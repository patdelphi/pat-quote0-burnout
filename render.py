"""
Render a 296×152 pure black/white PNG for Quote/0.

v0.4: accepts a snapshot dict with structured codex/deepseek data.
      Falls back to legacy string mode for backward compat.

Layout:
┌──────────────────────────────┐
│ AI BURNOUT              16:40│
│                              │
│ CODEX                        │
│ 5h  ███████░░░ 72%  2h13m    │
│ Wk  ████░░░░░░ 41%           │
│                              │
│ DEEPSEEK                     │
│ $18.42                 [OK]  │
└──────────────────────────────┘
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 296, 152
PAD = 8

FONT_PATH = "/System/Library/Fonts/Menlo.ttc"

BLACK = 0
WHITE = 255

# ── Font helpers ──────────────────────────────────────────────────────────────

def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── Progress bar helper ───────────────────────────────────────────────────────

def _draw_bar(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    bar_w: int, bar_h: int,
    used_pct: int | None,
    seg_count: int = 10,
):
    """Draw a 10-segment progress bar. Solid = used, outline = remaining."""
    seg_w = (bar_w - (seg_count - 1) * 2) // seg_count
    gap = 2

    if used_pct is None:
        used_segs = 0
    else:
        used_segs = max(0, min(seg_count, round(used_pct / seg_count)))

    for i in range(seg_count):
        sx = x + i * (seg_w + gap)
        if i < used_segs:
            draw.rectangle([sx, y, sx + seg_w - 1, y + bar_h - 1], fill=BLACK)
        else:
            draw.rectangle([sx, y, sx + seg_w - 1, y + bar_h - 1], outline=BLACK)


# ── v0.4 Layout ────────────────────────────────────────────────────────────────

def _render_v4(draw: ImageDraw.ImageDraw, snapshot: dict):
    """Render v0.4 dashboard layout matching HTML mockup."""
    title_font = _font(14)
    section_font = _font(10)
    row_font = _font(11)
    balance_font = _font(20)
    badge_font = _font(12)

    cx = snapshot.get("codex", {})
    ds = snapshot.get("deepseek", {})
    updated = snapshot.get("updated_at", datetime.now().strftime("%H:%M"))

    # ── Title bar ──────────────────────────────────────────────────────────
    title = "AI BURNOUT"
    draw.text((PAD, PAD), title, font=title_font, fill=BLACK)
    _, th = _text_size(draw, title, title_font)

    tsw, _ = _text_size(draw, updated, _font(12))
    draw.text((W - PAD - tsw, PAD + 1), updated, font=_font(12), fill=BLACK)

    # Divider
    div1_y = PAD + th + 4
    draw.line([(PAD, div1_y), (W - PAD, div1_y)], fill=BLACK, width=1)

    # ── Codex section ──────────────────────────────────────────────────────
    y = div1_y + 6

    draw.text((PAD, y), "CODEX", font=section_font, fill=BLACK)
    _, sh = _text_size(draw, "CODEX", section_font)
    y += sh + 2

    if cx.get("ok"):
        short_label = cx.get("short_label", "?")
        short_pct = cx.get("short_used_percent")
        short_reset = cx.get("short_reset", "?")

        pct_text = f"{short_pct}%" if short_pct is not None else "?"

        # Font metrics
        lw, lh = _text_size(draw, short_label, row_font)

        # Progress bar
        bar_x = PAD + lw + 4
        bar_w = 56
        bar_h = lh - 2
        _draw_bar(draw, bar_x, y + 1, bar_w, bar_h, short_pct)

        # Percentage after bar
        pctx = bar_x + bar_w + 4

        # Draw label + percentage
        draw.text((PAD, y), short_label, font=row_font, fill=BLACK)
        draw.text((pctx, y), pct_text, font=row_font, fill=BLACK)

        # Reset time — right-aligned
        reset_w, _ = _text_size(draw, short_reset, row_font)
        draw.text((W - PAD - reset_w, y), short_reset, font=row_font, fill=BLACK)

        y += lh + 2

        # Long window row: Wk  ████░░░░░░ 41%
        long_label = cx.get("long_label", "?")
        long_pct = cx.get("long_used_percent")

        if long_pct is not None:
            long_pct_text = f"{long_pct}%"
            llw, llh = _text_size(draw, long_label, row_font)
            _draw_bar(draw, bar_x, y + 1, bar_w, bar_h, long_pct)
            draw.text((PAD, y), long_label, font=row_font, fill=BLACK)
            draw.text((pctx, y), long_pct_text, font=row_font, fill=BLACK)
            y += llh + 2
    else:
        status = cx.get("raw_status", "error")
        draw.text((PAD, y), status, font=row_font, fill=BLACK)
        _, eh = _text_size(draw, status, row_font)
        y += eh + 2

    # Divider between sections
    y += 2
    draw.line([(PAD, y), (W - PAD, y)], fill=BLACK, width=1)
    y += 6

    # ── DeepSeek section ───────────────────────────────────────────────────
    draw.text((PAD, y), "DEEPSEEK", font=section_font, fill=BLACK)
    _, sh = _text_size(draw, "DEEPSEEK", section_font)
    y += sh + 4

    if ds.get("ok"):
        bal = ds.get("balance")
        sym = ds.get("symbol", "$")
        status = ds.get("status", "ok").upper()

        bal_text = f"{sym}{bal:.2f}" if bal is not None else "?"
        draw.text((PAD, y), bal_text, font=balance_font, fill=BLACK)

        # Status badge — bordered, right-aligned
        bw, bh = _text_size(draw, status, badge_font)
        bx = W - PAD - bw - 6  # 3px padding each side
        by = y + 2  # align with baseline of large text

        # Badge border
        draw.rectangle([bx - 3, by - 1, bx + bw + 2, by + bh + 1], outline=BLACK)
        draw.text((bx, by), status, font=badge_font, fill=BLACK)
    else:
        status = ds.get("raw_status", "error")
        draw.text((PAD, y), status, font=row_font, fill=BLACK)


# ── Legacy layout (v0.2–v0.3 compat) ──────────────────────────────────────────

def _render_legacy(draw: ImageDraw.ImageDraw, codex_text: str, deepseek_text: str):
    """Legacy two-line layout for backward compat."""
    title_font = _font(16)
    body_font = _font(18)
    ts_font = _font(12)

    title = "AI Usage"
    tw, th = _text_size(draw, title, title_font)
    draw.text(((W - tw) // 2, PAD), title, font=title_font, fill=BLACK)

    label1 = "Codex:"
    lw, lh = _text_size(draw, label1, body_font)
    y1 = PAD + th + 18
    draw.text((PAD, y1), label1, font=body_font, fill=BLACK)
    draw.text((PAD + lw + 12, y1), codex_text, font=body_font, fill=BLACK)

    label2 = "DeepSeek:"
    lw2, lh2 = _text_size(draw, label2, body_font)
    y2 = y1 + lh + 14
    draw.text((PAD, y2), label2, font=body_font, fill=BLACK)
    draw.text((PAD + lw2 + 12, y2), deepseek_text, font=body_font, fill=BLACK)

    div_y = y2 + lh2 + 16
    draw.line([(PAD, div_y), (W - PAD, div_y)], fill=BLACK, width=1)

    now = datetime.now().strftime("%H:%M")
    tsw, tsh = _text_size(draw, now, ts_font)
    draw.text((W - PAD - tsw, div_y + 8), now, font=ts_font, fill=BLACK)


# ── Public API ────────────────────────────────────────────────────────────────

def render_image(
    codex_text_or_snapshot: str | dict,
    deepseek_text: str | None = None,
) -> bytes:
    """Return PNG bytes (296×152, pure B&W).

    v0.4 (snapshot dict):
        render_image({"codex": {...}, "deepseek": {...}, "updated_at": "16:40"})

    Legacy (two strings):
        render_image("95% 5h", "¥25.91")
    """
    img = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    if isinstance(codex_text_or_snapshot, dict):
        _render_v4(draw, codex_text_or_snapshot)
    else:
        _render_legacy(draw, codex_text_or_snapshot, deepseek_text or "?")

    img = img.convert("1", dither=Image.Dither.NONE)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    snap = {
        "codex": {
            "ok": True,
            "short_label": "5h",
            "short_used_percent": 72,
            "short_reset": "2h13m",
            "long_label": "Week",
            "long_used_percent": 41,
            "status": "ok",
        },
        "deepseek": {
            "ok": True,
            "balance": 18.42,
            "currency": "USD",
            "symbol": "$",
            "status": "ok",
        },
        "updated_at": "16:40",
    }
    png = render_image(snap)
    out = Path(__file__).parent / "preview.png"
    out.write_bytes(png)
    print(f"Saved {out} ({len(png)} bytes)")
