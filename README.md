# quote0-burnout

Minimal AI usage display for MindReset Quote/0 — Codex + DeepSeek on e-ink.

v0.2 renders a 296×152 B&W PNG and pushes via Quote/0 Image API.

## Install

```bash
pip install -r requirements.txt
# CodexBar must also be installed and working:
codexbar usage --provider codex --format json
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
| `QUOTE0_REFRESH_NOW` | No | Force immediate display (default: `true`) |
| `DEEPSEEK_API_KEY` | No | DeepSeek API key |
| `CODEXBAR_BIN` | No | Path to CodexBar CLI (default: `codexbar`) |

### Dot. App setup

In Content Studio, add a single **Image API content** card to the device task.
Keep only one IMAGE_API card — the script pushes without `taskKey` and targets
the sole slot automatically.

## Usage

```bash
python display.py              # Image API (default, 296×152 PNG)
python display.py --preview    # Save PNG to /tmp/ without pushing
python display.py --text       # Text API fallback (v0.1 compat)
python quote0_usage.py         # Standalone Text API (v0.1)
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
codexbar usage --provider codex --format json | python3 -m json.tool > /dev/null \
  && echo "CodexBar OK" || echo "CodexBar FAIL"

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
4. Ensure only one IMAGE_API card exists (no duplicates in loop + fixed)

**Display doesn't update on schedule**

- Check launchd status: `launchctl list | grep quote0`
- If `runs = 0`, kickstart: `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`
- If cron is blocked by macOS TCC, grant Terminal / cron Full Disk Access in System Settings → Privacy & Security
