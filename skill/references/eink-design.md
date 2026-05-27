# E-Ink Dashboard Design

296×152 B&W e-ink dashboards for Quote/0 devices.

## Layout (v0.6)

```
                        16:40
◆ CODEX
5h  [████████████░░░░░] 89%  4h41m
Week [████████░░░░░░░░] 69%  5d23h
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
◆ DEEPSEEK
$18.42                        OK
```

- **Codex**: dual-row, inline dot-grid bar. Bar = remaining%, text = remaining% + reset.
- **DeepSeek**: VCR 21px balance + 16px status badge, bottom-aligned.
- **Divider**: 6px dash / 4px gap.

## Codex Row

```python
ROW_H = 22
BAR_H = 14
LABEL_W = 36

def _draw_codex_row(draw, y, label, used_pct, reset, note_font, label_font, note_x=None):
    bar_y = y + (ROW_H - BAR_H) // 2
    # Label left, right text (remaining% + reset), bar middle
    draw.text((PAD, …), label, font=label_font)
    note = f"{100-used_pct:.0f}%  {reset}"
    draw.text((note_x, …), note, font=note_font)
    _bar_dots(draw, PAD+LABEL_W, bar_y, note_x-4-(PAD+LABEL_W), BAR_H, 100-used_pct)
```

Pre-compute `note_x` from max note width across both rows for equal bar widths.

## Bar Style (dot-grid)

```python
def _bar_dots(draw, x, y, w, h, used_pct):
    draw.rectangle([x, y, x+w-1, y+h-1], outline=BLACK)
    filled = int((w-2) * used_pct / 100)
    draw.rectangle([x+1, y+1, x+filled, y+h-2], fill=BLACK)
    # 4px dot grid in empty area
    for dy in range(y+2, y+h-2, 4):
        for dx in range(x+2, x+w-2, 4):
            if dx >= x+1+filled:
                draw.point((dx, dy), fill=BLACK)
```

## Font Stack

| Font | Size | File | Use |
|------|------|------|-----|
| VCR OSD Mono | 21px | VCR_OSD_MONO_1.001.ttf | DeepSeek balance |
| PixelOperator | 16px | PixelOperator.ttf | All other text |
| Minecraftia | 8px | Minecraftia-Regular.ttf | Timestamp only |

All in `assets/fonts/`.

## Logos

16×16 pixel art in `assets/logos/`. Pasted pixel-by-pixel (PIL `paste()` doesn't work for pure B&W blending).

```python
LOGO_W = 16
LOGO_GAP = 4
LABEL_X = PAD + LOGO_W + LOGO_GAP  # 30

def _logo(logo_img, y):
    for dy in range(LOGO_W):
        for dx in range(LOGO_W):
            if logo_img.getpixel((dx, dy)) == 0:
                img.putpixel((PAD + dx, y + dy), BLACK)
```

## Time Format

```python
def _time_until(val) -> str:
    # val: ISO string or unix timestamp
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    h, m = divmod(secs, 3600)[0], (secs % 3600) // 60
    if h >= 24: return f"{h//24}d{h%24}h"
    if h > 0:   return f"{h}h{m:02d}m" if m else f"{h}h"
    return f"{m}m"
```

## Bottom Whitespace

Target 15-20px below the last content element. Use `textbbox()` to trace exact positions.
Current layout: DeepSeek balance bottom ≈ y=133, display height = 152 → 19px remaining.
