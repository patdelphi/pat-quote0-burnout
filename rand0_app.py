#!/usr/bin/env python3
"""
rand0_app — Rand/0 Display Mode 本地窗口。

功能：
  - 输入/保存设备 IP（持久化到 .env 的 RAND0_IP）
  - 选择黑白（bw）/ 四级灰（gray4）
  - 预览：获取真实额度数据，渲染 200×200 仪表盘并显示在窗口内
  - 推送：通过本地 WebSocket 把图片推送到设备
  - 可选定时自动推送（间隔可设，默认关闭）
  - 日志区显示设备回传的按钮事件/错误

用法：
  python rand0_app.py
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

# ── 路径与配置 ──────────────────────────────────────────────────────────
# 用户配置（.env）放在可执行文件所在目录；源码运行时为项目目录。
# PyInstaller 打包后 __file__ 指向 _MEIPASS 临时目录，因此用 sys.executable 定位。
CONFIG_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
ENV_PATH = CONFIG_DIR / ".env"


def _load_env() -> None:
    """把 .env 中的 `export KEY="value"` 载入 os.environ（不覆盖已存在的值）。"""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if " #" in line:  # 去掉行内注释
            line = line.split(" #", 1)[0]
        if line.startswith("export "):
            line = line[7:]
        key, val = line.split("=", 1)
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


# 必须先加载 .env，再导入 display / rand0_display（它们在模块级读取环境变量）
_load_env()

import rand0_display
from display import build_snapshot

# 从 .env 读取配置（窗日用，缺失时用默认值）
_saved_ip = os.environ.get("RAND0_IP", "").strip()
_default_mode = os.environ.get("RAND0_MODE", "bw").strip() or "bw"
_default_interval = os.environ.get("RAND0_INTERVAL", "关").strip()
_default_timeout = float(os.environ.get("RAND0_TIMEOUT", "5"))

BG = "#1e1e2e"
FG = "#cdd6f4"
FG_DIM = "#6c7086"
ACCENT = "#89b4fa"
DIVIDER = "#45475a"
BADGE_BG = "#313244"
FONT = "TkDefaultFont"

PREVIEW_SIZE = 300  # 窗口内预览图边长（原图 200×200，放大展示）


class Rand0App:
    """Rand/0 Display Mode 本地窗口。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Rand/0 Display Mode")
        self.root.configure(bg=BG)
        self.root.geometry("520x640")

        self._build_ui()

        # 定时推送状态
        self._timer_id = None
        self._pushing = False
        # 应用 .env 中的默认模式与自动推送间隔
        self.var_mode.set(_default_mode)
        # 推送间隔：空/0/"关" → 关闭定期推送；正整数 → 每 N 分钟推送一次
        try:
            _iv = int(_default_interval)
        except (TypeError, ValueError):
            _iv = 0
        if _iv > 0:
            self.combo_interval.set(str(_iv))
            self._schedule_push(_iv)
        # 其余情况 combo 保持默认（下拉框"关"），即关闭定时推送

    # ── UI 组装 ────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}

        # 顶部：IP 输入 + 模式选择
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 4))

        tk.Label(top, text="设备 IP", bg=BG, fg=FG_DIM).grid(row=0, column=0, sticky="w")
        self.var_ip = tk.StringVar(value=_saved_ip)
        self.entry_ip = ttk.Entry(top, textvariable=self.var_ip, width=18)
        self.entry_ip.grid(row=0, column=1, padx=(8, 8), sticky="w")

        self.var_mode = tk.StringVar(value="bw")
        for val, label in (("bw", "黑白"), ("gray4", "四级灰")):
            tk.Radiobutton(top, text=label, variable=self.var_mode, value=val,
                           bg=BG, fg=FG, selectcolor=BADGE_BG,
                           activebackground=BG, activeforeground=ACCENT).grid(
                row=0, column=2 if val == "bw" else 3, sticky="w")

        for c in range(3):
            top.grid_columnconfigure(c, weight=0)
        top.grid_columnconfigure(4, weight=1)

        # 按钮行
        btns = tk.Frame(self.root, bg=BG)
        btns.pack(fill="x", padx=12, pady=4)
        self.btn_preview = ttk.Button(btns, text="预览", command=self.on_preview)
        self.btn_preview.pack(side="left")
        self.btn_push = ttk.Button(btns, text="推送", command=self.on_push)
        self.btn_push.pack(side="left", padx=(8, 0))

        # 定时推送设置
        tk.Label(btns, text="自动推送每", bg=BG, fg=FG_DIM).pack(side="left", padx=(16, 4))
        self.combo_interval = ttk.Combobox(btns, width=6,
                                           values=["关", "5", "10", "15", "30", "60"],
                                           state="readonly")
        self.combo_interval.set("关")
        self.combo_interval.pack(side="left")
        tk.Label(btns, text="分钟", bg=BG, fg=FG_DIM).pack(side="left", padx=(4, 0))
        self.combo_interval.bind("<<ComboboxSelected>>", self.on_interval_change)

        # 预览区
        self.preview_label = tk.Label(self.root, bg=BG, text="预览（点击“预览”加载）",
                                      fg=FG_DIM)
        self.preview_label.pack(padx=12, pady=(8, 4))
        self._prev_photo = None

        # 日志区
        log_frame = tk.Frame(self.root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        tk.Label(log_frame, text="设备消息 / 日志", bg=BG, fg=FG_DIM).pack(anchor="w")
        self.txt_log = tk.Text(log_frame, height=8, bg="#11111b", fg=FG,
                               insertbackground=FG, wrap="word", relief="flat",
                               state="disabled")
        self.txt_log.pack(fill="both", expand=True, pady=(4, 0))

    # ── 工具函数 ────────────────────────────────────────────────────────────

    def _log(self, text: str):
        """向日志区追加一行。"""
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _get_ip(self) -> str:
        ip = self.var_ip.get().strip()
        if not ip:
            raise ValueError("请填写设备 IP")
        return ip

    def _save_config(self):
        """把窗口里的 IP、模式、自动推送间隔写回 .env，启动时复用。"""
        values = {
            "RAND0_IP": self.var_ip.get().strip(),
            "RAND0_MODE": self.var_mode.get(),
            "RAND0_INTERVAL": self.combo_interval.get(),
            # 推送/连接超时（秒），读取自 .env 或默认 5
            "RAND0_TIMEOUT": str(_default_timeout),
        }
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
        # 保留既有键值，替换窗口管理的这几个键
        keys = set(values)
        filtered = [l for l in lines if not l.startswith(tuple(k + "=" for k in keys))]
        for key, val in values.items():
            filtered.append(f"export {key}=\"{val}\"")
        ENV_PATH.write_text("\n".join(filtered) + "\n", encoding="utf-8")

    def _new_snapshot(self):
        """后台线程内拉取真实数据。"""
        return build_snapshot()

    def _preview_image(self, snap, mode) -> Image.Image:
        """按模式获取 200×200 Image（用于窗口展示）。"""
        if mode == "bw":
            return rand0_display._render_bw_image(snap)
        return rand0_display._render_gray4_image(snap)

    def _show_image(self, img: Image.Image):
        """把 200×200 图放大显示到预览区。"""
        resized = img.resize((PREVIEW_SIZE, PREVIEW_SIZE),
                             Image.Resampling.NEAREST)
        self._prev_photo = ImageTk.PhotoImage(resized)
        self.preview_label.configure(image=self._prev_photo, text="")

    # ── 按钮动作 ────────────────────────────────────────────────────────────

    def on_preview(self):
        """后台拉数据、渲染、显示预览。"""
        self._log("拉取数据并渲染预览…")
        def work():
            try:
                snap = self._new_snapshot()
                img = self._preview_image(snap, self.var_mode.get())
                self.root.after(0, lambda: self._show_image(img))
                self.root.after(0, lambda: self._log("预览已生成"))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"预览失败：{e}"))
        threading.Thread(target=work, daemon=True).start()

    def on_push(self):
        if self._pushing:
            return
        try:
            ip = self._get_ip()
        except ValueError as e:
            messagebox.showwarning("提示", str(e))
            return
        self._save_config()
        self._pushing = True
        self.btn_push.configure(state="disabled")
        self._log(f"推送 {self.var_mode.get()} 到 {ip} …")

        def work():
            try:
                snap = self._new_snapshot()
                mode = self.var_mode.get()
                payload = rand0_display.render_frame(snap, mode)
                received = rand0_display.push_frame(
                    ip, mode, payload, timeout=_default_timeout,
                    on_message=lambda m: self.root.after(0, self._log, m))
                self.root.after(0, lambda: self._log(f"推送完成（设备消息 {received} 条）"))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"推送失败：{e}"))
            finally:
                self._pushing = False
                self.root.after(0, lambda: self.btn_push.configure(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    # ── 定时推送 ────────────────────────────────────────────────────────────

    def on_interval_change(self, _event=None):
        interval = self.combo_interval.get()
        if interval == "关":
            self._cancel_timer()
            self._log("已关闭自动推送")
        else:
            self._schedule_push(int(interval))
        # 回写间隔到 .env，便于下次启动复用
        self._save_config()

    def _schedule_push(self, minutes: int):
        self._cancel_timer()
        self._log(f"已开启自动推送：每 {minutes} 分钟")
        self._timer_id = self.root.after(minutes * 60000, self._auto_push)

    def _auto_push(self):
        if not self._pushing:
            self.on_push()
        # 无论是否成功，重新安排下一轮（仅在仍处于定时模式下）
        if self.combo_interval.get() != "关":
            self._timer_id = self.root.after(
                int(self.combo_interval.get()) * 60000, self._auto_push)

    def _cancel_timer(self):
        if self._timer_id:
            try:
                self.root.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

    def on_close(self):
        self._cancel_timer()
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()


if __name__ == "__main__":
    Rand0App().run()