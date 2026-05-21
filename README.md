# quote0-burnout

Minimal AI usage display for MindReset Quote/0. Shows Codex and DeepSeek status.

## Install

```bash
pip install requests
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
| `DEEPSEEK_API_KEY` | No | DeepSeek API key |
| `CODEXBAR_BIN` | No | Path to CodexBar CLI (default: `codexbar`) |

## Run

```bash
python quote0_usage.py
```

## Schedule

**cron** (every 10 min):
```
*/10 * * * * /bin/bash /path/to/quote0-burnout/run.sh >> /tmp/quote0-burnout.log 2>&1
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

# test script
python quote0_usage.py
```

## Success

After first run, Quote/0 shows:

```
AI Usage

Codex     OK
DeepSeek  $18.42

15:36
```
