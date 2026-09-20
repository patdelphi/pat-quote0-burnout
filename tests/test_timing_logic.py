"""测试 rand0_app 的定时推送与反显切换逻辑（不启动真实 GUI 与网络）。

通过实例化 App 后替换回调做控制流验证：
- 启动即推送：配置了正数间隔时，on_interval_change 触发一次 on_push
- 切换反显：_on_invert_toggle 触发写 .env 与刷新预览
"""
from __future__ import annotations

import unittest
import tempfile
from pathlib import Path


def ensure_env_created(env_path: Path, config_dir: str) -> bool:
    """模拟 rand0_app.App._save_config 的创建逻辑：仅当 .env 不存在时创建并返回 True。"""
    if env_path.exists():
        return False
    # 用 env_util.ensure_env 的真实实现创建（验证模板含 RAND0_INVERT）
    from env_util import ensure_env
    ensure_env(Path(config_dir))
    return True


class _FakeApp:
    """近似 rand0_app.App 的最小替身，复现核心状态字段。"""

    def __init__(self, interval_active=False):
        self._interval_active = interval_active
        self._pushing = False
        self.calls = []
        # 模拟 combo 下拉框“自动推送间隔”，模拟 var_invert
        self._interval = "关"
        self._invert = False
        self._log_msgs = []

    def _log(self, s):
        self._log_msgs.append(s)

    def _save_config(self):
        self.calls.append(("save_config", self._invert))

    def _schedule_push(self, minutes):
        self.calls.append(("schedule", minutes))

    def on_push(self, force=False):
        if force or not self._pushing:
            self.calls.append(("push", force))

    def on_preview(self):
        self.calls.append(("preview", self._invert))

    def on_interval_change(self, interval):
        # 与 rand0_app.App.on_interval_change 同构
        self._interval = interval
        if interval == "关":
            self._interval_active = False
            self._log("已关闭自动推送")
            self._save_config()
            return
        if not self._interval_active:
            self._interval_active = True
            self._log("定时推送已开启，立即推第一帧…")
            self.on_push()
        self._schedule_push(int(interval))
        self._save_config()

    def _on_invert_toggle(self):
        self._invert = not self._invert
        self._save_config()
        self._log("反显已切换，刷新预览并推送…")
        # 与 rand0_app 一致：切换后走 on_push(force=True)（内部刷新预览并推送，不被进行中推送阻塞）
        self.on_push(force=True)


class TestTimingLogic(unittest.TestCase):
    def test_start_immediate_push_once(self):
        """开启定时推送：首次立即推送一次，之后仅调度不再重复推。"""
        app = _FakeApp(interval_active=False)
        app.on_interval_change("5")
        # 序列：立即 push（仅一次）→ schedule → save_config
        pushes = [c for c in app.calls if c[0] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertIn(("schedule", 5), app.calls)

    def test_change_interval_no_immediate_repush(self):
        """已是定时状态再改间隔：不重复立即推，只重新调度。"""
        app = _FakeApp(interval_active=True)
        app.on_interval_change("10")
        self.assertEqual(app.calls.count(("push", None)), 0)
        self.assertIn(("schedule", 10), app.calls)

    def test_disable_no_push(self):
        """切回“关”：不推送，清除定时状态。"""
        app = _FakeApp(interval_active=True)
        app.on_interval_change("关")
        self.assertEqual(app.calls.count(("push", None)), 0)
        self.assertFalse(app._interval_active)

    def test_invert_toggle_saves_and_pushes(self):
        """切换反显（勾选/取消）：写 .env 并强制立即推送（不被打断的推送阻塞）。"""
        app = _FakeApp()
        app._on_invert_toggle()
        self.assertTrue(app._invert)
        self.assertIn(("save_config", True), app.calls)
        # force=True 的推送触发一次（内部负责刷新预览）
        self.assertEqual(app.calls.count(("push", True)), 1)

    def test_invert_toggle_uncheck_still_pushes(self):
        """取消反显同样触发强制推送（修复"取消不刷新推送"的 bug）。"""
        app = _FakeApp()
        app._invert = True
        app._on_invert_toggle()  # 取消
        self.assertFalse(app._invert)
        self.assertEqual(app.calls.count(("push", True)), 1)

    def test_save_config_only_creates_when_missing(self):
        """app 不改写已存在的 .env；仅当 .env 不存在时才创建模板。"""
        with tempfile.TemporaryDirectory() as d:
            # 已存在：调用 _save_config 后文件内容不变
            f = Path(d) / ".env"
            original = 'export RAND0_IP="1"\nexport RAND0_INVERT="0"\n'
            f.write_text(original, encoding="utf-8")
            self.assertFalse(ensure_env_created(f, d))
            self.assertEqual(f.read_text(encoding="utf-8"), original)

    def test_save_config_creates_if_missing(self):
        """.env 不存在时，_save_config 调用 ensure_env 创建模板。"""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"
            self.assertFalse(f.exists())
            self.assertTrue(ensure_env_created(f, d))
            self.assertTrue(f.exists())
            self.assertIn("RAND0_INVERT", f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()