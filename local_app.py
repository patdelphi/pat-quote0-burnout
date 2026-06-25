#!/usr/bin/env python3
"""
quote0-burnout 本地弹窗 — Windows 桌面置顶显示 AI 额度数据。

功能：
  - 从 Codex（OpenAI）和 DeepSeek 获取实时用量/余额
  - tkinter 无边框置顶窗口，深色主题，像素风格
  - 每 5 分钟自动刷新，双击手动刷新
  - 支持拖动、系统托盘最小化

用法：
  python local_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 必须先加载 .env，再导入 display（display 在模块级别读取环境变量）
env_path = Path(__file__).parent / ".env"
example_path = Path(__file__).parent / "config.example.env"

# 如果 .env 不存在，自动创建
if not env_path.exists():
    if example_path.exists():
        # 从 config.example.env 复制
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        # 创建默认 .env
        env_path.write_text(
            '# DeepSeek API Key（必填）\n'
            'export DEEPSEEK_API_KEY=""\n\n'
            '# Codex 认证\n'
            '# export CODEX_ACCESS_TOKEN=""\n'
            '# export CODEX_ACCOUNT_ID=""\n\n'
            '# 本地弹窗配置\n'
            'export REFRESH_INTERVAL=300\n'
            'export WINDOW_OPACITY=0.92\n\n'
            '# 字体配置\n'
            'export FONT_FAMILY="Arial"\n'
            'export FONT_SIZE=10\n'
            'export FONT_SIZE_LARGE_OFFSET=0\n',
            encoding="utf-8"
        )

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
import threading
import tkinter as tk
from tkinter import font as tkfont

from display import build_snapshot

# ── 配置 ──────────────────────────────────────────────────────────────────────

REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "300"))  # 秒，默认 5 分钟
WINDOW_OPACITY   = float(os.environ.get("WINDOW_OPACITY", "0.92"))  # 不透明度
WINDOW_WIDTH     = 420
WINDOW_HEIGHT    = 260

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
ASSETS_DIR = Path(__file__).parent / "assets" / "fonts"
PIXEL_FONT_PATH = ASSETS_DIR / "PixelOperator.ttf"
VCR_FONT_PATH   = ASSETS_DIR / "VCR_OSD_MONO_1.001.ttf"

# ── 状态颜色映射 ──────────────────────────────────────────────────────────────

def status_color(status: str) -> str:
    """根据状态返回对应颜色。"""
    return {"ok": FG_OK, "warn": FG_WARN, "hot": FG_HOT}.get(status, FG_DIM)


def bar_color(status: str) -> str:
    """根据状态返回进度条填充色。"""
    return {"ok": BAR_FILL_OK, "warn": BAR_FILL_WARN, "hot": BAR_FILL_HOT}.get(status, FG_DIM)


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

        # Windows 无边框窗口设置透明度（SetLayeredWindowAttributes）
        self._set_window_opacity(WINDOW_OPACITY)

        # 拖动相关
        self._drag_x = 0
        self._drag_y = 0
        self.root.bind("<Button-1>", self._on_press)
        self.root.bind("<B1-Motion>", self._on_drag)
        self.root.bind("<Double-Button-1>", self._on_double_click)

        # 右键菜单
        self._menu = tk.Menu(self.root, tearoff=0, bg=BG_COLOR, fg=FG_COLOR,
                             activebackground=DIVIDER, activeforeground=FG_COLOR)
        self._menu.add_command(label="刷新", command=self.refresh)
        self._menu.add_command(label="退出", command=self.quit)
        self.root.bind("<Button-3>", self._show_menu)

        # 字体（统一大小）
        self._setup_fonts()

        # 构建 UI
        self._build_ui()

        # 首次加载数据
        self.refresh()

        # 定时刷新
        self._schedule_refresh()

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
        self.font_label = (family, s, "bold")
        self.font_data   = (family, s)
        self.font_small  = (family, s)
        self.font_large  = (family, large, "bold")

    def _build_ui(self):
        """构建窗口界面。"""
        pad = 14

        # 标题栏：时间 + 状态灯
        self.header = tk.Frame(self.root, bg=BG_COLOR)
        self.header.pack(fill="x", padx=pad, pady=(pad, 2))

        self.lbl_time = tk.Label(self.header, text="--:--", font=self.font_small,
                                  bg=BG_COLOR, fg=FG_DIM)
        self.lbl_time.pack(side="left")

        self.lbl_status = tk.Label(self.header, text="● C  ● D", font=self.font_small,
                                    bg=BG_COLOR, fg=FG_DIM)
        self.lbl_status.pack(side="right")

        # 分隔线
        tk.Frame(self.root, height=1, bg=DIVIDER).pack(fill="x", padx=pad, pady=2)

        # ── CODEX 区域 ──────────────────────────────────────────────────────
        self.codex_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.codex_frame.pack(fill="x", padx=pad, pady=(2, 0))

        self.lbl_codex_title = tk.Label(self.codex_frame, text="◆ CODEX", font=self.font_label,
                                         bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_codex_title.pack(anchor="w")

        # 短窗口行：标签 + 进度条 + 数据（一行）
        self.row1_frame = tk.Frame(self.codex_frame, bg=BG_COLOR)
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
        self.row2_frame = tk.Frame(self.codex_frame, bg=BG_COLOR)
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

        # 分隔线
        tk.Frame(self.root, height=1, bg=DIVIDER).pack(fill="x", padx=pad, pady=3)

        # ── DEEPSEEK 区域 ────────────────────────────────────────────────────
        self.ds_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.ds_frame.pack(fill="x", padx=pad, pady=(2, 8))

        self.ds_row = tk.Frame(self.ds_frame, bg=BG_COLOR)
        self.ds_row.pack(fill="x")

        self.lbl_ds_title = tk.Label(self.ds_row, text="◆ DEEPSEEK", font=self.font_label,
                                      bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_ds_title.pack(side="left")

        self.lbl_ds_balance = tk.Label(self.ds_row, text="$--.--", font=self.font_label,
                                        bg=BG_COLOR, fg=FG_COLOR)
        self.lbl_ds_balance.pack(side="right")

        # 状态标签（仅 warn/hot 时显示，ok 时隐藏，放在余额下方）
        self.lbl_ds_status = tk.Label(self.ds_frame, text="", font=self.font_data,
                                       bg=BG_COLOR, fg=FG_DIM)
        self.lbl_ds_status.pack(anchor="e")

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
                "codex": {"ok": False, "raw_status": str(e)},
                "deepseek": {"ok": False, "raw_status": str(e)},
                "updated_at": "ERR",
            }
        self.root.after(0, lambda: self._update_ui(snapshot))

    def _update_ui(self, snapshot: dict):
        """根据 snapshot 更新所有 UI 元素。"""
        ts = snapshot.get("updated_at", "--:--")
        self.lbl_time.config(text=ts)

        cx = snapshot.get("codex", {})
        ds = snapshot.get("deepseek", {})

        # 状态灯
        cx_st = cx.get("status", "unknown") if cx.get("ok") else "error"
        ds_st = ds.get("status", "unknown") if ds.get("ok") else "error"
        cx_dot = {"ok": "●", "warn": "◐", "hot": "●", "unknown": "○", "error": "✕"}.get(cx_st, "○")
        ds_dot = {"ok": "●", "warn": "◐", "hot": "●", "unknown": "○", "error": "✕"}.get(ds_st, "○")
        cx_color = status_color(cx_st)
        ds_color = status_color(ds_st)
        status_text = f"{cx_dot} C  {ds_dot} D"
        self.lbl_status.config(text=status_text, fg=cx_color if cx_st != "ok" else ds_color)

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
        else:
            err = cx.get("raw_status", "error")
            self.lbl_r1_label.config(text="Codex")
            self.lbl_r1_info.config(text=err, fg=FG_HOT)
            self._draw_bar(self.can_r1, 0, "error")
            self.lbl_r2_label.config(text="")
            self.lbl_r2_info.config(text="", fg=FG_DIM)
            self._draw_bar(self.can_r2, 0, "error")

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
        """安排下一次刷新。"""
        self.refresh()
        self.root.after(REFRESH_INTERVAL * 1000, self._schedule_refresh)

    # ── 退出 ────────────────────────────────────────────────────────────────────

    def quit(self):
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = Quote0Window()
    app.run()
