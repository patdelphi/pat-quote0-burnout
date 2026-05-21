# quote0-usage

Minimal AI usage display for MindReset Quote/0. Shows Codex and DeepSeek status.

## Install

```bash
pip install requests
# CodexBar must also be installed and working:
codexbar --provider codex --format json
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
*/10 * * * * /usr/bin/python3 /path/to/quote0_usage.py >> /tmp/quote0-usage.log 2>&1
```

**macOS launchd** — TBD.

## Success

After first run, Quote/0 shows:

```
AI Usage

Codex     OK
DeepSeek  $18.42

15:36
```
