#!/usr/bin/env python3
"""
quote0-burnout v0.3 — fetch usage, render image, push to Quote/0.

Usage:
  python display.py                 # Image API (default)
  python display.py --preview       # Save preview PNG, skip push
  python display.py --text          # Text API fallback (v0.1 compat)
  python display.py --check         # Self-check, no push
  python display.py --list-tasks    # List fixed + loop task slots
  python display.py --list-tasks fixed
  python display.py --list-tasks loop
"""

from __future__ import annotations

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

# ── Config (lazy — never crashes on missing env) ──────────────────────────────

_HERE = Path(__file__).parent

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

QUOTE0_API_KEY     = _env("QUOTE0_API_KEY")
QUOTE0_DEVICE_ID   = _env("QUOTE0_DEVICE_ID")
DEEPSEEK_API_KEY   = _env("DEEPSEEK_API_KEY")
CODEXBAR_BIN       = _env("CODEXBAR_BIN", "codexbar")
QUOTE0_REFRESH_NOW = _env("QUOTE0_REFRESH_NOW", "false").lower() == "true"

QUOTE0_IMAGE_TASK_KEY = _env("QUOTE0_IMAGE_TASK_KEY")
QUOTE0_TEXT_TASK_KEY  = _env("QUOTE0_TEXT_TASK_KEY")
QUOTE0_PREVIEW_PATH   = _env("QUOTE0_PREVIEW_PATH", "/tmp/quote0_burnout_preview.png")

API_BASE = "https://dot.mindreset.tech"

# ── Fetch ─────────────────────────────────────────────────────────────────────

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


# ── Normalize ─────────────────────────────────────────────────────────────────

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

    primary = usage.get("primary", {})
    pct = primary.get("usedPercent")
    resets = primary.get("resetsAt")

    secondary = usage.get("secondary", {})
    sec_pct = secondary.get("usedPercent")
    window_m = secondary.get("windowMinutes", 0)

    if pct is None:
        return "OK"

    parts = [f"{float(pct):.0f}%"]
    if resets:
        parts.append(_time_until(resets))
    if sec_pct is not None:
        if window_m >= 10080:
            parts.append(f"Wk {float(sec_pct):.0f}%")
        elif window_m >= 1440:
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


# ── Push ──────────────────────────────────────────────────────────────────────

def push_image(png_bytes: bytes) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/image"
    payload = {
        "refreshNow": QUOTE0_REFRESH_NOW,
        "image": base64.b64encode(png_bytes).decode(),
        "ditherType": "DIFFUSION",
        "ditherKernel": "FLOYD_STEINBERG",
        "border": 0,
    }
    if QUOTE0_IMAGE_TASK_KEY:
        payload["taskKey"] = QUOTE0_IMAGE_TASK_KEY
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
            body_resp = r.json()
        except Exception:
            body_resp = {"_raw": r.text}
        return {"ok": False, "status": r.status_code, "body": body_resp}
    return {"ok": True, "body": r.json()}


# ── Run (push) ────────────────────────────────────────────────────────────────

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

        if preview is True:
            Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
            print(f"Preview saved to {QUOTE0_PREVIEW_PATH}")
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


# ── Check ─────────────────────────────────────────────────────────────────────

def _status(label: str, ok: bool, detail: str = "") -> str:
    tag = "OK" if ok else "FAIL"
    suffix = f" {detail}" if detail else ""
    return f"  {label:<24} {tag}{suffix}"


