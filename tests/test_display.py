"""
quote0-burnout 额度解析测试。

覆盖 Codex app-server 新结构、旧 HTTP 结构，以及 app-server 优先策略；
测试不访问真实网络，也不读取本机 Codex 认证信息。
"""

import unittest
from unittest.mock import patch

import display


class CodexSnapshotTests(unittest.TestCase):
    """验证新旧 Codex 响应都能转换为统一快照。"""

    def test_parses_app_server_rate_limits(self):
        result = display.build_codex_snapshot(
            {
                "ok": True,
                "raw": {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 18,
                            "windowDurationMins": 300,
                            "resetsAt": 0,
                        },
                        "secondary": {
                            "usedPercent": 10,
                            "windowDurationMins": 10080,
                            "resetsAt": 0,
                        },
                    }
                },
            }
        )

        self.assertEqual(result["short_label"], "5h")
        self.assertEqual(result["short_used_percent"], 18)
        self.assertEqual(result["long_label"], "Wk")
        self.assertEqual(result["long_used_percent"], 10)
        self.assertNotEqual(result["short_reset"], "?")

    def test_parses_legacy_http_rate_limits(self):
        result = display.build_codex_snapshot(
            {
                "ok": True,
                "raw": {
                    "rate_limit": {
                        "primary_window": {"used_percent": 72, "reset_at": 0},
                        "secondary_window": {"used_percent": 41, "reset_at": 0},
                    }
                },
            }
        )

        self.assertEqual(result["short_label"], "5h")
        self.assertEqual(result["short_used_percent"], 72)
        self.assertEqual(result["long_label"], "Wk")
        self.assertEqual(result["long_used_percent"], 41)

    def test_handles_missing_secondary_window(self):
        result = display.build_codex_snapshot(
            {
                "ok": True,
                "raw": {
                    "rateLimits": {
                        "primary": {"usedPercent": 0, "windowDurationMins": 300},
                        "secondary": None,
                    }
                },
            }
        )

        self.assertEqual(result["short_used_percent"], 0)
        self.assertIsNone(result["long_used_percent"])
        self.assertEqual(result["long_label"], "Wk")

    def test_parses_reset_credit_details(self):
        result = display.build_codex_snapshot(
            {
                "ok": True,
                "raw": {
                    "rateLimits": {"primary": {}, "secondary": None},
                    "rateLimitResetCredits": {
                        "availableCount": 2,
                        "credits": [
                            {
                                "id": "private-id-is-not-displayed",
                                "status": "available",
                                "title": "Full reset",
                                "grantedAt": 100,
                                "expiresAt": 200,
                            }
                        ],
                    },
                },
            }
        )

        credits = result["reset_credits"]
        self.assertEqual(credits["available_count"], 2)
        self.assertEqual(len(credits["credits"]), 1)
        self.assertEqual(credits["credits"][0]["title"], "Full reset")
        self.assertEqual(credits["credits"][0]["expires_at"], display._time_until(200))
        self.assertNotIn("id", credits["credits"][0])

    def test_formats_reset_credit_summary(self):
        self.assertEqual(
            display.format_reset_credits(
                {"available_count": 1, "credits": [{"expires_at": "09/01 12:00"}]}
            ),
            "重置卡 1张 / 到期 09/01 12:00",
        )
        self.assertEqual(
            display.format_reset_credits({"available_count": 0, "credits": []}),
            "重置卡 0张",
        )

    @patch("display._get_codex_usage_http")
    @patch("display._get_codex_usage_app_server")
    def test_prefers_app_server(self, app_server, http_fallback):
        app_server.return_value = {"rateLimits": {"primary": {}, "secondary": None}}

        result = display.get_codex_usage()

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "app-server")
        http_fallback.assert_not_called()


