#!/usr/bin/env python3
"""
程序说明：为 Quote0Local 提供 ESP32-S3 RLCD（400×300）无线投屏渲染与推送接入。

功能职责：
1. 解析 .env 中的 RLCD_CAST_* 配置（默认关闭，支持跟随主窗口 bar/ring 双模板与反显）。
2. 复用 display.py 拉取到的 AI 额度快照，使用 Pillow 绘制高对比纯黑白 400×300 PNG。
3. 通过 HTTP POST（/push）自动或手动将图像推送到 xiaozhi-esp32 cast_server 后台服务。
"""

from __future__ import annotations

import io
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_WIDTH = 400
DEFAULT_HEIGHT = 300
DEFAULT_URL = "http://127.0.0.1:8787/push"
DEFAULT_TIMEOUT = 5.0

BLACK = 0
WHITE = 255


@dataclass
class RlcdCastConfig:
    """无线投屏自动推送配置对象。"""

    enabled: bool = False
    url: str = DEFAULT_URL
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    template: str = "sync"  # sync | bar | ring
    invert: bool = False
    push_now: bool = True
    timeout: float = DEFAULT_TIMEOUT


def _parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on", "y"):
        return True
    if text in ("0", "false", "no", "off", "n", ""):
        return False
    return default


def _parse_int(raw: Any, default: int, min_val: int, max_val: int) -> int:
    try:
        val = int(str(raw).strip())
        if min_val <= val <= max_val:
            return val
    except (TypeError, ValueError):
        pass
    return default


def _parse_float(raw: Any, default: float, min_val: float, max_val: float) -> float:
    try:
        val = float(str(raw).strip())
        if math.isfinite(val) and min_val <= val <= max_val:
            return val
    except (TypeError, ValueError):
        pass
    return default


def load_rlcd_cast_config(env: Optional[Mapping[str, str]] = None) -> RlcdCastConfig:
    """从环境变量或给定字典读取 RLCD_CAST_* 配置，异常值回退到安全默认值。"""
    src = env if env is not None else os.environ
    enabled = _parse_bool(src.get("RLCD_CAST_ENABLED"), False)
    raw_url = str(src.get("RLCD_CAST_URL") or DEFAULT_URL).strip() or DEFAULT_URL
    width = _parse_int(src.get("RLCD_CAST_WIDTH"), DEFAULT_WIDTH, 100, 2000)
    height = _parse_int(src.get("RLCD_CAST_HEIGHT"), DEFAULT_HEIGHT, 100, 2000)

    tpl = str(src.get("RLCD_CAST_TEMPLATE") or "sync").strip().lower()
    if tpl not in ("sync", "bar", "ring"):
        tpl = "sync"

    invert = _parse_bool(src.get("RLCD_CAST_INVERT"), False)
    push_now = _parse_bool(src.get("RLCD_CAST_PUSH_NOW"), True)
    timeout = _parse_float(src.get("RLCD_CAST_TIMEOUT"), DEFAULT_TIMEOUT, 0.5, 60.0)

    return RlcdCastConfig(
        enabled=enabled,
        url=raw_url,
        width=width,
        height=height,
        template=tpl,
        invert=invert,
        push_now=push_now,
        timeout=timeout,
    )


def normalize_cast_push_url(url: str, push_now: bool = True) -> str:
    """规范化推送地址：缺省路径自动补齐 /push，并按需附加 push_now=1 参数。"""
    raw = str(url or "").strip() or DEFAULT_URL
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    path = parsed.path or "/push"
    if path == "/":
        path = "/push"

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if push_now and not any(k == "push_now" for k, _ in query_pairs):
        query_pairs.append(("push_now", "1"))
    new_query = urlencode(query_pairs)
    return urlunparse(parsed._replace(path=path, query=new_query))


