#!/usr/bin/env python3
"""
rand0_display — Rand/0 Display Mode 本地 WebSocket 推送。

参考协议：
  https://dot.mindreset.tech/docs/rand_0/start/features/display_mode
  https://github.com/MindReset/dot_open_platform/tree/main/capabilities/rand_0_display_mode

针对 MindReset Rand/0 设备（200×200 墨水屏）的 Display Mode：
  - 通过本地 WebSocket 把 AI 额度仪表盘渲染成 200×200 图片并推送
  - 支持黑白（bw，1 bit/px，5000 字节）与四级灰（gray4，2 bit/px，10000 字节）
  - 监听设备的按钮事件 / 错误 JSON

对外接口：
  render_frame(snapshot, mode) -> bytes   # 渲染并打包成二进制帧
  push_frame(ip, mode, payload) -> int     # 通过 WebSocket 推送一帧，返回收到的消息数
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

# 字段内容必须与项目其他模块一致：codex 双窗口 + deepseek 余额 + 更新时刻
from display import format_reset_credits

from websocket import (
    WebSocket,
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
)
from websocket._exceptions import WebSocketBadStatusException

# ── 常量 ──────────────────────────────────────────────────────────────────

SIZE = 200                 # 显示器边长（200×200 像素）
BW_SIZE = SIZE * SIZE // 8          # bw：每像素 1 bit → 5000 字节
GRAY4_SIZE = SIZE * SIZE // 4       # gray4：每像素 2 bit → 10000 字节

import sys
from pathlib import Path

PAD = 10                   # 内边距


def _resource_dir(sub: str) -> Path:
    """返回资源目录。PyInstaller 打包后在 _MEIPASS 临时目录中查找。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / sub


FONT_DIR = _resource_dir("assets/fonts")
PIXEL_FONT = FONT_DIR / "PixelOperator.ttf"
VCR_FONT = FONT_DIR / "VCR_OSD_MONO_1.001.ttf"
# 微软雅黑粗体（系统字体，笔画粗、清晰度高，适合电子墨水屏）
_SYSTEM_BOLD_FONT = r"C:\Windows\Fonts\msyhbd.ttc"


def _pick_bold_font() -> Path:
    """优先返回系统微软雅黑粗体，找不到则回退内置像素字体。"""
    if Path(_SYSTEM_BOLD_FONT).exists():
        return Path(_SYSTEM_BOLD_FONT)
    return PIXEL_FONT


_BODY_FONT = _pick_bold_font()

BLACK = 0
WHITE = 255

# gray4 的四个灰度等级：00=白 01=浅灰 10=深灰 11=黑（像素值 0 为黑、255 为白）
_GRAY4_LEVELS = (255, 170, 85, 0)

# 进度条几何参数（针对 200 宽重新紧凑排版）
BAR_H = 14
ROW_H = 23


# ── 字体 ──────────────────────────────────────────────────────────────────

def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    """使用中文粗体字体（微软雅黑粗体，回退像素字体）加载。"""
    return ImageFont.truetype(str(path), size)


# ── 200×200 布局渲染 ───────────────────────────────────────────────────────

def _tsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    """返回文本像素宽高。"""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_bar(draw, x, y, w, h, used_pct):
    """简单的进度条：外框 + 填充（filled=剩余）。"""
    used_pct = max(0, min(100, used_pct or 0))
    remaining = 100 - used_pct
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=BLACK)
    filled = int((w - 2) * remaining / 100)
    if filled > 0:
        draw.rectangle([x + 1, y + 1, x + filled, y + h - 2], fill=BLACK)


