"""
Render a 296×152 pure black/white PNG for Quote/0.

Uses Menlo (macOS system monospace) — no anti-aliasing, only #000 / #FFF.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 296, 152
PAD = 8

FONT_PATH = "/System/Library/Fonts/Menlo.ttc"

BLACK = 0
WHITE = 255


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_image(
    codex_text: str,
    deepseek_text: str,
) -> bytes:
    """Return PNG bytes (296×152, pure B&W)."""
    img = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    title_font = _font(16)
    body_font = _font(18)
    ts_font = _font(12)

    # Title
    title = "AI Usage"
    tw, th = _text_size(draw, title, title_font)
    draw.text(((W - tw) // 2, PAD), title, font=title_font, fill=BLACK)

    # Line 1: Codex
    label1 = "Codex:"
    lw, lh = _text_size(draw, label1, body_font)
    y1 = PAD + th + 18
    draw.text((PAD, y1), label1, font=body_font, fill=BLACK)
    draw.text((PAD + lw + 12, y1), codex_text, font=body_font, fill=BLACK)

    # Line 2: DeepSeek
    label2 = "DeepSeek:"
    lw2, lh2 = _text_size(draw, label2, body_font)
    y2 = y1 + lh + 14
    draw.text((PAD, y2), label2, font=body_font, fill=BLACK)
    draw.text((PAD + lw2 + 12, y2), deepseek_text, font=body_font, fill=BLACK)

    # Divider
    div_y = y2 + lh2 + 16
    draw.line([(PAD, div_y), (W - PAD, div_y)], fill=BLACK, width=1)

    # Timestamp
    now = datetime.now().strftime("%H:%M")
    tsw, tsh = _text_size(draw, now, ts_font)
    draw.text((W - PAD - tsw, div_y + 8), now, font=ts_font, fill=BLACK)

    # Save to bytes as pure 1-bit PNG
    buf = io.BytesIO()
    img = img.convert("1", dither=Image.Dither.NONE)
    img.save(buf, format="PNG")
    return buf.getvalue()


# For standalone testing
if __name__ == "__main__":
    png = render_image("95% 5h", "¥25.91")
    out = Path(__file__).parent / "preview.png"
    out.write_bytes(png)
    print(f"Saved {out} ({len(png)} bytes)")