def _resource_dir(sub: str) -> Path:
    """返回项目内置资源目录（兼容 PyInstaller 单文件 _MEIPASS 解包路径）。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / sub


def _pick_font_source() -> tuple[Optional[Path], bool]:
    """优先选择系统微软雅黑粗体；返回 (字体路径, 是否支持完整中文)。"""
    candidates = (
        (Path(r"C:\Windows\Fonts\msyhbd.ttc"), True),
        (Path(r"C:\Windows\Fonts\msyh.ttc"), True),
        (Path(r"C:\Windows\Fonts\simhei.ttf"), True),
        (_resource_dir("assets/fonts/PixelOperator.ttf"), False),
    )
    for path, has_cjk in candidates:
        if path.exists():
            return path, has_cjk
    return None, False


_FONT_PATH, _FONT_HAS_CJK = _pick_font_source()
_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def _get_font(size: int) -> ImageFont.ImageFont:
    """按字号加载并缓存字体对象，任何异常均回退到 PIL 默认字体。"""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    font_obj: ImageFont.ImageFont
    if _FONT_PATH is not None:
        try:
            font_obj = ImageFont.truetype(str(_FONT_PATH), size)
            _FONT_CACHE[size] = font_obj
            return font_obj
        except Exception:
            pass
    font_obj = ImageFont.load_default()
    _FONT_CACHE[size] = font_obj
    return font_obj


def _tsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _is_num(val: Any) -> bool:
    """判断是否为有效有限数值（排除 bool）。"""
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _fmt_pct(val: Any) -> str:
    """将百分比格式化为简洁文本，避免长浮点挤压画布。"""
    if not _is_num(val):
        return "--%"
    clamped = max(0.0, min(100.0, float(val)))
    return f"{round(clamped, 1):g}%"


def _truncate_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    """按像素宽度安全截断超长文本并附加省略号。"""
    raw = str(text or "")
    if not raw or max_w <= 0:
        return ""
    if _tsize(draw, raw, font)[0] <= max_w:
        return raw
    ellipsis = "..."
    if _tsize(draw, ellipsis, font)[0] > max_w:
        return ""
    lo, hi = 0, len(raw)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _tsize(draw, raw[:mid] + ellipsis, font)[0] <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return raw[:lo] + ellipsis


def _status_tag(status: str, ok: bool) -> str:
    if not ok:
        return "ERR"
    return {"ok": "OK", "warn": "WARN", "hot": "HOT", "unknown": "--"}.get(str(status).lower(), "--")


def _draw_status_pill(draw: ImageDraw.ImageDraw, right_x: int, top_y: int, text: str, font: ImageFont.ImageFont, invert_pill: bool = True) -> int:
    """在指定右边界绘制状态标签徽章，返回占用宽度。"""
    pad_x = 6
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    bw = tw + pad_x * 2
    bh = th + 8
    x0 = right_x - bw
    text_x = x0 + pad_x - bbox[0]
    text_y = top_y + (bh - th) // 2 - bbox[1]
    if invert_pill:
        draw.rectangle((x0, top_y, right_x, top_y + bh), fill=BLACK)
        draw.text((text_x, text_y), text, font=font, fill=WHITE)
    else:
        draw.rectangle((x0, top_y, right_x, top_y + bh), outline=BLACK, width=1)
        draw.text((text_x, text_y), text, font=font, fill=BLACK)
    return bw


def _draw_dashed_line(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int) -> None:
    dash, gap = 6, 4
    x = x0
    while x < x1:
        draw.line((x, y, min(x + dash - 1, x1), y), fill=BLACK, width=1)
        x += dash + gap


def _draw_progress_bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, remaining_pct: Optional[float]) -> None:
    """绘制纯黑白高对比进度条：1px 实线框 + 内部实黑剩余填充。"""
    draw.rectangle((x, y, x + w - 1, y + h - 1), outline=BLACK, width=1)
    if not _is_num(remaining_pct):
        return
    clamped = max(0.0, min(100.0, float(remaining_pct)))
    inner_w = max(0, w - 4)
    fill_w = int(round(inner_w * clamped / 100.0))
    if fill_w > 0:
        draw.rectangle((x + 2, y + 2, x + 2 + fill_w - 1, y + h - 3), fill=BLACK)


def _draw_ring(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    diameter: int,
    remaining_pct: Optional[float],
    label_font: ImageFont.ImageFont,
) -> None:
    """绘制适用于 1-bit 单色屏的圆环进度图（细轨道外圈 + 粗黑色剩余弧线）。"""
    r = diameter // 2
    outer = (cx - r, cy - r, cx + r, cy + r)
    # 细 1px 轨道避免在 1-bit 屏幕丢轨
    draw.ellipse(outer, outline=BLACK, width=1)
    if _is_num(remaining_pct):
        val = max(0.0, min(100.0, float(remaining_pct)))
        if val >= 99.5:
            draw.ellipse(outer, outline=BLACK, width=5)
        elif val > 0:
            # PIL arc 按顺时针从 3 点钟方向计算角度，顶部 12 点钟为 -90°
            extent = 3.6 * val
            draw.arc(outer, start=-90, end=-90 + extent, fill=BLACK, width=5)
        pct_text = _fmt_pct(val)
    else:
        pct_text = "--%"
    bbox = draw.textbbox((0, 0), pct_text, font=label_font)
    tx = cx - (bbox[2] - bbox[0]) // 2 - bbox[0]
    ty = cy - (bbox[3] - bbox[1]) // 2 - bbox[1]
    draw.text((tx, ty), pct_text, font=label_font, fill=BLACK)


def _format_reset_parts(reset_credits: Any) -> tuple[str, str]:
    """拆分重置卡张数标题与有效期列表，供布局函数组合并避免重复。"""
    if not isinstance(reset_credits, dict):
        return "", ""
    count = reset_credits.get("available_count")
    if count is None:
        return "", ""
    try:
        cnt = max(0, int(count))
    except (TypeError, ValueError):
        return "", ""

    head = f"重置卡 {cnt}张" if _FONT_HAS_CJK else f"Reset {cnt}"
    if cnt <= 0:
        return head, ""
    cards = [
        str(c.get("expires_at"))
        for c in (reset_credits.get("credits") or [])
        if isinstance(c, dict) and c.get("expires_at")
    ]
    if not cards:
        return head, ""
    prefix = "到期 " if _FONT_HAS_CJK else "EXP "
    return head, prefix + "  ".join(cards[:4])


def _format_reset_lines(reset_credits: Any, first_line_cards: Optional[int] = None) -> tuple[str, str]:
    """将「重置卡 N张」置于「到期」之前；需双行展示时将剩余日期放到第二行。"""
    head, exp_str = _format_reset_parts(reset_credits)
    if not head:
        return "", ""
    if not exp_str:
        return head, ""
    prefix = "到期 " if _FONT_HAS_CJK else "EXP "
    dates_raw = exp_str[len(prefix):] if exp_str.startswith(prefix) else exp_str
    dates = [d for d in dates_raw.split("  ") if d]
    if first_line_cards is None or first_line_cards >= len(dates):
        return f"{head}  {exp_str}", ""
    line1_dates = "  ".join(dates[:first_line_cards])
    line2_dates = "  ".join(dates[first_line_cards:])
    return f"{head}  {prefix}{line1_dates}", line2_dates


def _draw_header(draw: ImageDraw.ImageDraw, width: int, snap: Mapping[str, Any]) -> None:
    """绘制顶部 28px 纯黑状态栏与右上角矢量状态指示灯。"""
    draw.rectangle((0, 0, width - 1, 27), fill=BLACK)
    f_title = _get_font(13)
    f_meta = _get_font(11)

    updated = str(snap.get("updated_at") or "--:--")
    title = f"AI 用量看板 · {updated}" if _FONT_HAS_CJK else f"AI QUOTA  {updated}"

    ag = snap.get("antigravity", {})
    cx = snap.get("codex", {})
    ds = snap.get("deepseek", {})
    items = (
        ("A", str(ag.get("status", "unknown")).lower(), bool(ag.get("ok"))),
        ("C", str(cx.get("status", "unknown")).lower(), bool(cx.get("ok"))),
        ("D", str(ds.get("status", "unknown")).lower(), bool(ds.get("ok"))),
    )
    dot_r = 3
    cur_x = width - 10
    for letter, st, ok_flag in reversed(items):
        lw, _ = _tsize(draw, letter, f_meta)
        cur_x -= lw
        draw.text((cur_x, 7), letter, font=f_meta, fill=WHITE)
        dot_cx = cur_x - 3 - dot_r
        dot_cy = 14
        if not ok_flag:
            draw.line((dot_cx - 3, dot_cy - 3, dot_cx + 3, dot_cy + 3), fill=WHITE, width=1)
            draw.line((dot_cx - 3, dot_cy + 3, dot_cx + 3, dot_cy - 3), fill=WHITE, width=1)
        elif st == "ok":
            draw.ellipse((dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r), fill=WHITE)
        else:
            draw.ellipse((dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r), outline=WHITE, width=1)
        cur_x = dot_cx - dot_r - 10

    title_max_w = max(80, cur_x - 4)
    draw.text((10, 5), _truncate_text(draw, title, f_title, title_max_w), font=f_title, fill=WHITE)


def _draw_bar_template(draw: ImageDraw.ImageDraw, width: int, height: int, snap: Mapping[str, Any]) -> None:
    """在 400×300 上绘制进度条风格（bar）完整面板。"""
    pad = 10
    f_sec = _get_font(12)
    f_row = _get_font(12)
    f_small = _get_font(11)
    f_big = _get_font(26)

    ag = snap.get("antigravity", {})
    cx = snap.get("codex", {})
    ds = snap.get("deepseek", {})

    # ── 1. ANTIGRAVITY 区（y = 34..140）──────────────────────────────────────
    y = 34
    draw.text((pad, y), "ANTIGRAVITY", font=f_sec, fill=BLACK)
    ag_tag = _status_tag(ag.get("status", "unknown"), bool(ag.get("ok")))
    if ag_tag != "OK":
        _draw_status_pill(draw, width - pad, y - 1, ag_tag, f_small, invert_pill=True)
    y += 20

    if ag.get("ok"):
        rows = ag.get("rows") or []
        parsed_rows = []
        max_rw = 64
        for row in rows[:4]:
            label = _truncate_text(draw, str(row.get("label") or "--"), f_row, 54)
            rem = row.get("remaining_percent")
            reset = str(row.get("reset") or "?")
            rtxt = _truncate_text(draw, f"{_fmt_pct(rem)}  {reset}", f_row, 150)
            rw, _ = _tsize(draw, rtxt, f_row)
            max_rw = max(max_rw, rw)
            parsed_rows.append((label, rem if _is_num(rem) else None, rtxt))
        bar_x = pad + 56
        bar_w = max(80, width - pad - max_rw - 8 - bar_x)
        for label, rem, rtxt in parsed_rows:
            draw.text((pad, y + 1), label, font=f_row, fill=BLACK)
            _draw_progress_bar(draw, bar_x, y + 3, bar_w, 12, rem)
            rw, _ = _tsize(draw, rtxt, f_row)
            draw.text((width - pad - rw, y + 1), rtxt, font=f_row, fill=BLACK)
            y += 20
    else:
        err_msg = _truncate_text(draw, f"ERROR: {ag.get('raw_status', 'unavailable')}", f_row, width - pad * 2)
        draw.text((pad, y + 8), err_msg, font=f_row, fill=BLACK)

    # 分隔线
    _draw_dashed_line(draw, pad, width - pad, 141)

    # ── 2. CODEX 区（y = 148..234）──────────────────────────────────────────
    y = 148
    draw.text((pad, y), "CODEX", font=f_sec, fill=BLACK)
    cx_tag = _status_tag(cx.get("status", "unknown"), bool(cx.get("ok")))
    if cx_tag != "OK":
        _draw_status_pill(draw, width - pad, y - 1, cx_tag, f_small, invert_pill=True)
    credits_info = cx.get("reset_credits") or {}
    reset_line1, _ = _format_reset_lines(credits_info)
    y += 21

    if cx.get("ok"):
        codex_rows = []
        for prefix, default_lbl in (("short", "5h"), ("long", "Wk")):
            used = cx.get(f"{prefix}_used_percent")
            rem = (100.0 - float(used)) if _is_num(used) else None
            reset = str(cx.get(f"{prefix}_reset") or "?")
            rtxt = _truncate_text(draw, f"{_fmt_pct(rem)}  {reset}", f_row, 165)
            lbl = _truncate_text(draw, str(cx.get(f"{prefix}_label") or default_lbl), f_row, 38)
            codex_rows.append((lbl, rem, rtxt))
        max_rw = max(64, *(_tsize(draw, item[2], f_row)[0] for item in codex_rows))
        bar_x = pad + 42
        bar_w = max(90, width - pad - max_rw - 8 - bar_x)
        for lbl, rem, rtxt in codex_rows:
            draw.text((pad, y + 1), lbl, font=f_row, fill=BLACK)
            _draw_progress_bar(draw, bar_x, y + 3, bar_w, 12, rem)
            rw, _ = _tsize(draw, rtxt, f_row)
            draw.text((width - pad - rw, y + 1), rtxt, font=f_row, fill=BLACK)
            y += 21

        # 重置卡张数放在到期日期前面，统一展示在底部同一行
        if reset_line1:
            draw.text((pad, y + 1), _truncate_text(draw, reset_line1, f_small, width - pad * 2), font=f_small, fill=BLACK)
    else:
        err_msg = _truncate_text(draw, f"ERROR: {cx.get('raw_status', 'unavailable')}", f_row, width - pad * 2)
        draw.text((pad, y + 6), err_msg, font=f_row, fill=BLACK)

    # 分隔线
    _draw_dashed_line(draw, pad, width - pad, 237)

    # ── 3. DEEPSEEK 区（y = 244..294）：左侧标题，右侧右对齐金额 ──────────
    if ds.get("ok"):
        bal = ds.get("balance")
        sym = str(ds.get("symbol") or "$")
        bal_text = f"{sym}{float(bal):.2f}" if _is_num(bal) else f"{sym}?"
        ds_tag = _status_tag(ds.get("status", "ok"), True)
    else:
        bal_text = str(ds.get("raw_status") or "error")
        ds_tag = "ERR"

    title_w, _ = _tsize(draw, "DEEPSEEK", f_sec)
    left_end = pad + title_w
    if ds_tag != "OK":
        draw.text((pad, 246), "DEEPSEEK", font=f_sec, fill=BLACK)
        tag_bbox = draw.textbbox((0, 0), ds_tag, font=f_small)
        tag_w = (tag_bbox[2] - tag_bbox[0]) + 12
        _draw_status_pill(draw, pad + tag_w, 267, ds_tag, f_small, invert_pill=True)
        left_end = max(left_end, pad + tag_w)
    else:
        draw.text((pad, 260), "DEEPSEEK", font=f_sec, fill=BLACK)

    bal_max_w = max(80, width - pad - left_end - 12)
    safe_bal = _truncate_text(draw, bal_text, f_big, bal_max_w)
    bal_bbox = draw.textbbox((0, 0), safe_bal, font=f_big)
    bw = bal_bbox[2] - bal_bbox[0]
    bh = bal_bbox[3] - bal_bbox[1]
    bx = (width - pad) - bw - bal_bbox[0]
    by = 268 - bh // 2 - bal_bbox[1]
    draw.text((bx, by), safe_bal, font=f_big, fill=BLACK)


def _draw_ring_template(draw: ImageDraw.ImageDraw, width: int, height: int, snap: Mapping[str, Any]) -> None:
    """在 400×300 上绘制圆环风格（ring）完整面板。"""
    pad = 10
    f_sec = _get_font(12)
    f_ring = _get_font(12)
    f_small = _get_font(11)
    f_big = _get_font(22)

    ag = snap.get("antigravity", {})
    cx_data = snap.get("codex", {})
    ds = snap.get("deepseek", {})

    # ── 上半区：ANTIGRAVITY 4 圆环 ──────────────────────────────────────────
    draw.text((pad, 32), "ANTIGRAVITY", font=f_sec, fill=BLACK)
    ag_tag = _status_tag(ag.get("status", "unknown"), bool(ag.get("ok")))
    if ag_tag != "OK":
        _draw_status_pill(draw, width - pad, 31, ag_tag, f_small, invert_pill=True)

    if ag.get("ok"):
        rows = ag.get("rows") or []
        centers_x = (55, 152, 248, 345)
        for idx, ring_cx in enumerate(centers_x):
            row = rows[idx] if idx < len(rows) else {}
            lbl = _truncate_text(draw, str(row.get("label") or "--"), f_small, 90)
            rem = row.get("remaining_percent")
            reset = _truncate_text(draw, str(row.get("reset") or "--"), f_small, 92)
            _draw_ring(draw, ring_cx, 82, 52, rem if _is_num(rem) else None, f_ring)
            lw, _ = _tsize(draw, lbl, f_small)
            draw.text((ring_cx - lw // 2, 112), lbl, font=f_small, fill=BLACK)
            rw, _ = _tsize(draw, reset, f_small)
            draw.text((ring_cx - rw // 2, 128), reset, font=f_small, fill=BLACK)
    else:
        err_msg = _truncate_text(draw, f"ERROR: {ag.get('raw_status', 'unavailable')}", f_ring, width - pad * 2)
        draw.text((pad, 78), err_msg, font=f_ring, fill=BLACK)

    _draw_dashed_line(draw, pad, width - pad, 147)

    # ── 下半区左栏：CODEX 双圆环 + 重置卡 ────────────────────────────────────
    split_x = 248
    draw.line((split_x, 153, split_x, height - 8), fill=BLACK, width=1)

    draw.text((pad, 152), "CODEX", font=f_sec, fill=BLACK)
    cx_tag = _status_tag(cx_data.get("status", "unknown"), bool(cx_data.get("ok")))
    if cx_tag != "OK":
        _draw_status_pill(draw, split_x - 10, 151, cx_tag, f_small, invert_pill=True)

    credits_info = cx_data.get("reset_credits") or {}
    reset_line1, reset_line2 = _format_reset_lines(credits_info, first_line_cards=1)

    if cx_data.get("ok"):
        specs = (("short", "5h", 68), ("long", "Wk", 180))
        for prefix, default_lbl, ring_cx in specs:
            used = cx_data.get(f"{prefix}_used_percent")
            rem = (100.0 - float(used)) if _is_num(used) else None
            lbl = str(cx_data.get(f"{prefix}_label") or default_lbl)
            reset = str(cx_data.get(f"{prefix}_reset") or "?")
            _draw_ring(draw, ring_cx, 197, 50, rem, f_ring)
            cap = _truncate_text(draw, f"{lbl}  {reset}", f_small, 108)
            cw, _ = _tsize(draw, cap, f_small)
            draw.text((ring_cx - cw // 2, 227), cap, font=f_small, fill=BLACK)

        if reset_line1:
            draw.text((pad, 248), _truncate_text(draw, reset_line1, f_small, split_x - pad - 10), font=f_small, fill=BLACK)
        if reset_line2:
            draw.text((pad, 266), _truncate_text(draw, reset_line2, f_small, split_x - pad - 10), font=f_small, fill=BLACK)
    else:
        err_msg = _truncate_text(draw, f"ERR: {cx_data.get('raw_status', 'unavailable')}", f_ring, split_x - pad - 10)
        draw.text((pad, 205), err_msg, font=f_ring, fill=BLACK)

    # ── 下半区右栏：DEEPSEEK 余额（右对齐贴齐右侧边界）────────────────────
    right_x = split_x + 12
    right_max_w = max(60, width - pad - right_x)
    draw.text((right_x, 152), "DEEPSEEK", font=f_sec, fill=BLACK)
    if ds.get("ok"):
        bal = ds.get("balance")
        sym = str(ds.get("symbol") or "$")
        bal_text = f"{sym}{float(bal):.2f}" if _is_num(bal) else f"{sym}?"
        ds_tag = _status_tag(ds.get("status", "ok"), True)
    else:
        bal_text = str(ds.get("raw_status") or "error")
        ds_tag = "ERR"

    if ds_tag != "OK":
        _draw_status_pill(draw, width - pad, 151, ds_tag, f_small, invert_pill=True)

    safe_bal = _truncate_text(draw, bal_text, f_big, right_max_w)
    bal_bbox = draw.textbbox((0, 0), safe_bal, font=f_big)
    bw = bal_bbox[2] - bal_bbox[0]
    bh = bal_bbox[3] - bal_bbox[1]
    bx = (width - pad) - bw - bal_bbox[0]
    by = 216 - bh // 2 - bal_bbox[1]
    draw.text((bx, by), safe_bal, font=f_big, fill=BLACK)


def render_rlcd_image(
    snapshot: Mapping[str, Any],
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    template: str = "bar",
    invert: bool = False,
) -> Image.Image:
    """按设备原生 400×300 横屏布局渲染 AI 用量快照；若目标尺寸不同则等比缩放输出。"""
    img = Image.new("L", (DEFAULT_WIDTH, DEFAULT_HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    safe_snap = snapshot if isinstance(snapshot, Mapping) else {}
    _draw_header(draw, DEFAULT_WIDTH, safe_snap)
    if str(template).lower() == "ring":
        _draw_ring_template(draw, DEFAULT_WIDTH, DEFAULT_HEIGHT, safe_snap)
    else:
        _draw_bar_template(draw, DEFAULT_WIDTH, DEFAULT_HEIGHT, safe_snap)

    if width != DEFAULT_WIDTH or height != DEFAULT_HEIGHT:
        img = img.resize((width, height), resample=Image.Resampling.LANCZOS)

    if invert:
        img = ImageOps.invert(img)
    return img.convert("1", dither=Image.Dither.NONE)


def render_rlcd_png(
    snapshot: Mapping[str, Any],
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    template: str = "bar",
    invert: bool = False,
) -> bytes:
    """渲染 400×300 单色 PNG 字节流，供直接上传到后台 /push 接口。"""
    img = render_rlcd_image(snapshot, width=width, height=height, template=template, invert=invert)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def push_snapshot_to_cast(
    snapshot: Mapping[str, Any],
    config: RlcdCastConfig,
    template_override: Optional[str] = None,
    post_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """将快照渲染并推送到无线投屏后台 /push；捕获全部异常确保主界面稳定。"""
    chosen_tpl = template_override or config.template
    if chosen_tpl not in ("bar", "ring"):
        chosen_tpl = "bar"

    try:
        png_bytes = render_rlcd_png(
            snapshot,
            width=config.width,
            height=config.height,
            template=chosen_tpl,
            invert=config.invert,
        )
    except Exception as exc:
        return {"ok": False, "error": f"渲染失败: {exc}"}

    target_url = normalize_cast_push_url(config.url, push_now=config.push_now)
    sender = post_fn or requests.post

    try:
        resp = sender(
            target_url,
            data=png_bytes,
            headers={"Content-Type": "image/png"},
            timeout=config.timeout,
        )
        status_code = getattr(resp, "status_code", 0)
        if status_code >= 400:
            err_detail = ""
            try:
                err_detail = str(resp.json().get("error") or "")
            except Exception:
                err_detail = str(getattr(resp, "text", ""))[:160]
            return {"ok": False, "status_code": status_code, "error": err_detail or f"HTTP {status_code}"}

        payload: dict[str, Any] = {}
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        return {"ok": True, "status_code": status_code, "response": payload, "bytes": len(png_bytes)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
