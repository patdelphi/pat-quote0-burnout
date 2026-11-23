"""
quote0-burnout 本地弹窗折叠功能测试。

覆盖 Antigravity、Codex、DeepSeek 三个模块的独立折叠/展开切换、
标题前缀更新（▼ / ▶）与窗口高度自适应逻辑；不依赖真实图形界面与 PIL。
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

try:
    import local_app
except ModuleNotFoundError:
    # 无 PIL 环境时提供轻量 tray_util 桩模块，仅用于测试折叠逻辑
    stub_tray = types.ModuleType("tray_util")
    stub_tray.TrayManager = MagicMock()
    sys.modules["tray_util"] = stub_tray
    import local_app


class LocalAppFoldTests(unittest.TestCase):
    """验证 Quote0Window.toggle_section 对各模块的折叠与展开行为。"""

    def _make_dummy_window(self):
        win = local_app.Quote0Window.__new__(local_app.Quote0Window)
        win.root = MagicMock()
        win.root.winfo_width.return_value = 504
        win.root.winfo_reqwidth.return_value = 400
        win.root.winfo_reqheight.side_effect = [260, 390]
        win._collapsed = {"antigravity": False, "codex": False, "deepseek": False}
        win._sections = {}
        for key, title in (
            ("antigravity", "ANTIGRAVITY"),
            ("codex", "CODEX"),
            ("deepseek", "DEEPSEEK"),
        ):
            win._sections[key] = {
                "title": title,
                "label": MagicMock(),
                "body": MagicMock(),
            }
        return win

    def test_toggle_each_section_independently(self):
        win = self._make_dummy_window()

        res = win.toggle_section("antigravity")
        self.assertEqual(res, "break")
        self.assertTrue(win._collapsed["antigravity"])
        self.assertFalse(win._collapsed["codex"])
        self.assertFalse(win._collapsed["deepseek"])
        win._sections["antigravity"]["label"].config.assert_called_with(text="▶ ANTIGRAVITY")
        win._sections["antigravity"]["body"].pack_forget.assert_called_once()
        win.root.geometry.assert_called_with("504x260")

        # 再次点击展开
        win.toggle_section("antigravity")
        self.assertFalse(win._collapsed["antigravity"])
        win._sections["antigravity"]["label"].config.assert_called_with(text="▼ ANTIGRAVITY")
        win._sections["antigravity"]["body"].pack.assert_called_with(fill="x")
        win.root.geometry.assert_called_with("504x390")

    def test_toggle_codex_and_deepseek(self):
        win = self._make_dummy_window()
        win.root.winfo_reqheight.side_effect = [310, 270]

        win.toggle_section("codex")
        self.assertTrue(win._collapsed["codex"])
        win._sections["codex"]["label"].config.assert_called_with(text="▶ CODEX")
        win._sections["codex"]["body"].pack_forget.assert_called_once()

        win.toggle_section("deepseek")
        self.assertTrue(win._collapsed["deepseek"])
        win._sections["deepseek"]["label"].config.assert_called_with(text="▶ DEEPSEEK")
        win._sections["deepseek"]["body"].pack_forget.assert_called_once()


if __name__ == "__main__":
    unittest.main()
