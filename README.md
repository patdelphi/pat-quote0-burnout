# quote0-burnout

Minimal AI usage dashboard for MindReset Quote/0 — Codex + DeepSeek on e-ink.

v0.4 renders a compact 296×152 B&W dashboard with progress bars and status indicators.

## v0.8 Layout

```
┌──────────────────────────────┐
│                        16:40 │
│                              │
│ ◆ CODEX                      │
│ 28% - reset 2h13m            │  ← remaining (not used)
│ ███░░░░░░░░░░░░░░░           │  ← bar = remaining
│ 5h                  Week 41% │
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│ ◆ DEEPSEEK                   │
│ $18.42                  OK   │
└──────────────────────────────┘
```

- **Codex**: remaining percentage with progress bar. 28% = 28% left (72% used).
- **DeepSeek**: balance with status badge (OK / WARN / HOT).
- All text: PixelOperator 16px. Timestamp: Minecraftia 8px.
- Status levels: `ok` (<70% used), `warn` (70–89% used), `hot` (≥90% used).

## Install

```bash
pip install -r requirements.txt
# Codex auth auto-reads ~/.codex/auth.json (from codex CLI login)
# Or set CODEX_ACCESS_TOKEN in .env to override
```

## Configure

```bash
cp config.example.env .env
# edit .env with real keys
source .env
```

### Required vars

| Variable | Required | Description |
|----------|----------|-------------|
| `QUOTE0_API_KEY` | Yes | Quote/0 API key |
| `QUOTE0_DEVICE_ID` | Yes | Quote/0 device ID |
| `QUOTE0_IMAGE_TASK_KEY` | No | taskKey for Image API content slot (only needed with multiple cards) |
| `QUOTE0_TEXT_TASK_KEY` | No | taskKey for Text API content slot |
| `QUOTE0_REFRESH_NOW` | No | Force immediate display (`true` for manual push, `false` for scheduled) |
| `DEEPSEEK_API_KEY` | No | DeepSeek API key |
| `CODEX_ACCESS_TOKEN` | No | Override Codex OAuth token (auto-read from ~/.codex/auth.json) |
| `CODEX_ACCOUNT_ID` | No | Codex account ID for ChatGPT-Account-Id header |
| `QUOTE0_PREVIEW_PATH` | No | Preview image path (default: `/tmp/quote0_burnout_preview.png`) |

### Dot. App setup

In Content Studio, add a single **Image API content** card to the device task.
Keep only one IMAGE_API card — the script pushes without `taskKey` and targets
the sole slot automatically.

## Usage

```bash
# Debug — print structured snapshot as JSON
python display.py --debug-json

# Self-check — tests everything without pushing
python display.py --check

# List task slots
python display.py --list-tasks
python display.py --list-tasks fixed
python display.py --list-tasks loop

# Preview only — render PNG locally, no push
python display.py --preview
open /tmp/quote0_burnout_preview.png

# Push to Quote/0 (Image API)
python display.py

# Text API fallback (v0.1 legacy)
python display.py --text
python quote0_usage.py              # legacy standalone Text API
```

## Schedule

**macOS launchd** — copy `com.ajax.quote0-burnout.plist.example` to
`~/Library/LaunchAgents/`, edit the `Program` path to match your checkout, then:

```bash
launchctl load ~/Library/LaunchAgents/com.ajax.quote0-burnout.plist
```

Runs every 5 minutes at :00, :05, :10...

## Smoke test

```bash
# verify env
source .env && echo "API key length: ${#QUOTE0_API_KEY}"

# test CodexBar
codexbar usage --provider codex --format json --source cli | python3 -m json.tool > /dev/null \
  && echo "CodexBar OK" || echo "CodexBar FAIL"

# self-check
python display.py --check

# debug snapshot
python display.py --debug-json

# preview only (no push)
python display.py --preview

# full push
python display.py
```

## Troubleshooting

**`SyntaxError` on run**

Check file line endings are LF (not CRLF):

```bash
file display.py render.py quote0_usage.py
```

**`ModuleNotFoundError: No module named 'PIL'`**

```bash
pip install -r requirements.txt
```

**Image API push returns 404 "未找到图像 API 内容"**

1. Go to Dot. App → Content Studio
2. Remove all IMAGE_API cards from the device task
3. Re-add a single IMAGE_API card
4. Verify with `python display.py --list-tasks`

**Display doesn't update on schedule**

- Check launchd status: `launchctl list | grep quote0`
- If `runs = 0`, kickstart: `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`
- If cron is blocked by macOS TCC, grant Terminal / cron Full Disk Access in System Settings → Privacy & Security

**Codex shows "timeout" or "no codexbar"**

```bash
# Test CodexBar directly
codexbar usage --provider codex --format json --source cli
# If it hangs, try with --source cli (skips web dashboard)
```

**Run `--check` to diagnose issues**

```bash
python display.py --check
```
Shows: env vars, CodexBar status, DeepSeek balance, image rendering, and Quote/0 connectivity — all without pushing.

**Debug data structure**

```bash
python display.py --debug-json
```
Prints the full snapshot dict — useful for checking CodexBar parsing and status levels.