def check() -> int:
    """Run self-check. Returns exit code (0=OK, 1=problems)."""
    print("quote0-burnout check\n")

    warnings = 0
    failures = 0

    # ── Environment ────────────────────────────────────────────────────────
    print("Environment:")

    env_vars = [
        ("QUOTE0_API_KEY",        QUOTE0_API_KEY,        True),
        ("QUOTE0_DEVICE_ID",      QUOTE0_DEVICE_ID,      True),
        ("QUOTE0_IMAGE_TASK_KEY", QUOTE0_IMAGE_TASK_KEY, False),
        ("QUOTE0_TEXT_TASK_KEY",  QUOTE0_TEXT_TASK_KEY,  False),
        ("DEEPSEEK_API_KEY",      DEEPSEEK_API_KEY,      False),
        ("CODEXBAR_BIN",          CODEXBAR_BIN,          False),
    ]

    for name, val, required in env_vars:
        if name == "CODEXBAR_BIN":
            print(_status(name, True, val))
        elif val:
            masked = val[:3] + "..." if len(val) > 6 else val
            print(_status(name, True, masked))
        elif required:
            print(_status(name, False, "missing"))
            failures += 1
        else:
            print(_status(name, True, "optional / missing"))

    print()

    # ── CodexBar ───────────────────────────────────────────────────────────
    print("CodexBar:")

    # Binary check
    binary_ok = False
    try:
        result = subprocess.run(
            [CODEXBAR_BIN, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            ver = result.stdout.strip().split()[-1] if result.stdout.strip() else "?"
            print(_status("binary", True, ver))
            binary_ok = True
        else:
            print(_status("binary", False, "exit code " + str(result.returncode)))
    except FileNotFoundError:
        print(_status("binary", False, "no codexbar found"))
    except subprocess.TimeoutExpired:
        print(_status("binary", False, "timeout"))
    except Exception as e:
        print(_status("binary", False, str(e)))

    # Usage check
    codex_ok = False
    codex_detail = ""
    if binary_ok:
        codex = get_codex_usage()
        if codex.get("ok"):
            codex_text = normalize_codex(codex)
            print(_status("usage", True, codex_text))
            codex_ok = True
            codex_detail = codex_text
        else:
            status = codex.get("status", "unknown")
            print(_status("usage", False, status))
    else:
        print(_status("usage", False, "binary not found"))

    print()

    # ── DeepSeek ───────────────────────────────────────────────────────────
    print("DeepSeek:")
    ds_ok = False
    ds_detail = ""
    if DEEPSEEK_API_KEY:
        ds = get_deepseek_balance()
        if ds.get("ok"):
            ds_detail = normalize_deepseek(ds)
            print(_status("balance", True, ds_detail))
            ds_ok = True
        else:
            status = ds.get("status", "unknown")
            print(_status("balance", False, status))
    else:
        print(_status("balance", False, "no API key"))

    print()

    # ── Render ─────────────────────────────────────────────────────────────
    print("Render:")
    render_ok = False
    if codex_ok or ds_ok:
        try:
            cx = codex_detail if codex_ok else "N/A"
            ds = ds_detail if ds_ok else "N/A"
            png = render_image(cx, ds)
            Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
            print(_status("image", True, QUOTE0_PREVIEW_PATH))
            render_ok = True
        except Exception as e:
            print(_status("image", False, str(e)))
            failures += 1
    else:
        print(_status("image", False, "no data to render"))

    print()

    # ── Quote/0 ────────────────────────────────────────────────────────────
    print("Quote/0:")
    if QUOTE0_API_KEY and QUOTE0_DEVICE_ID:
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/fixed/list",
                headers={"Authorization": f"Bearer {QUOTE0_API_KEY}"},
                timeout=10,
            )
            if r.ok:
                print(_status("endpoint", True, f"HTTP {r.status_code}"))
            else:
                print(_status("endpoint", False, f"HTTP {r.status_code}"))
        except Exception as e:
            print(_status("endpoint", False, str(e)))
            failures += 1

        refresh_label = "true" if QUOTE0_REFRESH_NOW else "false"
        print(_status("refreshNow", True, refresh_label))
    else:
        print(_status("endpoint", False, "QUOTE0_API_KEY or QUOTE0_DEVICE_ID missing"))
        failures += 1

    print()

    # ── Result ─────────────────────────────────────────────────────────────
    print("Result:")

    if not codex_ok:
        warnings += 1
    if not ds_ok:
        warnings += 1

    if failures == 0 and warnings == 0:
        print("  OK")
        return 0
    elif failures == 0 and warnings > 0:
        print(f"  WARNING ({warnings} non-critical issue(s))")
        # WARNING: Codex fail + DeepSeek OK → 0; DeepSeek fail + Codex OK → 0
        # Both fail → 1
        if not codex_ok and not ds_ok:
            return 1
        return 0
    else:
        print(f"  FAIL ({failures} error(s), {warnings} warning(s))")
        return 1


# ── List tasks ────────────────────────────────────────────────────────────────

def list_tasks(task_type: str = "") -> int:
    """List Quote/0 task slots. task_type: '', 'fixed', 'loop'."""

    if not QUOTE0_API_KEY or not QUOTE0_DEVICE_ID:
        print("Error: QUOTE0_API_KEY and QUOTE0_DEVICE_ID are required", file=sys.stderr)
        return 1

    types = [task_type] if task_type else ["fixed", "loop"]

    for tt in types:
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/{tt}/list",
                headers={"Authorization": f"Bearer {QUOTE0_API_KEY}"},
                timeout=10,
            )
            if not r.ok:
                print(f"{tt}:  HTTP {r.status_code}", file=sys.stderr)
                try:
                    body = r.json()
                    print(json.dumps(body, ensure_ascii=False, indent=2), file=sys.stderr)
                except Exception:
                    print(r.text, file=sys.stderr)
                continue

            data = r.json()
            if not isinstance(data, list):
                print(f"{tt}:  unexpected response (not a list):")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                continue

            print(f"{tt}:")
            if not data:
                print("  (empty)")
                continue

            for task in data:
                if not isinstance(task, dict):
                    print(f"  {task}")
                    continue
                t = task.get("type", "?")
                k = task.get("key", "?")
                # Try title first, then name
                title = task.get("title", task.get("name", ""))
                line = f"  {t:<12} {k}"
                if title:
                    line += f"  {title}"
                print(line)

        except Exception as e:
            print(f"{tt}:  error — {e}", file=sys.stderr)

        if task_type:
            continue
        # blank line between fixed & loop
        if tt == "fixed" and "loop" in types:
            print()

    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Push AI usage to Quote/0 display"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help=f"Save preview PNG to {QUOTE0_PREVIEW_PATH} and skip push"
    )
    parser.add_argument(
        "--text", action="store_true",
        help="Use Text API instead of Image API (v0.1 compat)"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Run self-check — tests env, deps, data, render, endpoints (no push)"
    )
    parser.add_argument(
        "--list-tasks", nargs="?", const="", metavar="TYPE",
        help="List task slots: no arg = fixed+loop, 'fixed', 'loop'"
    )
    args = parser.parse_args()

    # ── --check ────────────────────────────────────────────────────────────
    if args.check:
        rc = check()
        sys.exit(rc)

    # ── --list-tasks ───────────────────────────────────────────────────────
    if args.list_tasks is not None:
        rc = list_tasks(args.list_tasks)
        sys.exit(rc)

    # ── default / --preview / --text ───────────────────────────────────────
    success = run(preview=args.preview, text_mode=args.text)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
