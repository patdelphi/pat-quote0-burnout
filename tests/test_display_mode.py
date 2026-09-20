"""
rand0_display（Rand/0 Display Mode）测试。

覆盖 200×200 渲染的帧长度、位序打包、灰度量化，以及 WebSocket 推送的幂等逻辑。
推送测试使用 mock，不访问真实网络。
"""

import unittest
from unittest.mock import patch, MagicMock

import rand0_display
from rand0_display import (
    BW_SIZE,
    GRAY4_SIZE,
    SIZE,
    _pack_bw,
    _pack_gray4,
    render_frame,
    push_frame,
    _render_bw_image,
    _render_gray4_image,
)


def _sample_snapshot() -> dict:
    """构造一个可渲染的示例快照。"""
    return {
        "codex": {"ok": True, "short_label": "5h", "short_used_percent": 72,
                  "short_reset": "2h13m", "long_label": "Week",
                  "long_used_percent": 41, "long_reset": "123h3m",
                  "reset_credits": {"available_count": 0, "credits": []},
                  "status": "ok"},
        "deepseek": {"ok": True, "balance": 18.42, "currency": "USD",
                     "symbol": "$", "status": "ok"},
        "updated_at": "16:40",
    }


class RenderFrameTests(unittest.TestCase):
    """验证字节数、模式参数与打包内部函数。"""

    def test_bw_frame_length(self):
        frame = render_frame(_sample_snapshot(), "bw")
        self.assertEqual(len(frame), BW_SIZE)
        self.assertEqual(len(frame), 5000)

    def test_gray4_frame_length(self):
        frame = render_frame(_sample_snapshot(), "gray4")
        self.assertEqual(len(frame), GRAY4_SIZE)
        self.assertEqual(len(frame), 10000)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            render_frame(_sample_snapshot(), "foo")


class PackBWTests(unittest.TestCase):
    """验证 bw 位打包：1=白 0=黑，行主序，高层位在左。"""

    def _make_img(self, pixels):
        """根据像素值列表（0/1，长度须为 SIZE*SIZE）构建 "1" 模式图。"""
        from PIL import Image
        mode = Image.new("L", (SIZE, SIZE), 0)
        mode.putdata([255 if p else 0 for p in pixels])
        return mode.convert("1")

    def test_all_white_gives_0xff(self):
        img = self._make_img([1] * (SIZE * SIZE))
        out = _pack_bw(img)
        self.assertEqual(out, b"\xff" * BW_SIZE)

    def test_all_black_gives_zero(self):
        img = self._make_img([0] * (SIZE * SIZE))
        out = _pack_bw(img)
        self.assertEqual(out, b"\x00" * BW_SIZE)

    def test_first_pixel_uses_bit7(self):
        # 仅第一个像素为白，其余黑 → 第一字节最高位（bit7）为 1
        img = self._make_img([1] + [0] * (SIZE * SIZE - 1))
        out = _pack_bw(img)
        self.assertEqual(out[0], 0b10000000)
        self.assertTrue(all(b == 0 for b in out[1:]))

    def test_second_pixel_uses_bit6(self):
        img = self._make_img([0, 1] + [0] * (SIZE * SIZE - 2))
        out = _pack_bw(img)
        self.assertEqual(out[0], 0b01000000)


class PackGray4Tests(unittest.TestCase):
    """验证 gray4 位打包：00=白 01=浅灰 10=深灰 11=黑，首像素 bit7-6。"""

    def _make_gray_img(self, levels):
        """根据灰度值（0..255）列表构建 "L" 模式图。"""
        from PIL import Image
        img = Image.new("L", (SIZE, SIZE), 255)
        img.putdata(list(levels))
        return img

    def test_all_white_gives_zero(self):
        img = self._make_gray_img([255] * (SIZE * SIZE))  # 00=白
        img = img.point(rand0_display._gray4_quantize)
        out = _pack_gray4(img)
        self.assertEqual(out, b"\x00" * GRAY4_SIZE)

    def test_all_black_gives_0xff(self):
        img = self._make_gray_img([0] * (SIZE * SIZE))  # 11=黑
        img = img.point(rand0_display._gray4_quantize)
        out = _pack_gray4(img)
        self.assertEqual(out, b"\xff" * GRAY4_SIZE)

    def test_first_pixel_bits7_6(self):
        # 白(00) + 黑(11) + 白(00) + 黑(11) → 0b00110011
        img = self._make_gray_img([255, 0, 255, 0] + [255] * (SIZE * SIZE - 4))
        img = img.point(rand0_display._gray4_quantize)
        out = _pack_gray4(img)
        self.assertEqual(out[0], 0b00110011)

    def test_quantize_mapping(self):
        self.assertEqual(rand0_display._gray4_quantize(255), 255)  # 白
        self.assertEqual(rand0_display._gray4_quantize(170), 170)  # 浅灰
        self.assertEqual(rand0_display._gray4_quantize(85), 85)    # 深灰
        self.assertEqual(rand0_display._gray4_quantize(0), 0)      # 黑


class RenderImageTests(unittest.TestCase):
    """验证渲染图尺寸与像素总数。"""

    def test_bw_image_size(self):
        img = _render_bw_image(_sample_snapshot())
        self.assertEqual(img.size, (SIZE, SIZE))

    def test_gray4_image_size(self):
        img = _render_gray4_image(_sample_snapshot())
        self.assertEqual(img.size, (SIZE, SIZE))


class PushFrameTests(unittest.TestCase):
    """验证 WebSocket 推送逻辑（mock，不联网）。"""

    def test_sends_binary_and_returns_message_count(self):
        from websocket import WebSocketTimeoutException
        fake_ws = MagicMock()
        # 设备返回一条按钮事件 JSON，随后读取超时视为本轮结束
        fake_ws.recv.side_effect = [
            '{"type":"key","key":"up","action":"short"}',
            WebSocketTimeoutException("no more"),
        ]
        with patch("rand0_display.WebSocket", return_value=fake_ws):
            count = push_frame("192.168.1.100", "bw", b"\x00" * BW_SIZE)
        fake_ws.send_binary.assert_called_once_with(b"\x00" * BW_SIZE)
        fake_ws.connect.assert_called_once_with("ws://192.168.1.100/display/bw")
        self.assertEqual(count, 1)

    def test_frame_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            push_frame("ip", "bw", b"\x00")  # 长度错误

    def test_connection_timeout_raises(self):
        from websocket import WebSocketTimeoutException
        fake_ws = MagicMock()
        fake_ws.connect.side_effect = WebSocketTimeoutException("timeout")
        with patch("rand0_display.WebSocket", return_value=fake_ws):
            with self.assertRaises(RuntimeError):
                push_frame("127.0.0.1", "bw", b"\x00" * BW_SIZE)


if __name__ == "__main__":
    unittest.main()