class AntigravitySnapshotTests(unittest.TestCase):
    """验证 Antigravity CLI 响应解析、异常处理与快照构建。"""

    SAMPLE_RAW = {
        "conversation_id": "",
        "status": "SUCCESS",
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {
                                "id": "gemini-weekly",
                                "window": "weekly",
                                "remaining_fraction": 0.9936991930007935,
                                "reset_time": "2026-11-22T03:46:59Z",
                            },
                            {
                                "id": "gemini-5h",
                                "window": "5h",
                                "remaining_fraction": 0.9774393439292908,
                                "reset_time": "2026-11-15T08:46:59Z",
                            },
                        ],
                    },
                    {
                        "name": "Claude and GPT models",
                        "buckets": [
                            {
                                "id": "3p-weekly",
                                "window": "weekly",
                                "remaining_fraction": 0.9498991370201111,
                                "reset_time": "2026-11-22T07:47:28Z",
                            },
                            {
                                "id": "3p-5h",
                                "window": "5h",
                                "remaining_fraction": 0.65,
                                "reset_time": "2026-11-15T12:47:28Z",
                            },
                        ],
                    },
                ]
            },
        },
    }

    def test_parses_antigravity_usage_rows(self):
        result = display.build_antigravity_snapshot({"ok": True, "raw": self.SAMPLE_RAW})

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["rows"]), 4)
        self.assertEqual(
            [row["label"] for row in result["rows"]],
            ["Gem 5h", "Gem Wk", "Cld 5h", "Cld Wk"],
        )
        self.assertEqual(result["rows"][0]["remaining_percent"], 98)
        self.assertEqual(result["rows"][1]["remaining_percent"], 99)
        self.assertEqual(result["rows"][2]["remaining_percent"], 65)
        self.assertEqual(result["rows"][2]["used_percent"], 35)
        self.assertEqual(result["rows"][3]["remaining_percent"], 95)
        self.assertEqual(result["status"], "ok")
        self.assertNotEqual(result["rows"][0]["reset"], "?")

    def test_antigravity_status_reflects_worst_bucket(self):
        raw = {
            "status": "SUCCESS",
            "command": {
                "data": {
                    "groups": [
                        {
                            "name": "Gemini Models",
                            "buckets": [
                                {"window": "5h", "remaining_fraction": 0.25},
                                {"window": "weekly", "remaining_fraction": 0.90},
                            ],
                        },
                        {
                            "name": "Claude and GPT models",
                            "buckets": [
                                {"window": "5h", "remaining_fraction": 0.05},
                                {"window": "weekly", "remaining_fraction": 0.80},
                            ],
                        },
                    ]
                }
            },
        }
        result = display.build_antigravity_snapshot({"ok": True, "raw": raw})
        self.assertEqual(result["rows"][0]["status"], "warn")
        self.assertEqual(result["rows"][2]["status"], "hot")
        self.assertEqual(result["status"], "hot")

    def test_handles_antigravity_error_snapshot(self):
        result = display.build_antigravity_snapshot({"ok": False, "status": "no cli"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["raw_status"], "no cli")
        self.assertEqual(result["rows"], [])

    @patch("display._find_agy_command", return_value=None)
    def test_get_antigravity_usage_missing_cli(self, _mock_find):
        result = display.get_antigravity_usage()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no cli")

    @patch("display.get_deepseek_balance", return_value={"ok": True, "amount": 12.34, "currency": "USD", "available": True})
    @patch("display.get_codex_usage", return_value={"ok": False, "status": "no auth"})
    @patch("display.get_antigravity_usage")
    def test_build_snapshot_includes_antigravity(self, mock_agy, _mock_codex, _mock_ds):
        mock_agy.return_value = {"ok": True, "raw": self.SAMPLE_RAW}
        snap = display.build_snapshot()
        self.assertIn("antigravity", snap)
        self.assertTrue(snap["antigravity"]["ok"])
        self.assertEqual(len(snap["antigravity"]["rows"]), 4)


if __name__ == "__main__":
    unittest.main()