def _draw_codex_row(draw, y, label_text, used_pct, reset_str, font):
    """绘制一行 Codex：标签 + 进度条 + 剩余%。"""
    bar_y = y + (ROW_H - BAR_H) // 2

    lh = font.size
    draw.text((PAD, bar_y), label_text, font=font, fill=BLACK)
    lw, _ = _tsize(draw, label_text, font)

    # 右侧文本：剩余% + 重置时间
    remaining = 100 - used_pct if used_pct is not None else 0
    note = f"{remaining:.0f}%" if reset_str in (None, "?") else f"{remaining:.0f}% {reset_str}"
    nw, nh = _tsize(draw, note, font)
    note_x = SIZE - PAD - nw
    draw.text((note_x, bar_y), note, font=font, fill=BLACK)

    # 进度条从标签实际宽度之后开始，避免 "Week" 这类较长标签被遮挡
    bar_x = PAD + lw + 6
    bar_w = note_x - 4 - bar_x
    if bar_w > 0:
        _draw_bar(draw, bar_x, bar_y, bar_w, BAR_H, used_pct)
    return y + ROW_H


def _render_bw_image(snap: dict, invert: bool = False) -> Image.Image:
    """渲染 200×200 纯黑白图片。invert=True 时反显（黑底白字）。"""
    img = Image.new("L", (SIZE, SIZE), WHITE)
    draw = ImageDraw.Draw(img)
    _draw_layout(draw, snap)
    if invert:
        img = ImageOps.invert(img)
    return img.convert("1", dither=Image.Dither.NONE)


def _render_gray4_image(snap: dict, invert: bool = False) -> Image.Image:
    """渲染 200×200 四级灰图片（像素值取 0/85/170/255）。invert=True 时反显。"""
    img = Image.new("L", (SIZE, SIZE), WHITE)
    draw = ImageDraw.Draw(img)
    _draw_layout(draw, snap)
    if invert:
        # 在量化前先反显，保证四个灰度级反向映射正确
        img = ImageOps.invert(img)
    # 把灰度图量化到 4 级
    return img.point(_gray4_quantize)


def _gray4_quantize(v: int) -> int:
    """把单点灰度值映射到四级灰（用于 Image.point）。"""
    if v < 42:
        return _GRAY4_LEVELS[3]     # 11=黑
    if v < 128:
        return _GRAY4_LEVELS[2]     # 10=深灰
    if v < 213:
        return _GRAY4_LEVELS[1]     # 01=浅灰
    return _GRAY4_LEVELS[0]         # 00=白


def _draw_layout(draw: ImageDraw.ImageDraw, snap: dict):
    """在给定的 ImageDraw 上绘制 200×200 仪表盘内容（黑白/灰共用）。"""
    cx = snap.get("codex", {})
    ds = snap.get("deepseek", {})
    ts = snap.get("updated_at", datetime.now().strftime("%H:%M"))

    label = _font(_BODY_FONT, 13)   # 标签/进度文本（雅黑粗体，清晰）
    bal = _font(_BODY_FONT, 18)     # DeepSeek 余额
    small = _font(_BODY_FONT, 11)   # 时间戳
    reset_font = _font(_BODY_FONT, 13)  # 重置卡信息（同正文）

    # ── 时间戳（右上角） ────────────────────────────────────────────────
    tsw, _ = _tsize(draw, ts, small)
    draw.text((SIZE - PAD - tsw, 8), ts, font=small, fill=BLACK)

    # ── CODEX ──────────────────────────────────────────────────────────
    y = 14
    draw.text((PAD, y), "CODEX", font=label, fill=BLACK)

    card_text = format_reset_credits(cx.get("reset_credits"), compact=True)
    if card_text and cx.get("ok"):
        # 重置卡信息单独一行（16px），避免与标题/时间戳拥挤导致看不清
        y += 20
        draw.text((PAD, y), card_text, font=reset_font, fill=BLACK)
        _, card_h = _tsize(draw, card_text, reset_font)
        y += card_h + 2
    else:
        y += 20

    if cx.get("ok"):
        short_label = cx.get("short_label", "5h")
        short_used = cx.get("short_used_percent")
        short_reset = cx.get("short_reset", "?")

        y = _draw_codex_row(draw, y, short_label, short_used, short_reset, label)

        long_label = cx.get("long_label", "Wk")
        long_used = cx.get("long_used_percent")
        long_reset = cx.get("long_reset", "?")
        y = _draw_codex_row(draw, y, long_label, long_used, long_reset, label)
    else:
        status = cx.get("raw_status", "error")
        draw.text((PAD, y + 4), status, font=label, fill=BLACK)
        y += 24

    # ── 分隔线（6px dash / 4px gap） ────────────────────────────────────
    y += 8
    dash, gap = 6, 4
    x = 0
    while x < SIZE:
        draw.line([(x, y), (min(x + dash - 1, SIZE), y)], fill=BLACK, width=1)
        x += dash + gap
    y += 12

    # ── DEEPSEEK ────────────────────────────────────────────────────────
    draw.text((PAD, y), "DEEPSEEK", font=label, fill=BLACK)
    y += 20

    if ds.get("ok"):
        bal_val = ds.get("balance")
        sym = ds.get("symbol", "$")
        bal_text = f"{sym}{bal_val:.2f}" if bal_val is not None else "?"
        draw.text((PAD, y), bal_text, font=bal, fill=BLACK)
        _, bh = _tsize(draw, bal_text, bal)

        status = ds.get("status", "ok").upper()
        sw, sh = _tsize(draw, status, label)
        draw.text((SIZE - PAD - sw, y + bh - sh), status, font=label, fill=BLACK)
    else:
        status = ds.get("raw_status", "error")
        draw.text((PAD, y), status, font=label, fill=BLACK)


