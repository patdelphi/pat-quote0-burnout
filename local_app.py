#!/usr/bin/env python3
"""
quote0-burnout 本地弹窗 — Windows 桌面置顶显示 AI 额度数据。

功能：
  - 从 Antigravity、Codex（OpenAI）和 DeepSeek 获取实时用量/余额
  - tkinter 无边框置顶窗口，深色主题，像素风格
  - 支持分别折叠/展开 Antigravity、Codex、DeepSeek 模块
  - 每 5 分钟自动刷新，双击或 F5 手动刷新，+/- 调整字号，/* 调整透明度
  - 支持拖动、系统托盘最小化

用法：
  python local_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from env_util import ensure_env


def _config_dir() -> Path:
    """用户配置文件目录：打包后为 exe 所在目录，源码运行时为项目目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _resource_dir(sub: str) -> Path:
    """资源目录（字体等）：打包后从 _MEIPASS 临时目录读取。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / sub


# 必须先加载 .env，再导入 display（display 在模块级别读取环境变量）
env_path = _config_dir() / ".env"

# 如果 .env 不存在，自动创建（同时生成 .env.sample 模板）
ensure_env(_config_dir())

if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            # 去掉行内注释
            if " #" in line:
                line = line.split(" #", 1)[0]
            # 支持 shell 格式：export KEY="value"
            if line.startswith("export "):
                line = line[7:]
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)

import ctypes
import math
import threading
import tkinter as tk
from dataclasses import replace
from tkinter import font as tkfont

from display import build_snapshot
from rlcd_cast import load_rlcd_cast_config, push_snapshot_to_cast
from tray_util import TrayManager

# ── 配置 ──────────────────────────────────────────────────────────────────────

REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "300"))  # 秒，默认 5 分钟
WINDOW_OPACITY   = float(os.environ.get("WINDOW_OPACITY", "0.92"))  # 不透明度
WINDOW_WIDTH     = 504
WINDOW_HEIGHT    = 390

# 颜色方案（Catppuccin Mocha 风格）
BG_COLOR      = "#1e1e2e"
FG_COLOR      = "#cdd6f4"
FG_DIM        = "#6c7086"
FG_OK         = "#a6e3a1"   # 绿色
FG_WARN       = "#f9e2af"   # 黄色
FG_HOT        = "#f38ba8"   # 红色
BAR_BG        = "#313244"
BAR_FILL_OK   = "#a6e3a1"
BAR_FILL_WARN = "#f9e2af"
BAR_FILL_HOT  = "#f38ba8"
DIVIDER       = "#45475a"

# 字体路径
ASSETS_DIR = _resource_dir("assets/fonts")
PIXEL_FONT_PATH = ASSETS_DIR / "PixelOperator.ttf"
VCR_FONT_PATH   = ASSETS_DIR / "VCR_OSD_MONO_1.001.ttf"

# ── 状态颜色映射 ──────────────────────────────────────────────────────────────

def status_color(status: str) -> str:
    """根据状态返回对应颜色。"""
    return {"ok": FG_OK, "warn": FG_WARN, "hot": FG_HOT}.get(status, FG_DIM)


def bar_color(status: str) -> str:
    """根据状态返回进度条填充色。"""
    return {"ok": BAR_FILL_OK, "warn": BAR_FILL_WARN, "hot": BAR_FILL_HOT}.get(status, FG_DIM)


def format_reset_credit_details(reset_credits):
    """在一行显示到期时间，缺失的明细单独标注。"""
    if not isinstance(reset_credits, dict) or reset_credits.get("available_count") is None:
        return "重置卡 --"
    try:
        count = max(0, int(reset_credits["available_count"]))
    except (TypeError, ValueError, OverflowError):
        return "重置卡 --"
    lines = [f"重置卡 {count}张"]
    if count:
        cards = reset_credits.get("credits")
        cards = [card for card in cards if isinstance(card, dict)] if isinstance(cards, list) else []
        dates = [str(card.get("expires_at") or "--") for card in cards]
        if dates:
            lines.append("到期 " + "  ".join(dates))
        if count > len(cards):
            lines.append(f"另有 {count - len(cards)} 张无详情")
    return "\n".join(lines)


# ── 主窗口类 ──────────────────────────────────────────────────────────────────

# Windows DPI 感知 — 必须在 tk.Tk() 之前设置
# 0= unaware, 1= system aware, 2= per-monitor aware
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


class Quote0Window:
    """AI 额度数据置顶弹窗。"""

    FONT_FAMILY = os.environ.get("FONT_FAMILY", "Arial")
    FONT_SIZE = int(os.environ.get("FONT_SIZE", "10"))
    FONT_SIZE_LARGE_OFFSET = int(os.environ.get("FONT_SIZE_LARGE_OFFSET", "4"))

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("quote0-burnout")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+100+100")
        self.root.overrideredirect(True)          # 无边框
        self.root.attributes("-topmost", True)    # 置顶
        self.root.configure(bg=BG_COLOR)

        # 系统托盘（最小化到托盘 / 退出）
        self.tray = TrayManager(self.root, "quote0-burnout")

        # Windows 无边框窗口设置透明度（SetLayeredWindowAttributes）
        self._opacity = max(0.0, min(1.0, WINDOW_OPACITY))
        self._set_window_opacity(self._opacity)

        # 拖动相关
        self._drag_x = 0
        self._drag_y = 0
        self.root.bind("<Button-1>", self._on_press)
        self.root.bind("<B1-Motion>", self._on_drag)
        self.root.bind("<Double-Button-1>", self._on_double_click)
        self.root.bind("<F5>", lambda _event: self.refresh())
        for key in ("<plus>", "<equal>", "<KP_Add>"):
            self.root.bind(key, lambda _event: self._change_font_size(1))
        for key in ("<minus>", "<KP_Subtract>"):
            self.root.bind(key, lambda _event: self._change_font_size(-1))
        for key in ("<slash>", "<KP_Divide>"):
            self.root.bind(key, lambda _event: self._change_opacity(-0.05))
        for key in ("<asterisk>", "<KP_Multiply>"):
            self.root.bind(key, lambda _event: self._change_opacity(0.05))
        for key in ("<KeyPress-1>", "<KP_1>"):
            self.root.bind(key, lambda _event: self._set_template("bar"))
        for key in ("<KeyPress-2>", "<KP_2>"):
            self.root.bind(key, lambda _event: self._set_template("ring"))

        # 无线投屏后台自动推送配置与防并发锁
        self._rlcd_config = load_rlcd_cast_config()
        self._rlcd_enabled_var = tk.BooleanVar(value=self._rlcd_config.enabled)
        self._rlcd_push_lock = threading.Lock()
        self._rlcd_seq_lock = threading.Lock()
        self._rlcd_push_seq = 0
        self._rlcd_last_result = None
        self._rlcd_timer_id = None

        # 右键菜单
        self._menu = tk.Menu(self.root, tearoff=0, bg=BG_COLOR, fg=FG_COLOR,
                             activebackground=DIVIDER, activeforeground=FG_COLOR)
        self._menu.add_command(label="刷新", command=self.refresh)
        self._menu.add_command(label="进度条模板 (1)", command=lambda: self._set_template("bar"))
        self._menu.add_command(label="圆环模板 (2)", command=lambda: self._set_template("ring"))
        self._menu.add_separator()
        self._menu.add_checkbutton(
            label="无线投屏自动推送",
            variable=self._rlcd_enabled_var,
            command=self._on_toggle_rlcd_cast,
        )
        self._menu.add_command(label="立即推送到 RLCD", command=self.push_to_rlcd_now)
        self._menu.add_separator()
        self._menu.add_command(label="最小化到托盘", command=self.tray.to_tray)
        self._menu.add_command(label="退出", command=self.quit)
        self.root.bind("<Button-3>", self._show_menu)

        # 字体（统一大小）
        self._setup_fonts()

        # 模块折叠状态（默认全部展开）
        self._collapsed = {"antigravity": False, "codex": False, "deepseek": False}
        self._sections = {}
        self._template = "bar"
        self._last_snapshot = None

        # 构建 UI
        self._build_ui()
        self._update_rings({})
        self._fit_window()
        self.root.after_idle(self.root.focus_force)

        # 首次加载数据
        self.refresh()

        # 定时刷新
        self._schedule_refresh()
        if self._rlcd_config.interval > 0:
            self._schedule_rlcd_push()

    def _resolve_font_family(self) -> str:
        """检查用户配置的字体是否存在，不存在则按平台回退。"""
        configured = self.FONT_FAMILY
        available = set(tkfont.families())

        if configured in available:
            return configured

        # 平台专用回退
        platform = sys.platform
        if platform == "win32":
            candidates = ["Microsoft YaHei", "SimHei", "Arial", "Segoe UI"]
        elif platform == "darwin":
            candidates = ["PingFang SC", "Heiti SC", "Helvetica Neue", "Arial"]
        else:  # linux / other
            candidates = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans", "Arial"]

        for c in candidates:
            if c in available:
                return c

        # 最终兜底：Tk 会映射到系统默认无衬线字体
        return "sans-serif"

    def _setup_fonts(self):
        """加载自定义字体（带跨平台兜底）。"""
        family = self._resolve_font_family()
        s = self.FONT_SIZE
        large = s + self.FONT_SIZE_LARGE_OFFSET
        # 使用共享字体对象，修改字号时所有关联控件同步更新。
        self.font_label = tkfont.Font(root=self.root, family=family, size=s, weight="bold")
        self.font_data = tkfont.Font(root=self.root, family=family, size=s)
        self.font_small = tkfont.Font(root=self.root, family=family, size=s)
        self.font_hint = tkfont.Font(root=self.root, family=family, size=max(5, int(s * 0.7)))
        self.font_large = tkfont.Font(root=self.root, family=family, size=large, weight="bold")

    def _fit_window(self, expand_only=False):
        """按当前内容调整尺寸，数据更新时保留用户手动放大的空间。"""
        self.root.update_idletasks()
        width = max(280, self.root.winfo_reqwidth())
        height = max(120, self.root.winfo_reqheight())
        if expand_only:
            width = max(width, self.root.winfo_width())
            height = max(height, self.root.winfo_height())
        # 只设置尺寸，保留窗口原有位置。
        self.root.geometry(f"{width}x{height}")

    def _change_font_size(self, delta):
        """调整共享字号，并为放大后的内容留出空间。"""
        current = self.font_data.cget("size")
        size = max(6, min(40, current + delta))
        for font in (self.font_label, self.font_data, self.font_small):
            font.configure(size=size)
        self.font_hint.configure(size=max(5, int(size * 0.7)))
        self.font_large.configure(size=max(1, size + self.FONT_SIZE_LARGE_OFFSET))
        self._update_rings(self._last_snapshot or {})
        self._fit_window()
        return "break"

    def _change_opacity(self, delta):
        """调整窗口不透明度，避免窗口因完全透明而无法操作。"""
        self._opacity = round(max(0.2, min(1.0, self._opacity + delta)), 2)
        self._set_window_opacity(self._opacity)
        return "break"

    def _set_template(self, template):
        """切换布局并复用已有数据，不改变折叠状态和窗口位置。"""
        if template not in ("bar", "ring") or template == self._template:
            return "break"
        self._template = template
        if template == "ring":
            self.ag_bars.pack_forget()
            self.codex_bars.pack_forget()
            self.ag_rings.pack(fill="x")
            self.codex_rings.pack(fill="x", before=self.lbl_reset_credits)
        else:
            self.ag_rings.pack_forget()
            self.codex_rings.pack_forget()
            self.ag_bars.pack(fill="x")
            self.codex_bars.pack(fill="x", before=self.lbl_reset_credits)
        self._fit_window()
        if self._last_snapshot and self._rlcd_config.enabled and self._rlcd_config.template == "sync":
            self._push_rlcd_async(self._last_snapshot)
        return "break"

    def _on_template_arrow(self, template):
        """点击标题栏箭头后保留键盘焦点。"""
        self.root.focus_force()
        return self._set_template(template)

    def _bind_collapsible(self, key: str, title_text: str, title_label: tk.Label, body_frame: tk.Frame):
        """注册可折叠模块，点击标题可切换展开/折叠并自适应窗口高度。"""
        self._sections[key] = {
            "title": title_text,
            "label": title_label,
            "body": body_frame,
        }
        title_label.config(cursor="hand2")
        title_label.bind("<Button-1>", lambda _e, k=key: self.toggle_section(k))

    def toggle_section(self, key: str) -> str:
        """切换指定模块的折叠状态。"""
        sec = self._sections.get(key)
        if not sec:
            return "break"

        collapsed = not self._collapsed.get(key, False)
        self._collapsed[key] = collapsed

        prefix = "▶" if collapsed else "▼"
        sec["label"].config(text=f"{prefix} {sec['title']}")
        if collapsed:
            sec["body"].pack_forget()
        else:
            sec["body"].pack(fill="x")

        # 折叠/展开后自适应窗口高度，保持当前宽度和位置
        self.root.update_idletasks()
        cur_w = max(self.root.winfo_width() or WINDOW_WIDTH, self.root.winfo_reqwidth())
        req_h = max(120, self.root.winfo_reqheight())
        self.root.geometry(f"{cur_w}x{req_h}")
        return "break"

    def _build_ring_group(self, parent, titles):
        """创建两列圆环及标题、重置时间控件。"""
        group = tk.Frame(parent, bg=BG_COLOR)
        error = tk.Label(group, text="", font=self.font_small, bg=BG_COLOR, fg=FG_HOT, anchor="w")
        grid = tk.Frame(group, bg=BG_COLOR)
        grid.pack(fill="x")
        items = []
        for index, title in enumerate(titles):
            cell = tk.Frame(grid, bg=BG_COLOR)
            cell.grid(row=index // 2, column=index % 2, padx=8, pady=3, sticky="n")
            grid.grid_columnconfigure(index % 2, weight=1)
            canvas = tk.Canvas(cell, bg=BG_COLOR, highlightthickness=0, bd=0)
            canvas.pack()
            label = tk.Label(cell, text=title, font=self.font_label, bg=BG_COLOR, fg=FG_COLOR)
            label.pack()
            reset = tk.Label(cell, text="--", font=self.font_small, bg=BG_COLOR, fg=FG_DIM)
            reset.pack()
            items.append({"canvas": canvas, "label": label, "reset": reset, "title": title})
        return group, items, error

    def _draw_ring(self, canvas, percent, status):
        """按剩余百分比绘制圆环；缺失数据用 --% 表示。"""
        valid = isinstance(percent, (int, float)) and math.isfinite(percent)
        value = max(0, min(100, percent)) if valid else None
        size = max(80, self.font_label.measure("100%") + 30, self.font_data.metrics("linespace") * 3)
        width = max(6, size // 12)
        inset = width // 2 + 3
        box = (inset, inset, size - inset, size - inset)
        canvas.config(width=size, height=size)
        canvas.delete("all")
        canvas.create_oval(*box, outline=BAR_BG, width=width)
        if value == 100:
            canvas.create_oval(*box, outline=bar_color(status), width=width, tags="arc")
        elif value is not None and value > 0:
            canvas.create_arc(*box, start=90, extent=-3.6 * value, style="arc",
                              outline=bar_color(status), width=width, tags="arc")
        text = f"{value:g}%" if value is not None else "--%"
        canvas.create_text(size // 2, size // 2, text=text, font=self.font_label,
                           fill=FG_COLOR, tags="percent")

    def _update_rings(self, snapshot):
        """将现有快照映射到圆环，不请求额外数据。"""
        ag = snapshot.get("antigravity", {})
        rows = ag.get("rows", []) if ag.get("ok") else []
        ag_error = str(ag.get("raw_status") or "error") if ag and not ag.get("ok") else ""
        self._set_ring_error(self.lbl_ag_ring_error, ag_error)
        for index, item in enumerate(self.ag_ring_items):
            row = rows[index] if index < len(rows) else {}
            item["label"].config(text=row.get("label") or item["title"])
            item["reset"].config(text=str(row.get("reset") or "--"))
            self._draw_ring(item["canvas"], row.get("remaining_percent"), row.get("status", "unknown"))

        cx = snapshot.get("codex", {})
        cx_error = str(cx.get("raw_status") or "error") if cx and not cx.get("ok") else ""
        self._set_ring_error(self.lbl_codex_ring_error, cx_error)
        for item, prefix in zip(self.codex_ring_items, ("short", "long")):
            used = cx.get(f"{prefix}_used_percent") if cx.get("ok") else None
            remaining = 100 - used if isinstance(used, (int, float)) else None
            item["label"].config(text=cx.get(f"{prefix}_label") or item["title"])
            item["reset"].config(text=str(cx.get(f"{prefix}_reset") or "--") if cx.get("ok") else "--")
            self._draw_ring(item["canvas"], remaining, cx.get("status", "unknown"))

    def _set_ring_error(self, label, text):
        """仅在出错时占用错误提示行。"""
        label.config(text=text)
        if text:
            label.pack(fill="x", before=label.master.winfo_children()[1])
        else:
            label.pack_forget()

    def _build_ui(self):
        """构建窗口界面。"""
        pad = 14

        # 标题栏：时间 + 状态灯
        self.header = tk.Frame(self.root, bg=BG_COLOR)
        self.header.pack(fill="x", padx=pad, pady=(pad, 2))

        self.lbl_time = tk.Label(self.header, text="--:--", font=self.font_small,
                                  bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_time.pack(side="left")

        self.lbl_prev_template = tk.Label(self.header, text="‹", font=self.font_label,
                                          bg=BG_COLOR, fg=FG_COLOR, cursor="hand2")
        self.lbl_prev_template.pack(side="left", padx=(8, 0))
        self.lbl_prev_template.bind("<Button-1>", lambda _event: self._on_template_arrow("bar"))
        self.lbl_next_template = tk.Label(self.header, text="›", font=self.font_label,
                                          bg=BG_COLOR, fg=FG_COLOR, cursor="hand2")
        self.lbl_next_template.pack(side="left")
        self.lbl_next_template.bind("<Button-1>", lambda _event: self._on_template_arrow("ring"))

        self.lbl_status = tk.Label(self.header, text="● A  ● C  ● D", font=self.font_small,
                                    bg=BG_COLOR, fg=FG_DIM)
        self.lbl_status.pack(side="right")

        # 分隔线
        tk.Frame(self.root, height=1, bg=DIVIDER).pack(fill="x", padx=pad, pady=2)

        # ── ANTIGRAVITY 区域（置于最上方）──────────────────────────────────
        self.ag_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.ag_frame.pack(fill="x", padx=pad, pady=(2, 0))

        self.lbl_ag_title = tk.Label(self.ag_frame, text="▼ ANTIGRAVITY", font=self.font_label,
                                      bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_ag_title.pack(anchor="w")

        self.ag_body = tk.Frame(self.ag_frame, bg=BG_COLOR)
        self.ag_body.pack(fill="x")

        self.ag_bars = tk.Frame(self.ag_body, bg=BG_COLOR)
        self.ag_bars.pack(fill="x")

        self.ag_rows = []
        for idx, default_label in enumerate(("Gem 5h", "Gem Wk", "Cld 5h", "Cld Wk")):
            row_frame = tk.Frame(self.ag_bars, bg=BG_COLOR)
            row_frame.pack(fill="x", pady=(2 if idx == 0 else 4, 0))

            lbl_label = tk.Label(row_frame, text=default_label, font=self.font_data,
                                 bg=BG_COLOR, fg=FG_COLOR, anchor="w", width=7)
            lbl_label.pack(side="left")

            canvas = tk.Canvas(row_frame, height=14, width=165, bg=BAR_BG,
                               highlightthickness=0, bd=0)
            canvas.pack(side="left", padx=(4, 4))

            lbl_info = tk.Label(row_frame, text="--% / --", font=self.font_data,
                                bg=BG_COLOR, fg=FG_COLOR, anchor="e")
            lbl_info.pack(side="left")

            self.ag_rows.append({"label": lbl_label, "canvas": canvas, "info": lbl_info})

        self.ag_rings, self.ag_ring_items, self.lbl_ag_ring_error = self._build_ring_group(
            self.ag_body, ("Gem 5h", "Gem Wk", "Cld 5h", "Cld Wk"))

        self._bind_collapsible("antigravity", "ANTIGRAVITY", self.lbl_ag_title, self.ag_body)

        # 分隔线
        tk.Frame(self.root, height=1, bg=DIVIDER).pack(fill="x", padx=pad, pady=3)

        # ── CODEX 区域 ──────────────────────────────────────────────────────
        self.codex_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.codex_frame.pack(fill="x", padx=pad, pady=(2, 0))

        self.lbl_codex_title = tk.Label(self.codex_frame, text="▼ CODEX", font=self.font_label,
                                         bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_codex_title.pack(anchor="w")

        self.codex_body = tk.Frame(self.codex_frame, bg=BG_COLOR)
        self.codex_body.pack(fill="x")

        self.codex_bars = tk.Frame(self.codex_body, bg=BG_COLOR)
        self.codex_bars.pack(fill="x")

        # 短窗口行：标签 + 进度条 + 数据（一行）
        self.row1_frame = tk.Frame(self.codex_bars, bg=BG_COLOR)
        self.row1_frame.pack(fill="x", pady=(2, 0))

        self.lbl_r1_label = tk.Label(self.row1_frame, text="5h", font=self.font_data,
                                      bg=BG_COLOR, fg=FG_COLOR, anchor="w", width=3)
        self.lbl_r1_label.pack(side="left")

        self.can_r1 = tk.Canvas(self.row1_frame, height=14, width=180, bg=BAR_BG,
                                 highlightthickness=0, bd=0)
        self.can_r1.pack(side="left", padx=(4, 4))

        self.lbl_r1_info = tk.Label(self.row1_frame, text="--% / --", font=self.font_data,
                                     bg=BG_COLOR, fg=FG_COLOR, anchor="e")
        self.lbl_r1_info.pack(side="left")

        # 长窗口行：标签 + 进度条 + 数据（一行）
        self.row2_frame = tk.Frame(self.codex_bars, bg=BG_COLOR)
        self.row2_frame.pack(fill="x", pady=(4, 0))

        self.lbl_r2_label = tk.Label(self.row2_frame, text="Wk", font=self.font_data,
                                      bg=BG_COLOR, fg=FG_COLOR, anchor="w", width=3)
        self.lbl_r2_label.pack(side="left")

        self.can_r2 = tk.Canvas(self.row2_frame, height=14, width=180, bg=BAR_BG,
                                 highlightthickness=0, bd=0)
        self.can_r2.pack(side="left", padx=(4, 4))

        self.lbl_r2_info = tk.Label(self.row2_frame, text="--% / --", font=self.font_data,
                                     bg=BG_COLOR, fg=FG_COLOR, anchor="e")
        self.lbl_r2_info.pack(side="left")

        # 重置卡信息：在一行显示所有可用到期时间。
        self.lbl_reset_credits = tk.Label(self.codex_body, text="重置卡 --", font=self.font_small,
                                           bg=BG_COLOR, fg=FG_COLOR, anchor="w", justify="left")
        self.lbl_reset_credits.pack(anchor="w", pady=(4, 0))
        self.lbl_reset_expiry = tk.Label(self.codex_body, text="", font=self.font_hint,
                                          bg=BG_COLOR, fg=FG_COLOR, anchor="w", justify="left")

        self.codex_rings, self.codex_ring_items, self.lbl_codex_ring_error = self._build_ring_group(
            self.codex_body, ("5h", "Wk"))

        self._bind_collapsible("codex", "CODEX", self.lbl_codex_title, self.codex_body)

        # 分隔线
        tk.Frame(self.root, height=1, bg=DIVIDER).pack(fill="x", padx=pad, pady=3)

        # ── DEEPSEEK 区域 ────────────────────────────────────────────────────
        self.ds_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.ds_frame.pack(fill="x", padx=pad, pady=(2, 8))

        self.lbl_ds_title = tk.Label(self.ds_frame, text="▼ DEEPSEEK", font=self.font_label,
                                      bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_ds_title.pack(anchor="w")

        self.ds_body = tk.Frame(self.ds_frame, bg=BG_COLOR)
        self.ds_body.pack(fill="x")

        self.ds_row = tk.Frame(self.ds_body, bg=BG_COLOR)
        self.ds_row.pack(fill="x")

        self.lbl_ds_balance = tk.Label(self.ds_row, text="$--.--", font=self.font_label,
                                        bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_ds_balance.pack(side="right")

        # 状态标签（仅 warn/hot 时显示，ok 时隐藏，放在余额下方）
        self.lbl_ds_status = tk.Label(self.ds_body, text="", font=self.font_data,
                                       bg=BG_COLOR, fg=FG_DIM)
        self.lbl_ds_status.pack(anchor="e")

        self._bind_collapsible("deepseek", "DEEPSEEK", self.lbl_ds_title, self.ds_body)

        # 底部显示快捷键，字号随主界面缩放。
        self.lbl_shortcuts = tk.Label(self.root, text="F5 刷新  +- 字号  /* 透明度  1/2 模板",
                                      font=self.font_hint, bg=BG_COLOR, fg=FG_DIM, anchor="w")
        self.lbl_shortcuts.pack(fill="x", padx=(pad, pad + 12), pady=(0, 8))

        # 右下角 resize handle
        self._resize_handle = tk.Frame(self.root, width=12, height=12, bg=DIVIDER, cursor="size_nw_se")
        self._resize_handle.place(relx=1.0, rely=1.0, anchor="se")
        self._resize_handle.bind("<Button-1>", self._on_resize_press)
        self._resize_handle.bind("<B1-Motion>", self._on_resize_drag)

    # ── 拖动 ────────────────────────────────────────────────────────────────────

    def _set_window_opacity(self, opacity: float):
        """使用 Windows API 设置无边框窗口透明度。"""
        try:
            from ctypes import wintypes

            hwnd = self.root.winfo_id()

            # 获取当前窗口样式
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000

            # 设置 Layered 窗口样式
            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)

            # 设置透明度 (0-255)
            LWA_ALPHA = 0x00000002
            alpha = int(255 * max(0.0, min(1.0, opacity)))
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
        except Exception:
            pass  # 失败则保持不透明

    def _on_press(self, event):
        self.root.focus_force()
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_resize_press(self, event):
        self._resize_x = event.x_root
        self._resize_y = event.y_root
        self._resize_w = self.root.winfo_width()
        self._resize_h = self.root.winfo_height()

    def _on_resize_drag(self, event):
        dw = event.x_root - self._resize_x
        dh = event.y_root - self._resize_y
        new_w = max(280, self._resize_w + dw)
        new_h = max(180, self._resize_h + dh)
        self.root.geometry(f"{new_w}x{new_h}")

    def _on_double_click(self, event):
        self.refresh()

    def _show_menu(self, event):
        self._menu.post(event.x_root, event.y_root)

    # ── 数据刷新 ────────────────────────────────────────────────────────────────

    def refresh(self):
        """在后台线程中获取数据并更新 UI。"""
        self.lbl_time.config(text="更新中...")
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
        """获取数据并在主线程中更新 UI。"""
        try:
            snapshot = build_snapshot()
        except Exception as e:
            snapshot = {
                "antigravity": {"ok": False, "rows": [], "raw_status": str(e)},
                "codex": {"ok": False, "raw_status": str(e)},
                "deepseek": {"ok": False, "raw_status": str(e)},
                "updated_at": "ERR",
            }
        self.root.after(0, lambda: self._update_ui_safe(snapshot))
        self._push_rlcd_async(snapshot)

    def _resolve_rlcd_template(self) -> str:
        """确定无线投屏使用的排版模板：sync 跟随窗口当前模板，否则使用 .env 指定模板。"""
        if self._rlcd_config.template == "sync":
            return self._template
        return self._rlcd_config.template

    def _push_rlcd_async(self, snapshot: dict, force: bool = False) -> None:
        """在后台线程渲染 400×300 PNG 并推送到无线投屏服务，捕获异常不阻塞弹窗。"""
        with self._rlcd_seq_lock:
            if not snapshot:
                return
            if not force and not self._rlcd_config.enabled:
                return
            cfg = replace(self._rlcd_config)
            tpl = self._resolve_rlcd_template()
            self._rlcd_push_seq += 1
            my_seq = self._rlcd_push_seq

        def worker():
            try:
                with self._rlcd_push_lock:
                    with self._rlcd_seq_lock:
                        if my_seq != self._rlcd_push_seq:
                            return
                    result = push_snapshot_to_cast(snapshot, cfg, template_override=tpl)
                    self._rlcd_last_result = result
                    if not result.get("ok") and sys.stderr is not None:
                        try:
                            sys.stderr.write(f"[Quote0Local][RLCD] 推送失败: {result.get('error', 'unknown')}\n")
                        except Exception:
                            pass
            except Exception as exc:
                self._rlcd_last_result = {"ok": False, "error": str(exc)}

        threading.Thread(target=worker, daemon=True).start()

    def _on_toggle_rlcd_cast(self) -> None:
        """右键开关：切换无线投屏自动推送；刚启用时立即推送并按需开启定时推流。"""
        enabled = bool(self._rlcd_enabled_var.get())
        with self._rlcd_seq_lock:
            self._rlcd_config.enabled = enabled
            interval = float(self._rlcd_config.interval)
        if enabled and interval > 0 and self._rlcd_timer_id is None:
            self._schedule_rlcd_push()
        elif enabled and self._last_snapshot:
            self._push_rlcd_async(self._last_snapshot)

    def push_to_rlcd_now(self) -> None:
        """手动触发一次向无线投屏后台推帧。"""
        if self._last_snapshot:
            self._push_rlcd_async(self._last_snapshot, force=True)
            return
        # 尚未完成首次拉取时后台拉取一帧并强制推送
        def worker():
            try:
                snap = build_snapshot()
            except Exception:
                return
            self.root.after(0, lambda: self._update_ui_safe(snap))
            self._push_rlcd_async(snap, force=True)

        threading.Thread(target=worker, daemon=True).start()

    def _update_ui_safe(self, snapshot: dict):
        """带异常捕获的 UI 更新，防止未处理异常导致程序退出。"""
        try:
            self._update_ui(snapshot)
            self._fit_window(expand_only=True)
        except Exception as e:
            self.lbl_time.config(text=f"UI错误: {e}", fg=FG_HOT)

    def _update_ui(self, snapshot: dict):
        """根据 snapshot 更新所有 UI 元素。"""
        ts = snapshot.get("updated_at", "--:--")
        self.lbl_time.config(text=ts, fg=FG_COLOR)

        ag = snapshot.get("antigravity", {})
        cx = snapshot.get("codex", {})
        ds = snapshot.get("deepseek", {})

        # 状态灯（按严重程度选取整体颜色）
        ag_st = ag.get("status", "unknown") if ag.get("ok") else "error"
        cx_st = cx.get("status", "unknown") if cx.get("ok") else "error"
        ds_st = ds.get("status", "unknown") if ds.get("ok") else "error"
        dot_map = {"ok": "●", "warn": "◐", "hot": "●", "unknown": "○", "error": "✕"}
        ag_dot = dot_map.get(ag_st, "○")
        cx_dot = dot_map.get(cx_st, "○")
        ds_dot = dot_map.get(ds_st, "○")
        severity = {"error": 4, "hot": 3, "warn": 2, "unknown": 1, "ok": 0}
        worst_st = max((ag_st, cx_st, ds_st), key=lambda s: severity.get(s, 0))
        status_text = f"{ag_dot} A  {cx_dot} C  {ds_dot} D"
        self.lbl_status.config(text=status_text, fg=status_color(worst_st))

        # Antigravity 四行（Gem 5h / Gem Wk / Cld 5h / Cld Wk）
        if ag.get("ok"):
            ag_data_rows = ag.get("rows", [])
            for idx, widget in enumerate(self.ag_rows):
                if idx < len(ag_data_rows):
                    row = ag_data_rows[idx]
                    rem = row.get("remaining_percent")
                    reset_str = row.get("reset", "?")
                    row_st = row.get("status", "unknown")
                    rem_val = rem if rem is not None else 0
                    rem_text = f"{rem}% / {reset_str}" if rem is not None else f"--% / {reset_str}"
                    widget["label"].config(text=row.get("label", ""))
                    widget["info"].config(text=rem_text, fg=status_color(row_st))
                    self._draw_bar(widget["canvas"], rem_val, row_st)
                else:
                    widget["label"].config(text="")
                    widget["info"].config(text="", fg=FG_DIM)
                    self._draw_bar(widget["canvas"], 0, "unknown")
        else:
            err = ag.get("raw_status", "error")
            for idx, widget in enumerate(self.ag_rows):
                if idx == 0:
                    widget["label"].config(text="AGY")
                    widget["info"].config(text=err, fg=FG_HOT)
                else:
                    widget["label"].config(text="")
                    widget["info"].config(text="", fg=FG_DIM)
                self._draw_bar(widget["canvas"], 0, "error")

        # Codex 行 1（一行：标签 + 进度条 + %/重置时间）
        if cx.get("ok"):
            s_pct = cx.get("short_used_percent")
            s_reset = cx.get("short_reset", "?")
            s_status = cx.get("status", "ok")
            remaining = 100 - s_pct if s_pct is not None else 0

            self.lbl_r1_label.config(text=cx.get("short_label", "5h"))
            self.lbl_r1_info.config(text=f"{remaining}% / {s_reset}", fg=status_color(s_status))
            self._draw_bar(self.can_r1, remaining, s_status)

            # Codex 行 2
            l_pct = cx.get("long_used_percent")
            l_reset = cx.get("long_reset", "?")
            l_status = cx.get("status", "ok")
            l_remaining = 100 - l_pct if l_pct is not None else 0

            self.lbl_r2_label.config(text=cx.get("long_label", "Wk"))
            self.lbl_r2_info.config(text=f"{l_remaining}% / {l_reset}", fg=status_color(l_status))
            self._draw_bar(self.can_r2, l_remaining, l_status)

            self._display_reset_credits(cx.get("reset_credits"))
        else:
            err = cx.get("raw_status", "error")
            self.lbl_r1_label.config(text="Codex")
            self.lbl_r1_info.config(text=err, fg=FG_HOT)
            self._draw_bar(self.can_r1, 0, "error")
            self.lbl_r2_label.config(text="")
            self.lbl_r2_info.config(text="", fg=FG_DIM)
            self._draw_bar(self.can_r2, 0, "error")
            self._display_reset_credits(None)

        # DeepSeek（ok 时不显示状态，仅 warn/hot/error 时显示）
        if ds.get("ok"):
            bal = ds.get("balance")
            sym = ds.get("symbol", "$")
            ds_status = ds.get("status", "ok")
            bal_text = f"{sym}{bal:.2f}" if bal is not None else "?"
            self.lbl_ds_balance.config(text=bal_text, fg=status_color(ds_status))
            # ok 状态隐藏，其他状态显示
            if ds_status == "ok":
                self.lbl_ds_status.config(text="", fg=FG_DIM)
            else:
                self.lbl_ds_status.config(text=ds_status.upper(), fg=status_color(ds_status))
        else:
            err = ds.get("raw_status", "error")
            self.lbl_ds_balance.config(text=err, fg=FG_HOT)
            self.lbl_ds_status.config(text="ERR", fg=FG_HOT)

        self._last_snapshot = snapshot
        self._update_rings(snapshot)

    def _display_reset_credits(self, credits):
        """卡片数量沿用正文大小，到期明细使用较小字号。"""
        title, *details = format_reset_credit_details(credits).split("\n")
        self.lbl_reset_credits.config(text=title, fg=FG_COLOR)
        self.lbl_reset_expiry.config(text="\n".join(details))
        if details:
            self.lbl_reset_expiry.pack(anchor="w", after=self.lbl_reset_credits)
        else:
            self.lbl_reset_expiry.pack_forget()

    def _draw_bar(self, canvas: tk.Canvas, percent: int, status: str):
        """在 Canvas 上绘制进度条。"""
        canvas.delete("all")
        w = canvas.winfo_width() or 120
        h = canvas.winfo_height() or 14

        fill_w = int((w - 2) * max(0, min(100, percent)) / 100)
        color = bar_color(status)

        # 背景
        canvas.create_rectangle(0, 0, w, h, fill=BAR_BG, outline="")
        # 填充
        if fill_w > 0:
            canvas.create_rectangle(1, 1, 1 + fill_w, h - 1, fill=color, outline="")

    # ── 定时器 ──────────────────────────────────────────────────────────────────

    def _schedule_refresh(self):
        """安排下一次刷新（带异常保护，防止定时器断链）。"""
        try:
            self.refresh()
        except Exception:
            pass  # refresh 内部已处理，此处仅保险
        self.root.after(REFRESH_INTERVAL * 1000, self._schedule_refresh)

    def _schedule_rlcd_push(self) -> None:
        """按配置周期定时向无线投屏后台推送画面；上一帧推流未完成时跳过防堆积。"""
        try:
            with self._rlcd_seq_lock:
                enabled = bool(self._rlcd_config.enabled)
                interval = float(self._rlcd_config.interval)
            if interval <= 0:
                self._rlcd_timer_id = None
                return
            if enabled and self._last_snapshot and not self._rlcd_push_lock.locked():
                self._push_rlcd_async(self._last_snapshot)
            delay_ms = max(200, int(round(interval * 1000)))
            self._rlcd_timer_id = self.root.after(delay_ms, self._schedule_rlcd_push)
        except tk.TclError:
            self._rlcd_timer_id = None
        except Exception:
            try:
                self._rlcd_timer_id = self.root.after(1000, self._schedule_rlcd_push)
            except Exception:
                self._rlcd_timer_id = None

    # ── 退出 ────────────────────────────────────────────────────────────────────

    def quit(self):
        if getattr(self, "_rlcd_timer_id", None) is not None:
            try:
                self.root.after_cancel(self._rlcd_timer_id)
            except Exception:
                pass
            self._rlcd_timer_id = None
        self.tray.stop()
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = Quote0Window()
    app.run()
