"""
Render a 296×152 pure black/white PNG for Quote/0 e-ink display.

v0.4 E-Ink Design System (UI/UX Pro Max):
  Style: E-Ink / Paper + Minimalist Monochrome
  - Pure #000000 / #FFFFFF only
  - Zero border-radius, no shadows, no gradients
  - 4px black structural dividers (full-bleed)
  - Typography-first: data in monospace, labels compact
  - Instant transitions (no animation on e-ink)
  - High contrast, WCAG AAA
  Typography: Terminal CLI Monospace (12/14/16pt strict scale)
  - Menlo 400 weight, line-height 1.2x for density
  - Section headers 10pt, data 14pt, balance 20pt
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

# ── Font: strict 10/12/14/20 scale ────────────────────────────────────────

def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── Progress bar (E-Ink: solid available, outline used) ───────────────────

def _draw_bar(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    bar_w: int, bar_h: int,
    avail_pct: int | None,
    seg_count: int = 10,
):
    """10-segment bar. Filled = available (remaining quota), outline = used."""
    seg_w = (bar_w - (seg_count - 1) * 2) // seg_count
    gap = 2

    if avail_pct is None:
        used_segs = 0
    else:
        used_segs = max(0, min(seg_count, round(avail_pct / seg_count)))

    for i in range(seg_count):
        sx = x + i * (seg_w + gap)
        if i < used_segs:
            draw.rectangle([sx, y, sx + seg_w - 1, y + bar_h - 1], fill=BLACK)
        else:
            draw.rectangle([sx, y, sx + seg_w - 1, y + bar_h - 1], outline=BLACK)


# ── v0.4 E-Ink Dashboard ──────────────────────────────────────────────────

def _render_v4(draw: ImageDraw.ImageDraw, snapshot: dict):
    """E-Ink dashboard — monochrome, typography-first, 4px dividers."""
    title_font   = _font(14)
    label_font   = _font(10)   # Section headers
    data_font    = _font(14)   # Data rows
    reset_font   = _font(12)
    balance_font = _font(20)
    badge_font   = _font(12)

    cx = snapshot.get("codex", {})
    ds = snapshot.get("deepseek", {})
    updated = snapshot.get("updated_at", datetime.now().strftime("%H:%M"))

    # ── Title bar ──────────────────────────────────────────────────────
    title = "AI BURNOUT"
    draw.text((PAD, PAD), title, font=title_font, fill=BLACK)
    _, th = _text_size(draw, title, title_font)

    tsw, _ = _text_size(draw, updated, reset_font)
    draw.text((W - PAD - tsw, PAD + 1), updated, font=reset_font, fill=BLACK)

    # 4px structural divider
    div_y = PAD + th + 5
    draw.rectangle([PAD, div_y, W - PAD, div_y + 3], fill=BLACK)

    # ── CODEX ──────────────────────────────────────────────────────────
    y = div_y + 7

    # Compact section header
    draw.text((PAD, y), "CODEX", font=label_font, fill=BLACK)
    _, sh = _text_size(draw, "CODEX", label_font)
    y += sh + 4

    if cx.get("ok"):
        short_label = cx.get("short_label", "?")
        short_used = cx.get("short_used_percent")
        short_rem = (100 - short_used) if short_used is not None else None
        short_reset = cx.get("short_reset", "?")

        rem_text = f"{short_rem}%" if short_rem is not None else "?"

        # Bar alignment: fixed width labels
        lw_s, lh = _text_size(draw, short_label, data_font)
        long_label = cx.get("long_label", "?")
        lw_l, _ = _text_size(draw, long_label, data_font)
        label_w = max(lw_s, lw_l)

        bar_x = PAD + label_w + 8
        bar_w = 110
        bar_h = lh  # Full row height

        # Short row: label + bar + rem%, reset right-aligned
        _draw_bar(draw, bar_x, y, bar_w, bar_h, short_rem)
        pctx = bar_x + bar_w + 8

        draw.text((PAD, y), short_label, font=data_font, fill=BLACK)
        draw.text((pctx, y), rem_text, font=data_font, fill=BLACK)

        if short_reset and short_reset != "?":
            rw, _ = _text_size(draw, short_reset, reset_font)
            draw.text((W - PAD - rw, y + 1), short_reset, font=reset_font, fill=BLACK)

        y += lh + 6

        # Long row
        long_used = cx.get("long_used_percent")
        if long_used is not None:
            long_rem = 100 - long_used
            _draw_bar(draw, bar_x, y, bar_w, bar_h, long_rem)
            draw.text((PAD, y), long_label, font=data_font, fill=BLACK)
            draw.text((pctx, y), f"{long_rem}%", font=data_font, fill=BLACK)
            y += lh + 6

        # Breathing room
        y += 2
    else:
        status = cx.get("raw_status", "error")
        draw.text((PAD, y), status, font=data_font, fill=BLACK)
        _, eh = _text_size(draw, status, data_font)
        y += eh + 4

    # 2px hairline divider between sections
    y += 2
    draw.rectangle([PAD, y, W - PAD, y + 1], fill=BLACK)

    # ── DEEPSEEK ───────────────────────────────────────────────────────
    y += 6

    draw.text((PAD, y), "DEEPSEEK", font=label_font, fill=BLACK)
    _, sh = _text_size(draw, "DEEPSEEK", label_font)
    y += sh + 4

    if ds.get("ok"):
        bal = ds.get("balance")
        sym = ds.get("symbol", "$")
        status = ds.get("status", "ok").upper()

        bal_text = f"{sym}{bal:.2f}" if bal is not None else "?"
        draw.text((PAD, y), bal_text, font=balance_font, fill=BLACK)

        # Status badge — text only, right-aligned, no border (E-Ink: clean)
        bw, _ = _text_size(draw, status, badge_font)
        draw.text((W - PAD - bw, y + 5), status, font=badge_font, fill=BLACK)
    else:
        status = ds.get("raw_status", "error")
        draw.text((PAD, y), status, font=data_font, fill=BLACK)


# ── Legacy layout (v0.2–v0.3 compat) ────────────────────────────────────

def _render_legacy(draw: ImageDraw.ImageDraw, codex_text: str, deepseek_text: str):
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
    draw.rectangle([PAD, div_y, W - PAD, div_y + 1], fill=BLACK)

    now = datetime.now().strftime("%H:%M")
    tsw, _ = _text_size(draw, now, ts_font)
    draw.text((W - PAD - tsw, div_y + 8), now, font=ts_font, fill=BLACK)


# ── Public API ──────────────────────────────────────────────────────────

def render_image(
    codex_text_or_snapshot: str | dict,
    deepseek_text: str | None = None,
) -> bytes:
    """Return PNG bytes (296×152, pure B&W).

    v0.4 (snapshot dict): E-Ink dashboard layout
    Legacy (two strings): backward compat
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