# ── 位打包 ──────────────────────────────────────────────────────────────────

def _pack_bw(img: Image.Image) -> bytes:
    """把 200×200 黑白图打包为 5000 字节。1=白 0=黑，行主序，高层位在左。"""
    # convert("1") 位图上 tobytes() 已经按 1bit 打包，需先转回 L 取逐像素 0/255
    data = img.convert("L").tobytes()
    if len(data) != SIZE * SIZE:
        raise ValueError(f"bw 像素数异常：{len(data)}")
    out = bytearray(BW_SIZE)
    for i, pixel in enumerate(data):
        byte_idx = i >> 3
        bit_idx = 7 - (i & 7)
        if pixel:  # 非 0 视为白 → 置 1
            out[byte_idx] |= 1 << bit_idx
    return bytes(out)


def _pack_gray4(img: Image.Image) -> bytes:
    """把 200×200 四级灰图打包为 10000 字节。00=白 01=浅灰 10=深灰 11=黑，行主序。"""
    # 先把量化后的灰度映射回 2bit 值：0→3, 85→2, 170→1, 255→0
    lut = {0: 3, 85: 2, 170: 1, 255: 0}
    data = img.tobytes()  # "L" 模式每像素 1 字节
    if len(data) != SIZE * SIZE:
        raise ValueError(f"gray4 像素数异常：{len(data)}")
    out = bytearray(GRAY4_SIZE)
    for i, pixel in enumerate(data):
        if pixel not in lut:
            # 非标准灰度值就近映射（理论上 point 后只可能是 0/85/170/255）
            pixel = min(_GRAY4_LEVELS, key=lambda v: abs(v - pixel))
        two_bit = lut[pixel]
        byte_idx = i >> 2
        shift = 6 - 2 * (i & 3)  # 每字节 4 像素，首像素 bit7-6
        out[byte_idx] |= two_bit << shift
    return bytes(out)


def render_frame(snapshot: dict, mode: str = "bw", invert: bool = False) -> bytes:
    """渲染 200×200 仪表盘并打包为 Display Mode 二进制帧。

    mode  : "bw"（5000 字节）或 "gray4"（10000 字节）。
    invert: True 时反显（黑底白字）。
    """
    if mode == "bw":
        img = _render_bw_image(snapshot, invert)
        return _pack_bw(img)
    if mode == "gray4":
        img = _render_gray4_image(snapshot, invert)
        return _pack_gray4(img)
    raise ValueError(f"未知模式：{mode}")


# ── WebSocket 推送 ──────────────────────────────────────────────────────────

WS_TIMEOUT = 5.0  # 连接/收发超时（秒）


