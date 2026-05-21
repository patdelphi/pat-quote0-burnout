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
| `QUOTE0_IMAGE_TASK_KEY` | * | taskKey for Image API content slot |
| `QUOTE0_TEXT_TASK_KEY` | * | taskKey for Text API content slot |
| `QUOTE0_REFRESH_NOW` | No | Force immediate display (default: `false`; set `true` for manual push) |
| `DEEPSEEK_API_KEY` | No | DeepSeek API key |
| `CODEXBAR_BIN` | No | Path to CodexBar CLI (default: `codexbar`) |

\\* *Required when multiple API content slots exist (e.g. fixed + loop). Find keys with:*

```bash
# List fixed content slots
curl -H "Authorization: Bearer $QUOTE0_API_KEY" \
  "https://dot.mindreset.tech/api/authV2/open/device/$QUOTE0_DEVICE_ID/fixed/list"

# List loop content slots
curl -H "Authorization: Bearer $QUOTE0_API_KEY" \
  "https://dot.mindreset.tech/api/authV2/open/device/$QUOTE0_DEVICE_ID/loop/list"
```

Look for `"type": "IMAGE_API"` or `"type": "TEXT_API"` entries and copy their `"key"`.

### Dot. App setup

In Content Studio, add **Image API content** to the device task for Image mode,
or **Text API content** for `--text` fallback.

**Fixed content mode:** if you placed the API content in a Fixed Content slot (not Loop), set `QUOTE0_REFRESH_NOW=false` so the device's schedule controls when to display it. The API only updates the slot's data.

## Usage

```bash
python display.py              # Image API (default, 296×152 PNG)
python display.py --preview    # Save PNG to /tmp/ without pushing
python display.py --text       # Text API fallback (v0.1 compat)
python quote0_usage.py         # Standalone Text API (v0.1)
```

## Schedule

**cron** (every 5 min):
```
*/5 * * * * /bin/bash /path/to/quote0-burnout/run.sh >> /tmp/quote0-burnout.log 2>&1
```

**macOS launchd** — copy `com.ajax.quote0-burnout.plist.example` to `~/Library/LaunchAgents/`, edit the `Program` path to match your checkout, then:
```bash
launchctl load ~/Library/LaunchAgents/com.ajax.quote0-burnout.plist
```

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
