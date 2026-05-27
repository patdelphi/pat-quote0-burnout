# quote0-burnout

AI usage dashboard for MindReset Quote/0 e-ink display — OpenAI Codex + DeepSeek.

[中文](README.md)

![Device photo](docs/preview.jpg)
![Example render](docs/example.png)

## Layout

```
                        16:40
◆ CODEX
5h  [████████████░░░░░] 89%  4h41m
Week [████████████░░░░░░] 69%  5d23h
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
◆ DEEPSEEK
$18.42                        OK
```

- **Codex**: dual-row (5h / Week) with inline dot-grid bar. Shows remaining% + reset countdown.
- **DeepSeek**: balance in 21px VCR OSD Mono + status badge.
- **Fonts**: PixelOperator 16px / VCR OSD Mono 21px / Minecraftia 8px.
- Codex data via direct OAuth API — **no CLI dependency**.

> Full design spec, API reference, and rendering details in [`skill/`](skill/).

## Install

```bash
pip install -r requirements.txt
codex   # one-time authentication
```

## Configure

```bash
cp config.example.env .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `QUOTE0_API_KEY` | ✓ | Quote/0 API key |
| `QUOTE0_DEVICE_ID` | ✓ | Device ID |
| `DEEPSEEK_API_KEY` | | DeepSeek API key |
| `CODEX_ACCESS_TOKEN` | | Override Codex token (default: ~/.codex/auth.json) |

## Usage

```bash
python display.py --preview   # local preview
python display.py             # push to device
python display.py --check     # self-check
```

## Scheduling (macOS launchd)

```bash
cp scripts/com.ajax.quote0-burnout.plist.example ~/Library/LaunchAgents/
# edit the Program path, then:
launchctl load ~/Library/LaunchAgents/com.ajax.quote0-burnout.plist
```

Runs every 5 minutes.

## Troubleshooting

```bash
python display.py --check
```

- **Codex "no auth"** — run `codex` to re-authenticate
- **Push 404** — delete and re-add the IMAGE_API card in Dot. App Content Studio
- **Schedule not updating** — `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`

## Skill

This repo includes [skill/SKILL.md](skill/SKILL.md) following the [Vercel Skills](https://github.com/nousresearch/hermes-agent) standard. Drop it into your Hermes Agent skills directory for AI-assisted dashboard development.