def push_frame(ip: str, mode: str, payload: bytes, timeout: float = WS_TIMEOUT,
               on_message=None) -> int:
    """通过 Display Mode WebSocket 推送一帧图片。

    参数：
      ip         : 设备显示的本地 IP
      mode       : "bw" 或 "gray4"
      payload    : render_frame 产出的二进制帧
      timeout    : 连接/收发超时（秒）
      on_message : 可选回调，设备每回传一条文本消息（按钮事件/错误）时调用
                   `on_message(text)`，用于 GUI 展示。

    返回：
      设备回传的消息数量（按钮事件或错误）。连接建立即成功返回。

    异常：
      依具体错误抛 RuntimeError 并携带可读信息。
    """
    expected = BW_SIZE if mode == "bw" else GRAY4_SIZE
    if len(payload) != expected:
        raise ValueError(f"{mode} 帧长度应为 {expected}，实际 {len(payload)}")

    ws = WebSocket()
    ws.settimeout(timeout)
    url = f"ws://{ip}/display/{mode}"
    try:
        try:
            ws.connect(url)
        except WebSocketBadStatusException as e:
            raise RuntimeError(f"握手失败 HTTP {e.status_code}: {e.resp_headers}") from e
        except WebSocketTimeoutException as e:
            raise RuntimeError(f"连接超时：{url}（请确认设备已进入 Display Mode 且 IP 正确）") from e

        # 发送二进制单帧
        ws.send_binary(payload)

        # 读取设备消息（按钮事件 / 错误）。墨水屏推送后一般不主动回帧，
        # 但按钮事件会实时到达；一次性读取超时即视为发送完成。
        received = 0
        try:
            while True:
                msg = ws.recv()
                if msg is None:
                    break
                received += 1
                if on_message:
                    on_message(str(msg))
                print(f"[rand0] 设备消息: {msg}")
        except (WebSocketTimeoutException, WebSocketConnectionClosedException):
            pass
        return received
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ── 命令行入口（预览/自检） ──────────────────────────────────────────────────

def preview(mode: str = "bw", out_path: str | None = None, invert: bool = False):
    """渲染示例快照并保存 PNG（便于本地预览布局）。invert=True 时反显。"""
    snap = {
        "codex": {"ok": True, "short_label": "5h", "short_used_percent": 72,
                  "short_reset": "2h13m", "long_label": "Week",
                  "long_used_percent": 41, "long_reset": "123h3m",
                  "reset_credits": {"available_count": 1,
                                    "credits": [{"expires_at": "09/24 19:01"}]},
                  "status": "ok"},
        "deepseek": {"ok": True, "balance": 18.42, "currency": "USD",
                     "symbol": "$", "status": "ok"},
        "updated_at": "16:40",
    }
    suffix = "inv" if invert else ""
    out = Path(out_path or f"preview_rand0_{mode}{suffix}.png")
    if mode == "bw":
        _render_bw_image(snap, invert).save(out)
    else:
        _render_gray4_image(snap, invert).save(out)
    print(f"Saved {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rand/0 Display Mode 渲染/自检")
    parser.add_argument("--preview", action="store_true", help="本地预览 200×200 布局（不推送）")
    parser.add_argument("--mode", default="bw", choices=["bw", "gray4"])
    parser.add_argument("--invert", action="store_true", help="反显（黑底白字）")
    args = parser.parse_args()

    if args.preview:
        preview(args.mode, invert=args.invert)
    else:
        # 自检：校验渲染与帧长度
        import json
        sample = {
            "codex": {"ok": True, "short_label": "5h", "short_used_percent": 72,
                      "short_reset": "2h13m", "long_label": "Week",
                      "long_used_percent": 41, "long_reset": "123h3m",
                      "reset_credits": {"available_count": 0, "credits": []},
                      "status": "ok"},
            "deepseek": {"ok": True, "balance": 18.42, "currency": "USD",
                         "symbol": "$", "status": "ok"},
            "updated_at": "16:40",
        }
        for m in ("bw", "gray4"):
            frame = render_frame(sample, m)
            expect = BW_SIZE if m == "bw" else GRAY4_SIZE
            print(f"{m}: {len(frame)} bytes (expected {expect}) {'OK' if len(frame) == expect else 'FAIL'}")