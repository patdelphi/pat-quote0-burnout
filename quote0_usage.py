#!/usr/bin/env python3
"""
MindReset Quote/0 usage display — minimal status snapshot renderer.

Data sources:
  - Codex   → CodexBar CLI (external)
  - DeepSeek → official balance API
  - Quote/0 → Text API

First version: text-only, no image rendering.
"""

import json
import os
import subprocess
import sys
from datetime import datetime

import requests

# ── config from env ──────────────────────────────────────────────────────────

QUOTE0_API_KEY = os.environ["QUOTE0_API_KEY"]
QUOTE0_DEVICE_ID = os.environ["QUOTE0_DEVICE_ID"]
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
CODEXBAR_BIN = os.environ.get("CODEXBAR_BIN", "codexbar")

QUOTE0_TEXT_TASK_KEY = os.environ.get("QUOTE0_TEXT_TASK_KEY", "")
QUOTE0_REFRESH_NOW = os.environ.get("QUOTE0_REFRESH_NOW", "false").lower() == "true"


# ── Codex ────────────────────────────────────────────────────────────────────

def get_codex_usage():
    try:
        raw = subprocess.check_output(
            [CODEXBAR_BIN, "usage", "--provider", "codex", "--format", "json", "--source", "cli"],
            text=True,
            timeout=20,
        )
        try:
            data = json.loads(raw)
        except Exception:
            return {"ok": False, "status": "parse error"}

        # codexbar returns an array; pick the first matching entry
        entry = data[0] if isinstance(data, list) and data else data
        return {"ok": True, "raw": entry}

    except FileNotFoundError:
        return {"ok": False, "status": "no codexbar"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout"}
    except Exception:
        return {"ok": False, "status": "login?"}


# ── DeepSeek ─────────────────────────────────────────────────────────────────

def get_deepseek_balance():
    if not DEEPSEEK_API_KEY:
        return {"ok": False, "status": "no key"}

    try:
        r = requests.get(
            "https://api.deepseek.com/user/balance",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Accept": "application/json",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        infos = data.get("balance_infos", [])
        usd = next(
            (x for x in infos if x.get("currency") == "USD"),
            infos[0] if infos else None,
        )

        if not usd:
            return {"ok": False, "status": "no balance"}

        return {
            "ok": True,
            "amount": usd.get("total_balance"),
            "currency": usd.get("currency", "USD"),
            "available": data.get("is_available"),
            "raw": data,
        }

    except Exception:
        return {"ok": False, "status": "error"}


# ── Normalize ────────────────────────────────────────────────────────────────

def normalize_codex(codex):
    if not codex.get("ok"):
        return codex.get("status", "unknown")

    raw = codex.get("raw", {})

    # codexbar nests under usage.primary.usedPercent / usage.secondary.usedPercent
    usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
    percent = (
        raw.get("percent")
        or raw.get("usage_percent")
        or raw.get("remaining_percent")
    )

    if percent is None:
        for tier in ("primary", "secondary"):
            tier_data = usage.get(tier, {})
            pct = tier_data.get("usedPercent")
            if pct is not None:
                percent = pct
                break

    if percent is None:
        return "OK"

    try:
        return f"{float(percent):.0f}%"
    except Exception:
        return "OK"


def normalize_deepseek(ds):
    if not ds.get("ok"):
        return ds.get("status", "unknown")

    amount = ds.get("amount")
    if amount is None:
        return "unknown"

    symbol = {"CNY": "¥", "USD": "$", "EUR": "€"}.get(
        ds.get("currency", ""), "$"
    )

    try:
        return f"{symbol}{float(amount):.2f}"
    except Exception:
        return str(amount)


# ── Render ───────────────────────────────────────────────────────────────────

def render_text(codex_text, deepseek_text):
    now = datetime.now().strftime("%H:%M")
    return {
        "title": "AI Usage",
        "message": f"Codex     {codex_text}\nDeepSeek  {deepseek_text}",
        "signature": now,
    }


# ── Push to Quote/0 ──────────────────────────────────────────────────────────

def push_quote0(payload):
    url = (
        f"https://dot.mindreset.tech/api/authV2/open/device/"
        f"{QUOTE0_DEVICE_ID}/text"
    )
    body = {"refreshNow": QUOTE0_REFRESH_NOW, **payload}
    if QUOTE0_TEXT_TASK_KEY:
        body["taskKey"] = QUOTE0_TEXT_TASK_KEY
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {QUOTE0_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=20,
    )
    if not r.ok:
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body}
    return {"ok": True, "body": r.json()}


def main():
    codex = get_codex_usage()
    deepseek = get_deepseek_balance()

    codex_text = normalize_codex(codex)
    deepseek_text = normalize_deepseek(deepseek)

    payload = render_text(codex_text, deepseek_text)
    result = push_quote0(payload)

    output = {
        "payload": payload,
        "result": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        body = result.get("body", {})
        if isinstance(body, dict):
            msg = body.get("message", str(body))
        else:
            msg = str(body)
        print(f"\n⚠️  Push failed (HTTP {result.get('status')}): {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
