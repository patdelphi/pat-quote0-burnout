#!/usr/bin/env python3
"""
quote0-burnout v0.6 — AI 额度数据获取与快照构建模块。

本模块负责从 Codex（OpenAI）和 DeepSeek 获取实时用量/余额数据，
并构建结构化的 snapshot 字典，供本地弹窗（local_app.py）或墨水屏推送使用。

对外接口：
  build_snapshot() -> dict   # 获取完整数据快照
  get_codex_usage() -> dict  # 仅获取 Codex 原始数据
  get_deepseek_balance() -> dict  # 仅获取 DeepSeek 原始数据
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config（延迟加载，缺失不会崩溃）───────────────────────────────────────────

_HERE = Path(__file__).parent

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

DEEPSEEK_API_KEY   = _env("DEEPSEEK_API_KEY")

# ── 状态判断辅助函数 ──────────────────────────────────────────────────────────

def _pct_status(pct: int | None) -> str:
    """Codex 已用百分比 → ok / warn / hot / unknown。"""
    if pct is None:
        return "unknown"
    if pct >= 90:
        return "hot"
    if pct >= 70:
        return "warn"
    return "ok"


def _balance_status(balance: float | None, is_available: bool | None) -> str:
    """DeepSeek 余额 → ok / warn / hot / unknown / error。"""
    if balance is None:
        return "unknown"
    if is_available is False:
        return "hot"
    if balance < 3:
        return "hot"
    if balance < 10:
        return "warn"
    return "ok"


def _window_label(minutes: int | None) -> str:
    """窗口分钟数 → 人类可读标签。"""
    if minutes is None:
        return "Now"
    if minutes <= 360:
        return "5h"
    if minutes <= 1440:
        return "Day"
    if minutes >= 10080:
        return "Week"
    return "Now"


# ── 数据获取 ──────────────────────────────────────────────────────────────────

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def _load_codex_token():
    """返回 (access_token, account_id)。环境变量优先于 auth.json。"""
    env_token = os.environ.get("CODEX_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token, os.environ.get("CODEX_ACCOUNT_ID", "").strip()

    if not CODEX_AUTH_PATH.exists():
        raise FileNotFoundError(
            f"未找到 Codex 认证文件：{CODEX_AUTH_PATH}。"
            "请先运行 `codex` 完成认证，或在 .env 中设置 CODEX_ACCESS_TOKEN。"
        )
    with open(CODEX_AUTH_PATH, encoding="utf-8") as f:
        auth = json.load(f)
    tokens = auth.get("tokens", {})
    return tokens.get("access_token", ""), tokens.get("account_id", "")


def get_codex_usage():
    """通过直连 API 获取 OpenAI Codex 用量（不依赖 codexbar CLI）。"""
    try:
        access_token, account_id = _load_codex_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "quote0-burnout",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        r = requests.get(CODEX_USAGE_URL, headers=headers, timeout=15)
        r.raise_for_status()
        return {"ok": True, "raw": r.json()}

    except FileNotFoundError as e:
        return {"ok": False, "status": "no auth", "detail": str(e)}
    except requests.Timeout:
        return {"ok": False, "status": "timeout"}
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.text[:200]
        except Exception:
            pass
        return {"ok": False, "status": f"HTTP {e.response.status_code}", "detail": detail}
    except Exception as e:
        return {"ok": False, "status": "error", "detail": str(e)[:200]}


def get_deepseek_balance():
    """获取 DeepSeek 账户余额。"""
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


# ── 快照构建 ──────────────────────────────────────────────────────────────────

CURRENCY_SYMBOLS = {"USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£"}


def _time_until(val) -> str:
    """从 ISO 字符串或 Unix 时间戳格式化为本地重置时间。"""
    if val is None:
        return "?"
    try:
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return "?"
    # 转为本地时间
    dt_local = dt.astimezone()
    now_local = datetime.now().astimezone()
    if dt_local.date() == now_local.date():
        return dt_local.strftime("%H:%M")
    return dt_local.strftime("%m/%d %H:%M")


def build_codex_snapshot(codex: dict) -> dict:
    """从 wham API 响应构建结构化的 Codex 快照。"""
    if not codex.get("ok"):
        status = codex.get("status", "error")
        return {
            "ok": False,
            "short_label": "?",
            "short_used_percent": None,
            "short_reset": "?",
            "long_label": "?",
            "long_used_percent": None,
            "status": "error",
            "raw_status": status,
        }

    raw = codex.get("raw", {})
    rate_limit = raw.get("rate_limit", {})

    primary = rate_limit.get("primary_window", {})
    secondary = rate_limit.get("secondary_window", {})

    short_pct = primary.get("used_percent")
    short_reset_ts = primary.get("reset_at")

    long_pct = secondary.get("used_percent")
    long_reset_ts = secondary.get("reset_at")

    # API 返回 float，归一化为 int
    try:
        short_pct = int(float(short_pct)) if short_pct is not None else None
    except (ValueError, TypeError):
        short_pct = None
    try:
        long_pct = int(float(long_pct)) if long_pct is not None else None
    except (ValueError, TypeError):
        long_pct = None

    return {
        "ok": True,
        "short_label": "5h",
        "short_used_percent": short_pct,
        "short_reset": _time_until(short_reset_ts) if short_reset_ts else "?",
        "long_label": "Wk",
        "long_used_percent": long_pct,
        "long_reset": _time_until(long_reset_ts) if long_reset_ts else "?",
        "status": _pct_status(short_pct),
        "raw_status": "",
    }


def build_deepseek_snapshot(ds: dict) -> dict:
    """从 balance API 响应构建结构化的 DeepSeek 快照。"""
    if not ds.get("ok"):
        status = ds.get("status", "error")
        return {
            "ok": False,
            "balance": None,
            "currency": "?",
            "symbol": "?",
            "status": "error",
            "raw_status": status,
        }

    amount = ds.get("amount")
    try:
        amount = float(amount) if amount is not None else None
    except (ValueError, TypeError):
        amount = None

    currency = ds.get("currency", "USD")
    available = ds.get("available")

    return {
        "ok": True,
        "balance": amount,
        "currency": currency,
        "symbol": CURRENCY_SYMBOLS.get(currency, "$"),
        "status": _balance_status(amount, available),
        "raw_status": "",
    }


def build_snapshot() -> dict:
    """获取并构建完整数据快照。"""
    codex = get_codex_usage()
    deepseek = get_deepseek_balance()
    return {
        "codex": build_codex_snapshot(codex),
        "deepseek": build_deepseek_snapshot(deepseek),
        "updated_at": datetime.now().strftime("%H:%M"),
    }


# ── 文本格式化（供调试或命令行使用）─────────────────────────────────────────────

def format_codex_text(sn: dict) -> str:
    """将 Codex 快照格式化为文本。"""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")

    pct = sn.get("short_used_percent")
    pct_str = f"{pct}%" if pct is not None else "?"
    reset = sn.get("short_reset", "?")

    line = f"{sn['short_label']} {pct_str} reset {reset}"

    long_pct = sn.get("long_used_percent")
    if long_pct is not None:
        line += f"\n{sn['long_label']} {long_pct}%"

    return line


def format_deepseek_text(sn: dict) -> str:
    """将 DeepSeek 快照格式化为文本。"""
    if not sn.get("ok"):
        return sn.get("raw_status", "error")

    bal = sn.get("balance")
    if bal is None:
        return "unknown"

    return f"{sn['symbol']}{bal:.2f} {sn['status'].upper()}"


# ── 命令行入口（调试/自检）─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI 额度数据获取与快照构建")
    parser.add_argument("--debug-json", action="store_true", help="打印快照 JSON，不推送")
    args = parser.parse_args()

    if args.debug_json:
        snapshot = build_snapshot()
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
