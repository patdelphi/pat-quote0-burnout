---
name: quote0-burnout
description: Build and maintain Quote/0 e-ink dashboards — Codex + DeepSeek usage on 296×152 B&W display.
version: 1.0.0
author: Ajax
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [quote0, e-ink, dashboard, codex, deepseek, pillow]
    related_skills: [e-ink-rendering]
---

# Quote/0 Burnout Dashboard

Render and push a 296×152 B&W AI usage dashboard to MindReset Quote/0 devices.

## When to Use

- Building or modifying a Quote/0 e-ink dashboard
- Pushing image content to Quote/0 via the HTTP API
- Debugging rendering or layout issues (Pillow, pixel fonts)
- Setting up launchd scheduling for periodic updates
- Fetching OpenAI Codex plan usage via OAuth API

## Architecture

```
display.py     # CLI entry: fetch → snapshot → render → push
render.py      # Pillow 296×152 pure B&W PNG
run.sh         # launchd wrapper (sets PATH, sources .env)
config.example.env
```

### Data flow

1. `display.py` → `_load_codex_token()` reads `~/.codex/auth.json`
2. `GET https://chatgpt.com/backend-api/wham/usage` → `rate_limit.primary_window`, `secondary_window`
3. DeepSeek: `GET https://api.deepseek.com/user/balance`
4. `build_snapshot()` → structured dict
5. `render.py::render_image()` → Pillow → pure B&W PNG
6. `push_image()` → Quote/0 Image API

## Codex Data (Direct OAuth API)

No CLI dependency. Token from `~/.codex/auth.json` or `CODEX_ACCESS_TOKEN` env var.

```python
GET https://chatgpt.com/backend-api/wham/usage
Authorization: Bearer <token>
ChatGPT-Account-Id: <account_id>
```

Response shape:
```python
{
    "plan_type": "pro",
    "rate_limit": {
        "primary_window": {"used_percent": 72.0, "reset_at": 1717000000},
        "secondary_window": {"used_percent": 41.0, "reset_at": 1717600000},
    }
}
```

- `used_percent` → float (72.0 = 72% used)
- `reset_at` → unix timestamp (int)
- Labels hardcoded: primary → "5h", secondary → "Week"

## Snapshot Format

```python
snapshot = {
    "codex": {
        "ok": True,
        "short_label": "5h",
        "short_used_percent": 72,
        "short_reset": "4h41m",
        "long_label": "Week",
        "long_used_percent": 41,
        "long_reset": "5d22h",
        "status": "warn",
    },
    "deepseek": {
        "ok": True,
        "balance": 92.64,
        "currency": "USD",
        "symbol": "$",
        "status": "ok",
    },
    "updated_at": "16:40",
}
```

Status rules: Codex `<70%` ok, `70-89%` warn, `≥90%` hot.
DeepSeek: `≥10` ok, `3-10` warn, `<3` hot.

## E-Ink Rendering

See `references/eink-design.md` for full layout, font stack, and spacing.

Key points:
- 296×152 pure B&W. `Image.new("L", …).convert("1", dither=NONE)`
- **Fonts**: PixelOperator 16px (labels/text), VCR OSD Mono 21px (DeepSeek balance), Minecraftia 8px (timestamp)
- **Logos**: 16×16 pixel art in `assets/logos/`
- **Dual-row Codex**: label + inline bar(dots) + remaining% + reset
- **Bar**: outline + dot-grid empty area. Filled = REMAINING.
- **Divider**: 6px dash / 4px gap
- **Time format**: ≥24h → `XdXXh`

## Quote/0 API

See `references/quote0-api.md` for endpoint details.

```python
POST https://dot.mindreset.tech/api/authV2/open/device/{id}/image
```

Key rules:
- Single IMAGE_API card → push WITHOUT `taskKey`
- Dither: `DIFFUSION` / `FLOYD_STEINBERG`, border 0
- `refreshNow: true` for immediate display

## launchd Scheduling

`scripts/com.ajax.quote0-burnout.plist.example` → `~/Library/LaunchAgents/`

- `StartCalendarInterval` every 5 minutes at :00, :05...
- `run.sh` exports `PATH="/opt/homebrew/bin:$PATH"` for homebrew deps
- Kickstart: `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`

## Quick Reference

```bash
# Preview (no push)
python display.py --preview

# Push to device
source .env && python display.py

# Self-check
python display.py --check

# Debug snapshot JSON
python display.py --debug-json
```

## Common Pitfalls

1. **Bar shows used instead of remaining.** Text and bar MUST both reflect remaining (100 - used_pct).
2. **Equal bar widths.** Pre-compute max note width and pass consistent `note_x` to both rows.
3. **Pixel font spacing.** Use `textbbox()` after every font change — pixel fonts have very different metrics from system fonts.
4. **Quote/0 404 "未找到图像 API 内容".** Delete and re-add the IMAGE_API card in Dot. App Content Studio.
5. **Device shows stale content.** Set `refreshNow=true` or wait for next content cycle.

## Verification Checklist

- [ ] `python display.py --check` passes all sections
- [ ] `python display.py --preview` renders clean 296×152 PNG
- [ ] Progress bars equal width, both show REMAINING
- [ ] No text overlap or clipping (verify with `textbbox()`)
- [ ] DeepSeek balance in VCR 21px, bottom-aligned with status badge
- [ ] Push succeeds: `python display.py`
