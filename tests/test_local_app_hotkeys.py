"""验证本地窗口热键、字体缩放与内容自适应，不访问外部服务。"""

import unittest
from unittest.mock import patch

import local_app


class LocalAppHotkeyTests(unittest.TestCase):
    """使用真实 Tk 控件验证键盘事件和窗口布局。"""

    def setUp(self):
        with patch.object(local_app, "TrayManager"), \
             patch.object(local_app.Quote0Window, "_set_window_opacity"), \
             patch.object(local_app.Quote0Window, "refresh"), \
             patch.object(local_app.Quote0Window, "_schedule_refresh"):
            self.window = local_app.Quote0Window()
        self.root = self.window.root
        self.root.update()
        self.root.focus_force()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def assert_content_fits(self):
        self.root.update_idletasks()
        self.assertGreaterEqual(self.root.winfo_width(), self.root.winfo_reqwidth())
        self.assertGreaterEqual(self.root.winfo_height(), self.root.winfo_reqheight())

    def test_startup_fits_content(self):
        self.assert_content_fits()

    def test_antigravity_labels_fit_at_large_font_sizes(self):
        for size in (10, 20, 40):
            self.window.font_data.configure(size=size)
            self.window._fit_window()
            self.root.update()
            for row in self.window.ag_rows:
                label = row["label"]
                available = label.winfo_width() - 2 * (int(label.cget("padx")) + int(label.cget("bd")))
                self.assertGreaterEqual(available, self.window.font_data.measure(label.cget("text")))
                self.assertLessEqual(int(label.cget("width")), 7)

    def test_shortcut_hint_is_at_bottom_and_scales_with_fonts(self):
        hint = self.window.lbl_shortcuts
        self.assertTrue(hint.winfo_ismapped())
        self.assertEqual(hint.cget("text"), "F5 刷新  +- 字号  /* 透明度")
        self.assertGreater(hint.winfo_rooty(), self.window.ds_frame.winfo_rooty())
        before = self.window.font_hint.cget("size")
        self.window._change_font_size(10)
        self.root.update()
        self.assertGreater(self.window.font_hint.cget("size"), before)
        self.assertLess(self.window.font_hint.cget("size"), self.window.font_data.cget("size"))
        self.assert_content_fits()

    def test_opacity_hotkeys_and_limits(self):
        initial = self.window._opacity
        with patch.object(self.window, "_set_window_opacity") as apply_opacity:
            self.root.event_generate("<KeyPress-slash>")
            self.root.update()
            self.assertAlmostEqual(self.window._opacity, max(0.2, initial - 0.05))
            apply_opacity.assert_called_with(self.window._opacity)
            self.root.event_generate("<KeyPress-asterisk>")
            self.root.update()
            self.assertAlmostEqual(self.window._opacity, min(1.0, max(0.2, initial - 0.05) + 0.05))
            self.window._change_opacity(-10)
            self.assertEqual(self.window._opacity, 0.2)
            self.window._change_opacity(10)
            self.assertEqual(self.window._opacity, 1.0)
        self.assertTrue(self.root.bind("<KP_Divide>"))
        self.assertTrue(self.root.bind("<KP_Multiply>"))

    def test_time_and_reset_credits_match_section_title_after_updates(self):
        title_color = self.window.lbl_codex_title.cget("fg")
        self.assertEqual(self.window.lbl_time.cget("fg"), title_color)
        self.assertEqual(self.window.lbl_reset_credits.cget("fg"), title_color)

        # 模拟先前界面错误，以及 Codex 正常和异常两种刷新结果。
        self.window.lbl_time.config(fg=local_app.FG_HOT)
        for codex in ({"ok": True}, {"ok": False}):
            self.window._update_ui_safe({
                "updated_at": "12:34", "codex": codex,
                "antigravity": {"ok": False}, "deepseek": {"ok": False},
            })
            self.assertEqual(self.window.lbl_time.cget("fg"), title_color)
            self.assertEqual(self.window.lbl_reset_credits.cget("fg"), title_color)

    def test_resizing_keeps_window_position_at_screen_edge(self):
        x = self.root.winfo_screenwidth() - 30
        y = self.root.winfo_screenheight() - 30
        self.root.geometry(f"+{x}+{y}")
        self.root.update()
        original = (self.root.winfo_x(), self.root.winfo_y())

        self.window._change_font_size(1)
        self.root.update()
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), original)
        self.window._update_ui_safe({
            "updated_at": "12:34",
            "antigravity": {"ok": False, "raw_status": "较长状态" * 10},
            "codex": {"ok": False},
            "deepseek": {"ok": False},
        })
        self.root.update()
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), original)

    def test_hotkeys_refresh_and_change_all_fonts(self):
        before = self.window.font_data.cget("size")
        with patch.object(self.window, "refresh") as refresh:
            self.root.event_generate("<KeyPress-F5>")
            self.root.update()
            refresh.assert_called_once()
        self.root.event_generate("<KeyPress-plus>")
        self.root.update()
        self.assertEqual(self.window.font_data.cget("size"), before + 1)
        self.assertEqual(self.window.font_label.cget("size"), before + 1)
        self.assert_content_fits()
        self.root.event_generate("<KeyPress-minus>")
        self.root.update()
        self.assertEqual(self.window.font_data.cget("size"), before)
        self.assert_content_fits()
        self.assertTrue(self.root.bind("<KP_Add>"))
        self.assertTrue(self.root.bind("<KP_Subtract>"))

    def test_refresh_expands_for_longer_content(self):
        self.window._update_ui_safe({
            "updated_at": "12:34",
            "antigravity": {"ok": False, "raw_status": "长状态" * 30},
            "codex": {"ok": False},
            "deepseek": {"ok": False},
        })
        self.assert_content_fits()


if __name__ == "__main__":
    unittest.main()
