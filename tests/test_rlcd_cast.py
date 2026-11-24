"""
程序说明：Quote0Local 接入 ESP32-S3 RLCD 无线投屏自动推送的单元与集成测试套件。

覆盖范围：
1. RLCD_CAST_* 环境变量解析、开关真假值、边界回退及 /push URL 规范化。
2. 400×300 bar / ring 双模板渲染（含 Antigravity、Codex + 重置卡、DeepSeek 余额）、
   反显模式与缺省/报错快照安全渲染。
3. HTTP 推送客户端（成功、请求超时与 HTTP 错误容错，不向外抛未捕获异常）。
4. 与无线投屏后台 cast_server 转换管线的兼容性验证（产出精确 15,000 字节 1-bit 帧）。
5. Quote0Window 主程序集成（开关开启/关闭、模板联动、手动立即推送）。
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import local_app  # noqa: E402
import rlcd_cast  # noqa: E402


def _full_sample_snapshot() -> dict:
    """构造包含 Antigravity、Codex（含 3 张重置卡）和 DeepSeek 的完整测试快照。"""
    return {
        "updated_at": "19:02",
        "antigravity": {
            "ok": True,
            "status": "warn",
            "rows": [
                {"key": "gemini_5h", "label": "Gem 5h", "remaining_percent": 82, "reset": "21:10", "status": "ok"},
                {"key": "gemini_wk", "label": "Gem Wk", "remaining_percent": 65, "reset": "11/28 08:00", "status": "ok"},
                {"key": "claude_5h", "label": "Cld 5h", "remaining_percent": 25, "reset": "20:45", "status": "warn"},
                {"key": "claude_wk", "label": "Cld Wk", "remaining_percent": 40, "reset": "11/29 12:00", "status": "ok"},
            ],
        },
        "codex": {
            "ok": True,
            "short_label": "5h",
            "short_used_percent": 18,
            "short_reset": "22:30",
            "long_label": "Wk",
            "long_used_percent": 46,
            "long_reset": "11/27 00:00",
            "reset_credits": {
                "available_count": 3,
                "credits": [
                    {"expires_at": "12/01 04:24"},
                    {"expires_at": "12/02 05:02"},
                    {"expires_at": "12/13 05:54"},
                ],
            },
            "status": "ok",
        },
        "deepseek": {
            "ok": True,
            "balance": 18.42,
            "currency": "USD",
            "symbol": "$",
            "status": "ok",
        },
    }


class TestRlcdCastConfig(unittest.TestCase):
    """验证 .env 参数解析、范围兜底与 URL 规范化。"""

    def test_defaults_and_bool_parsing(self):
        cfg = rlcd_cast.load_rlcd_cast_config({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.url, "http://127.0.0.1:8787/push")
        self.assertEqual((cfg.width, cfg.height), (400, 300))
        self.assertEqual(cfg.template, "sync")
        self.assertFalse(cfg.invert)
        self.assertTrue(cfg.push_now)
        self.assertEqual(cfg.timeout, 5.0)

        cfg_on = rlcd_cast.load_rlcd_cast_config(
            {
                "RLCD_CAST_ENABLED": "true",
                "RLCD_CAST_URL": "http://192.168.1.20:8787",
                "RLCD_CAST_TEMPLATE": "ring",
                "RLCD_CAST_INVERT": "1",
                "RLCD_CAST_PUSH_NOW": "0",
                "RLCD_CAST_TIMEOUT": "bad-num",
                "RLCD_CAST_WIDTH": "-10",
            }
        )
        self.assertTrue(cfg_on.enabled)
        self.assertEqual(cfg_on.template, "ring")
        self.assertTrue(cfg_on.invert)
        self.assertFalse(cfg_on.push_now)
        self.assertEqual(cfg_on.timeout, 5.0)
        self.assertEqual(cfg_on.width, 400)

    def test_normalize_cast_push_url(self):
        self.assertEqual(
            rlcd_cast.normalize_cast_push_url("http://127.0.0.1:8787", push_now=True),
            "http://127.0.0.1:8787/push?push_now=1",
        )
        self.assertEqual(
            rlcd_cast.normalize_cast_push_url("http://127.0.0.1:8787/push", push_now=False),
            "http://127.0.0.1:8787/push",
        )
        self.assertEqual(
            rlcd_cast.normalize_cast_push_url("http://127.0.0.1:8787/push?push_now=0", push_now=True),
            "http://127.0.0.1:8787/push?push_now=0",
        )


class TestRlcdCastRendering(unittest.TestCase):
    """验证 400×300 双模板绘制、反显与容错处理。"""

    def test_bar_and_ring_render_400x300_png_with_invert(self):
        snap = _full_sample_snapshot()
        for tpl in ("bar", "ring"):
            png_normal = rlcd_cast.render_rlcd_png(snap, template=tpl, invert=False)
            png_inv = rlcd_cast.render_rlcd_png(snap, template=tpl, invert=True)

            img_normal = Image.open(io.BytesIO(png_normal))
            img_inv = Image.open(io.BytesIO(png_inv))
            self.assertEqual(img_normal.size, (400, 300))
            self.assertEqual(img_inv.size, (400, 300))
            # 验证右下角背景色在正常（白）与反显（黑）下正好反转
            self.assertNotEqual(
                img_normal.convert("L").getpixel((395, 295)),
                img_inv.convert("L").getpixel((395, 295)),
            )

    def test_error_and_empty_snapshot_renders_safely(self):
        bad_snap = {
            "updated_at": "ERR",
            "antigravity": {"ok": False, "raw_status": "timeout"},
            "codex": {"ok": False, "raw_status": "no auth"},
            "deepseek": {"ok": False, "raw_status": "no key"},
        }
        for tpl in ("bar", "ring"):
            png = rlcd_cast.render_rlcd_png(bad_snap, template=tpl)
            img = Image.open(io.BytesIO(png))
            self.assertEqual(img.size, (400, 300))

    def test_custom_landscape_size_scaling(self):
        png = rlcd_cast.render_rlcd_png(_full_sample_snapshot(), width=480, height=360, template="bar")
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (480, 360))
        self.assertGreater(img.width, img.height)

    def test_edge_values_and_long_error_text_render_safely(self):
        long_err = "E" * 120 + " timeout while connecting upstream service"
        edge_snap = {
            "updated_at": "19:25",
            "antigravity": {
                "ok": True,
                "status": "ok",
                "rows": [
                    {"label": "VeryLongModelLabelName", "remaining_percent": 33.3333, "reset": "21:10"},
                    {"label": "Zero", "remaining_percent": 0, "reset": "now"},
                    {"label": "Full", "remaining_percent": 100, "reset": "7d"},
                    {"label": "BoolVal", "remaining_percent": True, "reset": "?"},
                ],
            },
            "codex": {
                "ok": True,
                "short_label": "5h",
                "short_used_percent": 100,
                "short_reset": "22:30",
                "long_label": "Wk",
                "long_used_percent": 0,
                "long_reset": "11/27 00:00",
                "reset_credits": {"available_count": 2, "credits": [{"expires_at": "12/01"}, {"expires_at": "12/02"}]},
                "status": "ok",
            },
            "deepseek": {"ok": False, "raw_status": long_err},
        }
        for tpl in ("bar", "ring"):
            png = rlcd_cast.render_rlcd_png(edge_snap, template=tpl)
            img = Image.open(io.BytesIO(png))
            self.assertEqual(img.size, (400, 300))

    def test_reset_credits_parts_do_not_duplicate_expiry(self):
        credits = {
            "available_count": 3,
            "credits": [
                {"expires_at": "12/01 04:24"},
                {"expires_at": "12/02 05:02"},
                {"expires_at": "12/13 05:54"},
            ],
        }
        head, exp = rlcd_cast._format_reset_parts(credits)
        self.assertIn("3", head)
        self.assertNotIn("12/01", head)
        self.assertNotIn("到期", head)

        bar_line1, bar_line2 = rlcd_cast._format_reset_lines(credits)
        self.assertEqual(bar_line2, "")
        self.assertLess(bar_line1.index("3"), bar_line1.index("12/01 04:24"))
        self.assertIn("12/02 05:02", bar_line1)
        self.assertIn("12/13 05:54", bar_line1)

        ring_line1, ring_line2 = rlcd_cast._format_reset_lines(credits, first_line_cards=1)
        self.assertLess(ring_line1.index("3"), ring_line1.index("12/01 04:24"))
        self.assertIn("12/02 05:02", ring_line2)
        self.assertIn("12/13 05:54", ring_line2)

    def test_ok_hides_extra_badges_and_aligns_deepseek_balance_right(self):
        snap_ok = _full_sample_snapshot()
        snap_ok["antigravity"]["status"] = "ok"
        snap_ok["deepseek"] = {"ok": True, "balance": 437.66, "symbol": "¥", "status": "ok"}

        bar_ok = rlcd_cast.render_rlcd_image(snap_ok, template="bar").convert("L")
        # 全 ok 时 ANTIGRAVITY 与 CODEX 标题行右侧均保持留白（无 OK 框、无独立重置卡字样）
        ag_top_right = [bar_ok.getpixel((x, y)) for y in range(30, 50) for x in range(340, 392)]
        self.assertTrue(all(px == 255 for px in ag_top_right))
        cx_top_right = [bar_ok.getpixel((x, y)) for y in range(145, 164) for x in range(300, 392)]
        self.assertTrue(all(px == 255 for px in cx_top_right))

        # DeepSeek 余额应右对齐绘制在右半侧，左下角标题右侧保持留白
        ds_left_mid = [bar_ok.getpixel((x, y)) for y in range(248, 294) for x in range(95, 220)]
        ds_right = [bar_ok.getpixel((x, y)) for y in range(248, 294) for x in range(280, 392)]
        self.assertTrue(all(px == 255 for px in ds_left_mid))
        self.assertTrue(any(px == 0 for px in ds_right))

        # 非 ok 告警状态仍应绘制黑底白字提示徽章
        snap_warn = _full_sample_snapshot()
        snap_warn["antigravity"]["status"] = "warn"
        bar_warn = rlcd_cast.render_rlcd_image(snap_warn, template="bar").convert("L")
        ag_warn_right = [bar_warn.getpixel((x, y)) for y in range(30, 50) for x in range(340, 392)]
        self.assertTrue(any(px == 0 for px in ag_warn_right))

        # 模板 2 (ring)：CODEX 标题行右侧无多余文本，DEEPSEEK 金额右对齐且底部无 OK 框
        ring_ok = rlcd_cast.render_rlcd_image(snap_ok, template="ring").convert("L")
        self.assertEqual(ring_ok.size, (400, 300))
        ring_cx_right = [ring_ok.getpixel((x, y)) for y in range(149, 168) for x in range(140, 242)]
        self.assertTrue(all(px == 255 for px in ring_cx_right))
        ring_ds_right = [ring_ok.getpixel((x, y)) for y in range(190, 240) for x in range(300, 392)]
        self.assertTrue(any(px == 0 for px in ring_ds_right))
        ring_ds_bottom = [ring_ok.getpixel((x, y)) for y in range(250, 290) for x in range(260, 392)]
        self.assertTrue(all(px == 255 for px in ring_ds_bottom))


class TestRlcdCastPushAndCompatibility(unittest.TestCase):
    """验证 HTTP 推流封装、异常容错及与 cast_server 后端格式兼容。"""

    def test_push_success_and_error_handling(self):
        cfg = rlcd_cast.load_rlcd_cast_config({"RLCD_CAST_ENABLED": "1", "RLCD_CAST_URL": "http://127.0.0.1:8787"})
        snap = _full_sample_snapshot()

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"ok": True, "frame_bytes": 15000}

        with patch.object(rlcd_cast.requests, "post", return_value=ok_resp) as post_mock:
            res = rlcd_cast.push_snapshot_to_cast(snap, cfg, template_override="bar")
            self.assertTrue(res["ok"])
            self.assertEqual(res["status_code"], 200)
            args, kwargs = post_mock.call_args
            self.assertEqual(args[0], "http://127.0.0.1:8787/push?push_now=1")
            self.assertEqual(kwargs["headers"]["Content-Type"], "image/png")
            self.assertEqual(Image.open(io.BytesIO(kwargs["data"])).size, (400, 300))

        with patch.object(rlcd_cast.requests, "post", side_effect=requests.ConnectionError("refused")):
            fail_res = rlcd_cast.push_snapshot_to_cast(snap, cfg)
            self.assertFalse(fail_res["ok"])
            self.assertIn("refused", fail_res["error"])

        bad_resp = MagicMock()
        bad_resp.status_code = 500
        bad_resp.text = "internal error"
        bad_resp.json.side_effect = ValueError("not json")
        with patch.object(rlcd_cast.requests, "post", return_value=bad_resp):
            http_fail = rlcd_cast.push_snapshot_to_cast(snap, cfg)
            self.assertFalse(http_fail["ok"])
            self.assertEqual(http_fail["status_code"], 500)

    def test_compatible_with_xiaozhi_cast_server_pipeline(self):
        cast_server_dir = Path(r"Y:\Dev\Waveshare\ESP32-S3-RLCD-4.2\xiaozhi-esp32\tools\cast_server")
        if not (cast_server_dir / "cast_server.py").exists():
            self.skipTest("cast_server.py not present")
        if str(cast_server_dir) not in sys.path:
            sys.path.insert(0, str(cast_server_dir))
        import cast_server  # noqa: E402

        png = rlcd_cast.render_rlcd_png(_full_sample_snapshot(), template="bar")
        converted = cast_server.convert_image_to_mono(
            png, {**cast_server.DEFAULT_CONFIG, "DITHER_MODE": "threshold"}
        )
        self.assertEqual(len(converted.mono_bytes), 15000)
        self.assertEqual((converted.width, converted.height), (400, 300))

    def test_end_to_end_push_to_live_cast_server(self):
        cast_server_dir = Path(r"Y:\Dev\Waveshare\ESP32-S3-RLCD-4.2\xiaozhi-esp32\tools\cast_server")
        if not (cast_server_dir / "cast_server.py").exists():
            self.skipTest("cast_server.py not present")
        if str(cast_server_dir) not in sys.path:
            sys.path.insert(0, str(cast_server_dir))
        import cast_server  # noqa: E402

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            cast_server.save_env_config(
                env_path,
                {**cast_server.DEFAULT_CONFIG, "DEVICE_IP": "127.0.0.1", "DEVICE_PORT": 65531, "DITHER_MODE": "threshold"},
            )
            service = cast_server.CastService(env_path)
            httpd = cast_server.create_http_server(service, "127.0.0.1", 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{httpd.server_port}"
                cfg = rlcd_cast.load_rlcd_cast_config({"RLCD_CAST_ENABLED": "1", "RLCD_CAST_URL": base})
                res = rlcd_cast.push_snapshot_to_cast(_full_sample_snapshot(), cfg, template_override="bar")
                self.assertTrue(res["ok"])
                self.assertEqual(res["response"]["frame_bytes"], 15000)

                with urllib.request.urlopen(f"{base}/health", timeout=3.0) as resp:
                    health = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(health["has_frame"])
                self.assertEqual(health["frame_seq"], 1)
                self.assertTrue(health["last_received_at"])

                with urllib.request.urlopen(f"{base}/preview.png", timeout=3.0) as resp:
                    preview_img = Image.open(io.BytesIO(resp.read()))
                self.assertEqual(preview_img.size, (400, 300))
                self.assertGreater(preview_img.width, preview_img.height)
            finally:
                httpd.shutdown()
                httpd.server_close()
                service.stop()

    def test_full_three_tier_rlcd_push_to_mock_esp32(self):
        cast_server_dir = Path(r"Y:\Dev\Waveshare\ESP32-S3-RLCD-4.2\xiaozhi-esp32\tools\cast_server")
        if not (cast_server_dir / "cast_server.py").exists():
            self.skipTest("cast_server.py not present")
        if str(cast_server_dir) not in sys.path:
            sys.path.insert(0, str(cast_server_dir))
        import cast_server  # noqa: E402

        received_frames: list[bytes] = []
        frame_evt = threading.Event()

        class FakeEsp32Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b""
                if self.path == "/api/cast/frame":
                    received_frames.append(body)
                    frame_evt.set()
                    resp_raw = json.dumps({"ok": True, "frames": len(received_frames)}).encode("utf-8")
                else:
                    resp_raw = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_raw)))
                self.end_headers()
                self.wfile.write(resp_raw)

        esp32_srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeEsp32Handler)
        esp32_srv.daemon_threads = True
        threading.Thread(target=esp32_srv.serve_forever, daemon=True).start()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                env_path = Path(tmpdir) / ".env"
                cfg_dict = cast_server.validate_config(
                    {
                        **cast_server.DEFAULT_CONFIG,
                        "DEVICE_IP": "127.0.0.1",
                        "DEVICE_PORT": esp32_srv.server_port,
                        "PUSH_INTERVAL_MS": 100,
                        "DITHER_MODE": "threshold",
                    }
                )
                cast_server.save_env_config(env_path, cfg_dict)
                service = cast_server.CastService(env_path)
                httpd = cast_server.create_http_server(service, "127.0.0.1", 0)
                service.start()
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
                try:
                    base = f"http://127.0.0.1:{httpd.server_port}"
                    cfg = rlcd_cast.load_rlcd_cast_config({"RLCD_CAST_ENABLED": "1", "RLCD_CAST_URL": base})
                    res = rlcd_cast.push_snapshot_to_cast(_full_sample_snapshot(), cfg, template_override="bar")
                    self.assertTrue(res["ok"])
                    self.assertTrue(frame_evt.wait(timeout=3.0), "Mock ESP32 未在超时前收到推流帧")
                    self.assertEqual(len(received_frames), 1)
                    self.assertEqual(len(received_frames[0]), 15000)

                    with urllib.request.urlopen(f"{base}/health", timeout=3.0) as resp:
                        health = json.loads(resp.read().decode("utf-8"))
                    self.assertGreaterEqual(health["frame_seq"], 1)
                    self.assertGreaterEqual(health["stats"]["pushed_frames"], 1)

                    with urllib.request.urlopen(f"{base}/preview.png", timeout=3.0) as resp:
                        self.assertEqual(Image.open(io.BytesIO(resp.read())).size, (400, 300))
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    service.stop()
        finally:
            esp32_srv.shutdown()
            esp32_srv.server_close()


class TestLocalAppRlcdIntegration(unittest.TestCase):
    """验证 Quote0Window 主程序内无线投屏开关、数据拉取联动与模板切换联动。"""

    def _create_window(self, env_overrides: dict):
        with patch.dict(os.environ, env_overrides, clear=False), \
             patch.object(local_app, "TrayManager"), \
             patch.object(local_app.Quote0Window, "_set_window_opacity"), \
             patch.object(local_app.Quote0Window, "refresh"), \
             patch.object(local_app.Quote0Window, "_schedule_refresh"):
            win = local_app.Quote0Window()
        win.root.update()
        return win

    def test_disabled_by_default_does_not_push(self):
        win = self._create_window({"RLCD_CAST_ENABLED": "0"})
        try:
            with patch.object(local_app, "build_snapshot", return_value=_full_sample_snapshot()), \
                 patch.object(local_app, "push_snapshot_to_cast") as push_mock, \
                 patch.object(win.root, "after"):
                win._fetch_and_update()
            push_mock.assert_not_called()
        finally:
            win.root.destroy()

    def test_enabled_pushes_on_fetch_template_sync_and_manual_trigger(self):
        win = self._create_window({"RLCD_CAST_ENABLED": "1", "RLCD_CAST_TEMPLATE": "sync"})
        try:
            snap = _full_sample_snapshot()
            win._last_snapshot = snap

            # 使用当前线程同步替代后台 Thread 启动以便精确断言调用次数
            class ImmediateThread:
                def __init__(self, target=None, daemon=None):
                    self._target = target

                def start(self):
                    if self._target:
                        self._target()

            with patch.object(local_app, "build_snapshot", return_value=snap), \
                 patch.object(local_app, "push_snapshot_to_cast", return_value={"ok": True}) as push_mock, \
                 patch.object(local_app.threading, "Thread", ImmediateThread), \
                 patch.object(win.root, "after"):
                win._fetch_and_update()
                self.assertEqual(push_mock.call_count, 1)
                self.assertEqual(push_mock.call_args.kwargs.get("template_override"), "bar")

                win._set_template("ring")
                self.assertEqual(push_mock.call_count, 2)
                self.assertEqual(push_mock.call_args.kwargs.get("template_override"), "ring")

                # 关闭开关后通过手动推送仍可执行单次推送，常规切换则不再触发
                win._rlcd_enabled_var.set(False)
                win._on_toggle_rlcd_cast()
                win._set_template("bar")
                self.assertEqual(push_mock.call_count, 2)

                win.push_to_rlcd_now()
                self.assertEqual(push_mock.call_count, 3)
        finally:
            win.root.destroy()

    def test_push_error_recorded_and_stale_sequence_skipped(self):
        win = self._create_window({"RLCD_CAST_ENABLED": "1", "RLCD_CAST_TEMPLATE": "sync"})
        try:
            snap = _full_sample_snapshot()
            first_entered = threading.Event()
            release_first = threading.Event()
            observed_calls = []
            prev_results = []

            def fake_push(snapshot, cfg, template_override=None):
                prev_results.append(win._rlcd_last_result)
                observed_calls.append((cfg.enabled, template_override))
                if len(observed_calls) == 1:
                    first_entered.set()
                    release_first.wait(timeout=3.0)
                    return {"ok": False, "error": "simulated error"}
                return {"ok": True, "status_code": 200, "bytes": 123}

            threads = []
            orig_thread_cls = local_app.threading.Thread

            def capture_thread(*args, **kwargs):
                t = orig_thread_cls(*args, **kwargs)
                threads.append(t)
                return t

            with patch.object(local_app, "push_snapshot_to_cast", side_effect=fake_push), \
                 patch.object(local_app.threading, "Thread", side_effect=capture_thread):
                # 第 1 个异步推流拿锁后暂停，主线程随即修改配置副本并连发第 2、3 个请求
                win._push_rlcd_async(snap, force=True)
                self.assertTrue(first_entered.wait(timeout=2.0))

                win._rlcd_enabled_var.set(False)
                win._on_toggle_rlcd_cast()
                # 验证首帧拿到的 cfg 快照未被主线程后续开关翻转污染
                win._push_rlcd_async(snap, force=True)
                win._push_rlcd_async(snap, force=True)
                release_first.set()

                for t in threads:
                    t.join(timeout=3.0)

            self.assertEqual(observed_calls[0][0], True)
            # 第 2 帧在等待锁期间已被第 3 帧取代，因此总共只执行第 1 帧和第 3 帧共 2 次推送
            self.assertEqual(len(observed_calls), 2)
            self.assertIsNotNone(prev_results[1])
            self.assertFalse(prev_results[1]["ok"])
            self.assertEqual(prev_results[1]["error"], "simulated error")
            self.assertIsNotNone(win._rlcd_last_result)
            self.assertTrue(win._rlcd_last_result["ok"])
        finally:
            win.root.destroy()


if __name__ == "__main__":
    unittest.main()
