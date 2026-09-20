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
# 若无 .env，先自动创建 .env 与 .env.sample 模板
from env_util import ensure_env
ensure_env(CONFIG_DIR)
_load_env()

import rand0_display
from display import build_snapshot
from tray_util import TrayManager

# 从 .env 读取配置（窗日用，缺失时用默认值）
_saved_ip = os.environ.get("RAND0_IP", "").strip()
_default_mode = os.environ.get("RAND0_MODE", "bw").strip() or "bw"
_default_interval = os.environ.get("RAND0_INTERVAL", "关").strip()
_default_timeout = float(os.environ.get("RAND0_TIMEOUT", "5"))
_default_invert = os.environ.get("RAND0_INVERT", "0").strip() not in ("", "0", "false", "no", "关")

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
        self._interval_active = False
        # 应用 .env 中的默认模式与自动推送间隔
        self.var_mode.set(_default_mode)
        # 推送间隔：空/0/"关" → 关闭定期推送；正整数 → 每 N 分钟推送一次
        try:
            _iv = int(_default_interval)
        except (TypeError, ValueError):
            _iv = 0
        if _iv > 0:
            self.combo_interval.set(str(_iv))
            # 启动时立即拉取并推送一次（同时刷新预览），之后再按周期推送
            self._interval_active = False
            self.on_interval_change()
        else:
            # 未开启定时推送：启动也自动拉取并刷新一次预览
            self._log("启动自动拉取预览…")
            self.on_preview()
        # 其余情况 combo 保持默认（下拉框"关"），即关闭定时推送

        # 最小化到系统托盘（任务栏不显示）
        self.tray = TrayManager(self.root, "Rand/0 Display Mode")

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

        # 反显开关：点击切换黑底白字，立即写 .env 并刷新预览
        self.var_invert = tk.BooleanVar(value=_default_invert)
        tk.Checkbutton(top, text="反显", variable=self.var_invert,
                       command=self._on_invert_toggle,
                       bg=BG, fg=FG, selectcolor=BG,
                       activebackground=BG, activeforeground=ACCENT).grid(
            row=0, column=4, padx=(8, 0), sticky="w")

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
        """app 不主动改写 .env；仅当 .env 不存在时创建一份模板供用户手动编辑。

        窗口内修改的 IP/模式/反显/间隔等仅对本次会话生效。
        """
        if not ENV_PATH.exists():
            ensure_env(CONFIG_DIR)

    def _new_snapshot(self):
        """后台线程内拉取真实数据。"""
        return build_snapshot()

    def _preview_image(self, snap, mode, invert: bool = False) -> Image.Image:
        """按模式获取 200×200 Image（用于窗口展示）。invert=True 时反显。"""
        if mode == "bw":
            return rand0_display._render_bw_image(snap, invert)
        return rand0_display._render_gray4_image(snap, invert)

    def _show_image(self, img: Image.Image):
        """把 200×200 图放大显示到预览区。"""
        resized = img.resize((PREVIEW_SIZE, PREVIEW_SIZE),
                             Image.Resampling.NEAREST)
        self._prev_photo = ImageTk.PhotoImage(resized)
        self.preview_label.configure(image=self._prev_photo, text="")

    # ── 按钮动作 ────────────────────────────────────────────────────────────

    def _on_invert_toggle(self):
        """切换反显：写入 .env，拉取并刷新预览后立即推送。"""
        self._save_config()
        # on_push(force=True) 内部会先刷新预览（用最新数据）再推送，且不被进行中的推送阻塞
        self._log("反显已切换，刷新预览并推送…")
        self.on_push(force=True)

    def on_preview(self):
        """后台拉数据、渲染、显示预览。"""
        self._log("拉取数据并渲染预览…")
        def work():
            try:
                snap = self._new_snapshot()
                self._refresh_preview(snap)
                self.root.after(0, lambda: self._log("预览已生成"))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"预览失败：{e}"))
        threading.Thread(target=work, daemon=True).start()

    def _refresh_preview(self, snap):
        """用已拉取的数据（后台线程）在主线程刷新预览图。"""
        try:
            img = self._preview_image(snap, self.var_mode.get(),
                                      invert=self.var_invert.get())
            self.root.after(0, lambda: self._show_image(img))
        except Exception as e:
            self.root.after(0, lambda: self._log(f"预览渲染失败：{e}"))

    def on_push(self, force=False):
        # 普通调用在推送进行中时跳过；force=True（如切换反显）不阻塞，立即重拉+刷新预览+推送
        if self._pushing and not force:
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
                # 只要拉取了数据就刷新一次预览（推送前先看到最新画面）
                self._refresh_preview(snap)
                mode = self.var_mode.get()
                payload = rand0_display.render_frame(snap, mode, invert=self.var_invert.get())
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
            self._interval_active = False
            self._log("已关闭自动推送")
            self._save_config()
            return
        self._schedule_push(int(interval))
        self._save_config()
        # 每次开启定时推送时立即拉数据并推送一帧（含从启动触发），之后按周期推
        if not self._interval_active:
            self._interval_active = True
            self._log("定时推送已开启，立即推第一帧…")
            self.on_push()

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
        self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()


if __name__ == "__main__":
    Rand0App().run()