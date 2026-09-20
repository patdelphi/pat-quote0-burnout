"""系统托盘工具：把 tkinter 窗口缩小到托盘图标区，任务栏不显示。

供多个 tkinter 应用复用（local_app.py / rand0_app.py）。
行为：
- 点窗口最小化按钮 → 隐藏到托盘（任务栏无显示），并弹出提示
- 双击托盘图标 / 托盘菜单"显示" → 恢复窗口
- 托盘菜单"退出" → 真正退出
- 任何托盘异常会自动回退：继续按普通最小化（任务栏显示）
"""

from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageDraw

# ---- pystray 为可选依赖：缺失或初始化失败时降级为普通最小化 ----
try:
    import pystray
    _HAS_TRAY = True
except Exception:
    _HAS_TRAY = False


class TrayManager:
    """把 tkinter 主窗口接入系统托盘。"""

    def __init__(self, root: tk.Tk, title: str = "AI 用量", icon: Image.Image | None = None):
        self.root = root
        self.title = title
        self.icon = None
        self._watch_id = None

        if not _HAS_TRAY:
            return
        try:
            image = icon or self._default_icon()
            menu = pystray.Menu(
                pystray.MenuItem("显示", lambda *_a: self.restore(), default=True),
                pystray.MenuItem("退出", lambda *_a: self.quit()),
            )
            self.icon = pystray.Icon("pat_quote_tray", image, title, menu)
            self.icon.run_detached()
            # 轮询窗口状态：检测到最小化(iconic)即转入托盘
            self._watch_id = self.root.after(200, self._watch)
        except Exception:
            self.icon = None  # 托盘不可用，回退普通最小化

    def _default_icon(self) -> Image.Image:
        """生成默认托盘图标（蓝色圆角方块 + 圆点 + 横条）。"""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(0, 120, 215, 255))
        d.ellipse((20, 12, 44, 36), fill=(255, 255, 255, 255))
        d.rectangle((16, 46, 48, 52), fill=(255, 255, 255, 255))
        return img

    def _watch(self):
        """周期检查：窗口处于最小化状态时转入托盘。"""
        if not self.icon:
            return
        try:
            if self.root.state() == "iconic":
                self.to_tray()
            self._watch_id = self.root.after(200, self._watch)
        except Exception:
            pass

    def to_tray(self):
        """隐藏到托盘（任务栏无显示）并提示。"""
        if not self.icon:
            return
        try:
            self.root.withdraw()
            self.icon.notify("已最小化到托盘，双击托盘图标恢复", self.title)
        except Exception:
            pass

    def restore(self):
        """从托盘恢复窗口。"""
        try:
            def _resume():
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            self.root.after(0, _resume)
        except Exception:
            pass

    def quit(self):
        """从托盘退出整个应用。"""
        try:
            self.icon.stop()
        except Exception:
            pass
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass

    def stop(self):
        """应用正常关闭时清理托盘。"""
        try:
            if self._watch_id:
                self.root.after_cancel(self._watch_id)
        except Exception:
            pass
        try:
            self.icon.stop()
        except Exception:
            pass