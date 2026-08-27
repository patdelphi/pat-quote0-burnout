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


if __name__ == "__main__":
    unittest.main()
