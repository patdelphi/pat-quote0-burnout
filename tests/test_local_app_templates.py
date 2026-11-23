"""验证本地窗口圆环模板切换、数据展示和异常状态。"""

import unittest
from unittest.mock import patch

import local_app


class LocalAppTemplateTests(unittest.TestCase):
    """使用真实 Tk 控件和模拟数据，不访问外部服务。"""

    def setUp(self):
        with patch.object(local_app, "TrayManager"), \
             patch.object(local_app.Quote0Window, "_set_window_opacity"), \
             patch.object(local_app.Quote0Window, "refresh"), \
             patch.object(local_app.Quote0Window, "_schedule_refresh"):
            self.win = local_app.Quote0Window()
        self.root = self.win.root
        self.root.update()
        self.root.focus_force()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_switch_keys_and_header_arrows_keep_position_and_data(self):
        self.win._update_ui_safe({
            "updated_at": "12:34",
            "antigravity": {"ok": True, "rows": [
                {"label": "Gem 5h", "remaining_percent": 75, "reset": "14:23", "status": "ok"},
                {"label": "Gem Wk", "remaining_percent": None, "reset": "?", "status": "unknown"},
            ]},
            "codex": {"ok": True, "short_used_percent": 12, "long_used_percent": 42,
                      "short_reset": "15:00", "long_reset": "周日", "status": "ok"},
            "deepseek": {"ok": True, "balance": 12.34, "symbol": "¥", "status": "ok"},
        })
        self.root.update()
        position = (self.root.winfo_x(), self.root.winfo_y())
        with patch.object(self.win, "refresh") as refresh:
            self.root.event_generate("<KeyPress-2>")
            self.root.update()
            self.assertEqual(self.win._template, "ring")
            self.assertTrue(self.win.ag_rings.winfo_ismapped())
            self.assertFalse(self.win.ag_bars.winfo_ismapped())
            self.assertEqual(self.win.ag_ring_items[0]["canvas"].itemcget("percent", "text"), "75%")
            self.assertAlmostEqual(float(self.win.ag_ring_items[0]["canvas"].itemcget("arc", "extent")), -270)
            self.assertEqual(self.win.ag_ring_items[0]["reset"].cget("text"), "14:23")
            self.assertEqual(self.win.ag_ring_items[1]["canvas"].itemcget("percent", "text"), "--%")
            self.assertEqual(self.win.codex_ring_items[0]["canvas"].itemcget("percent", "text"), "88%")
            self.assertFalse(self.win.lbl_ag_ring_error.winfo_ismapped())
            self.assertEqual(self.win.lbl_ds_balance.cget("text"), "¥12.34")
            self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), position)
            self.win.lbl_prev_template.event_generate("<Button-1>", x=3, y=3)
            self.root.update()
            self.assertEqual(self.win._template, "bar")
            self.assertTrue(self.win.ag_bars.winfo_ismapped())
            self.win.lbl_next_template.event_generate("<Button-1>", x=3, y=3)
            self.root.update()
            self.assertEqual(self.win._template, "ring")
            self.root.event_generate("<KeyPress-1>")
            self.root.update()
            self.assertEqual(self.win._template, "bar")
            refresh.assert_not_called()

    def test_ring_error_and_missing_percent_are_not_reported_as_zero(self):
        self.win._set_template("ring")
        self.win._update_ui_safe({
            "antigravity": {"ok": False, "raw_status": "连接失败"},
            "codex": {"ok": True, "short_used_percent": None, "long_used_percent": 100},
            "deepseek": {"ok": False, "raw_status": "余额不可用"},
        })
        self.root.update()
        self.assertEqual(self.win.ag_ring_items[0]["canvas"].itemcget("percent", "text"), "--%")
        self.assertIn("连接失败", self.win.lbl_ag_ring_error.cget("text"))
        self.assertEqual(self.win.codex_ring_items[0]["canvas"].itemcget("percent", "text"), "--%")
        self.assertEqual(self.win.codex_ring_items[1]["canvas"].itemcget("percent", "text"), "0%")
        self.assertFalse(self.win.codex_ring_items[1]["canvas"].find_withtag("arc"))
        self.assertEqual(self.win.lbl_ds_balance.cget("text"), "余额不可用")

    def test_ring_template_preserves_folding_fonts_and_window_fit(self):
        self.win._set_template("ring")
        self.win.toggle_section("antigravity")
        self.win._set_template("bar")
        self.win._set_template("ring")
        self.root.update()
        self.assertTrue(self.win._collapsed["antigravity"])
        self.assertFalse(self.win.ag_body.winfo_ismapped())
        self.win.toggle_section("antigravity")
        old_size = self.win.font_data.cget("size")
        self.win._change_font_size(3)
        self.root.update()
        self.assertEqual(self.win.font_data.cget("size"), old_size + 3)
        self.assertGreaterEqual(self.root.winfo_width(), self.root.winfo_reqwidth())
        self.assertGreaterEqual(self.root.winfo_height(), self.root.winfo_reqheight())
        self.assertEqual(self.win.lbl_codex_title.cget("fg"), local_app.FG_COLOR)

    def test_three_reset_cards_show_all_expiries_in_both_templates(self):
        snapshot = {
            "antigravity": {"ok": False},
            "codex": {"ok": True, "short_used_percent": 5, "long_used_percent": 10,
                      "reset_credits": {"available_count": 3, "credits": [
                          {"expires_at": "12/01 04:24"}, {"expires_at": "12/02 05:02"},
                          {"expires_at": "12/13 05:54"},
                      ]}},
            "deepseek": {"ok": False},
        }
        self.win._update_ui_safe(snapshot)
        for template in ("bar", "ring"):
            self.win._set_template(template)
            self.root.update()
            text = self.win.lbl_reset_credits.cget("text") + "\n" + self.win.lbl_reset_expiry.cget("text")
            for expected in ("重置卡 3张", "12/01 04:24", "12/02 05:02", "12/13 05:54"):
                self.assertIn(expected, text)
            self.assertEqual(len(text.splitlines()), 2)
            self.assertEqual(len(self.win.lbl_reset_expiry.cget("text").splitlines()), 1)
            self.assertEqual(text.count("到期"), 1)
            self.assertEqual(self.win.lbl_reset_expiry.cget("font"), str(self.win.font_hint))
            self.assertLess(self.win.font_hint.cget("size"), self.win.font_small.cget("size"))
            self.assertGreaterEqual(self.root.winfo_width(), self.root.winfo_reqwidth())
            self.assertGreaterEqual(self.root.winfo_height(), self.root.winfo_reqheight())

    def test_reset_card_missing_details_are_explicit(self):
        credits = {"available_count": 3, "credits": [{"expires_at": "12/01 04:24"}, {}]}
        text = local_app.format_reset_credit_details(credits)
        self.assertIn("12/01 04:24", text)
        self.assertIn("--", text)
        self.assertIn("另有 1 张无详情", text)
        self.assertEqual(local_app.format_reset_credit_details({"available_count": 0, "credits": []}), "重置卡 0张")
        self.assertEqual(local_app.format_reset_credit_details(None), "重置卡 --")


if __name__ == "__main__":
    unittest.main()
