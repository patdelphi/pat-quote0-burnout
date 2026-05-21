#!/usr/bin/env python3
"""
quote0-burnout display entrypoint — fetch usage, render image, push to Quote/0.

Usage:
  python display.py              # Image API (default)
  python display.py --preview    # Save preview PNG, then push
  python display.py --text       # Use Text API (v0.1 compat)
  python display.py --text --preview   # Text mode + no push (preview only)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from render import render_image

# ── Config ───────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent

QUOTE0_API_KEY = os.environ["QUOTE0_API_KEY"]
QUOTE0_DEVICE_ID = os.environ["QUOTE0_DEVICE_ID"]
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
CODEXBAR_BIN = os.environ.get("CODEXBAR_BIN", "codexbar")

API_BASE = "https://dot.mindreset.tech"


# ── Fetch ────────────────────────────────────────────────────────────────────

def get_codex_usage():
    try:
        raw = subprocess.check_output(
            [CODEXBAR_BIN, "usage", "--provider", "codex", "--format", "json"],
            text=True,
            timeout=20,
        )
        try:
            data = json.loads(raw)
        except Exception:
            return {"ok": False, "status": "parse error"}

        entry = data[0] if isinstance(data, list) and data else data
        return {"ok": True, "raw": entry}

    except FileNotFoundError:
        return {"ok": False, "status": "no codexbar"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout"}
    except Exception:
        return {"ok": False, "status": "login?"}


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

def _time_until(iso_str: str | None) -> str:
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return "?"
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "now"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def normalize_codex(codex):
    if not codex.get("ok"):
        return codex.get("status", "unknown")

    raw = codex.get("raw", {})
    usage = raw.get("usage", {}) if isinstance(raw, dict) else {}

    # Primary (short window)
    primary = usage.get("primary", {})
    pct = primary.get("usedPercent")
    resets = primary.get("resetsAt")

    # Secondary (long window)
    secondary = usage.get("secondary", {})
    sec_pct = secondary.get("usedPercent")
    window_m = secondary.get("windowMinutes", 0)

    if pct is None:
        return "OK"

    parts = [f"{float(pct):.0f}%"]
    if resets:
        parts.append(_time_until(resets))
    if sec_pct is not None:
        # Only show secondary if window is large (week+)
        if window_m >= 10080:  # week
            parts.append(f"Wk {float(sec_pct):.0f}%")
        elif window_m >= 1440:  # day+
            parts.append(f"{float(sec_pct):.0f}%")

    return " · ".join(parts)


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


# ── Push ─────────────────────────────────────────────────────────────────────

def push_image(png_bytes: bytes) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/image"
    payload = {
        "refreshNow": True,
        "image": base64.b64encode(png_bytes).decode(),
        "ditherType": "NONE",
    }
    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {QUOTE0_API_KEY}"},
        timeout=20,
    )
    if not r.ok:
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body}
    return {"ok": True, "body": r.json()}


def push_text(payload: dict) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/text"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {QUOTE0_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"refreshNow": True, **payload},
        timeout=20,
    )
    if not r.ok:
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body}
    return {"ok": True, "body": r.json()}


# ── Main ─────────────────────────────────────────────────────────────────────

def run(preview: bool = False, text_mode: bool = False) -> bool:
    codex = get_codex_usage()
    deepseek = get_deepseek_balance()

    codex_text = normalize_codex(codex)
    deepseek_text = normalize_deepseek(deepseek)

    print(f"Codex:     {codex_text}")
    print(f"DeepSeek:  {deepseek_text}")

    if text_mode:
        now = datetime.now().strftime("%H:%M")
        payload = {
            "title": "AI Usage",
            "message": f"Codex     {codex_text}\nDeepSeek  {deepseek_text}",
            "signature": now,
        }
        result = push_text(payload)
    else:
        png = render_image(codex_text, deepseek_text)

        if preview or preview is None:
            preview_path = "/tmp/quote0_burnout_preview.png"
            Path(preview_path).write_bytes(png)
            print(f"Preview saved to {preview_path}")

        if preview is True and not text_mode:
            print("--preview only, skipping push")
            return True

        result = push_image(png)

    output = {
        "ok": result.get("ok"),
        "status": result.get("status"),
    }
    body = result.get("body", {})
    if isinstance(body, dict):
        output["message"] = body.get("message", "")
    else:
        output["message"] = str(body)

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        msg = output.get("message", "unknown error")
        print(f"\n⚠️  Push failed (HTTP {result.get('status')}): {msg}", file=sys.stderr)
        return False

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Push AI usage to Quote/0 display"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Save preview PNG to /tmp/quote0_burnout_preview.png and skip push"
    )
    parser.add_argument(
        "--text", action="store_true",
        help="Use Text API instead of Image API (v0.1 compat)"
    )
    args = parser.parse_args()

    success = run(preview=args.preview, text_mode=args.text)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
