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
import queue
import shutil
import subprocess
import threading
import time
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
        return "Wk"
    return "Now"


# ── 数据获取 ──────────────────────────────────────────────────────────────────

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
CODEX_LEGACY_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_APP_SERVER_TIMEOUT = 20


def _find_codex_command():
    """查找 Codex CLI；CODEX_COMMAND 可用于指定自定义可执行文件路径。"""
    configured = os.environ.get("CODEX_COMMAND", "").strip()
    if configured:
        return configured

    # Windows 下 shutil.which 会自动处理 .cmd/.exe，macOS/Linux 则直接查找 codex。
    for candidate in ("codex", "codex.cmd", "codex.exe"):
        command = shutil.which(candidate)
        if command:
            return command
    return None


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


def _send_app_server_message(process, message: dict):
    """向 Codex app-server 写入一条 JSON-RPC 消息。"""
    if process.stdin is None:
        raise RuntimeError("Codex app-server stdin 不可用")
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _read_app_server_response(messages, request_id: int, timeout: float):
    """从 app-server 异步输出中读取指定 request id 的响应，忽略通知消息。"""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"等待 Codex app-server 响应超时：{request_id}")
        try:
            message = messages.get(timeout=remaining)
        except queue.Empty as e:
            raise TimeoutError(f"等待 Codex app-server 响应超时：{request_id}") from e

        if message is None:
            raise RuntimeError("Codex app-server 已提前退出")
        if message.get("id") != request_id:
            continue
        if "error" in message:
            error = message.get("error") or {}
            raise RuntimeError(error.get("message", "Codex app-server 返回错误"))
        if "result" not in message:
            raise RuntimeError("Codex app-server 响应缺少 result")
        return message["result"]


def _get_codex_usage_app_server():
    """通过 Codex CLI 的受支持 app-server 协议获取额度。"""
    command = _find_codex_command()
    if not command:
        raise FileNotFoundError("未找到 Codex CLI，请设置 CODEX_COMMAND 或将 codex 加入 PATH")

    process = None
    messages = queue.Queue()
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [command, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )

        def read_messages():
            """持续读取 stdout，避免 Windows 下 readline 阻塞主线程。"""
            if process.stdout is None:
                messages.put(None)
                return
            for line in process.stdout:
                try:
                    message = json.loads(line)
                    if isinstance(message, dict):
                        messages.put(message)
                except json.JSONDecodeError:
                    # app-server 只应输出 JSON；遇到版本噪声时继续等待正式响应。
                    continue
            messages.put(None)

        threading.Thread(target=read_messages, daemon=True).start()

        # app-server 的额度接口属于 experimental API，需要在握手时显式声明能力。
        _send_app_server_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "quote0-burnout", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        _read_app_server_response(messages, 1, CODEX_APP_SERVER_TIMEOUT)
        _send_app_server_message(process, {"method": "initialized"})
        _send_app_server_message(
            process,
            {"id": 2, "method": "account/rateLimits/read"},
        )
        return _read_app_server_response(messages, 2, CODEX_APP_SERVER_TIMEOUT)
    finally:
        if process is not None:
            # EOF 让 app-server 优雅退出；只有未退出时才强制结束当前子进程。
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _get_codex_usage_http():
    """使用 OAuth HTTP 接口作为旧版 CLI 或小组件场景的兼容回退。"""
    access_token, account_id = _load_codex_token()
    if not access_token:
        raise FileNotFoundError("Codex 认证文件中没有 access_token")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "quote0-burnout",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    for index, url in enumerate((CODEX_USAGE_URL, CODEX_LEGACY_USAGE_URL)):
        r = requests.get(url, headers=headers, timeout=15)
        try:
            r.raise_for_status()
        except requests.HTTPError:
            # 新路径不存在时兼容旧版服务端；其他 HTTP 错误直接交给上层显示。
            if r.status_code == 404 and index == 0:
                continue
            raise
        return r.json()
    raise RuntimeError("Codex HTTP 接口均不可用")


def get_codex_usage():
    """获取 Codex 用量：优先 app-server，失败后回退 OAuth HTTP 接口。"""
    try:
        return {"ok": True, "raw": _get_codex_usage_app_server(), "source": "app-server"}
    except Exception as app_server_error:
        try:
            return {"ok": True, "raw": _get_codex_usage_http(), "source": "http-fallback"}
        except FileNotFoundError as e:
            return {
                "ok": False,
                "status": "no auth",
                "detail": str(e),
                "app_server_detail": str(app_server_error)[:200],
            }
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


ANTIGRAVITY_COMMAND_TIMEOUT = 20


def _find_agy_command():
    """查找 Antigravity CLI；ANTIGRAVITY_COMMAND 可用于指定自定义可执行文件路径。"""
    configured = os.environ.get("ANTIGRAVITY_COMMAND", "").strip()
    if configured:
        return configured

    for candidate in ("agy", "agy.exe", "agy.cmd"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def get_antigravity_usage():
    """通过 `agy -p /usage --output-format json` 获取 Antigravity 额度。"""
    command = _find_agy_command()
    if not command:
        return {"ok": False, "status": "no cli", "detail": "未找到 agy CLI"}

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [command, "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ANTIGRAVITY_COMMAND_TIMEOUT,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout"}
    except Exception as e:
        return {"ok": False, "status": "error", "detail": str(e)[:200]}

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        return {"ok": False, "status": "error", "detail": detail[:200]}

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {"ok": False, "status": "invalid json", "detail": str(e)[:200]}

    if not isinstance(data, dict) or data.get("status") != "SUCCESS":
        status = data.get("status") if isinstance(data, dict) else "invalid response"
        return {"ok": False, "status": str(status or "error")}

    return {"ok": True, "raw": data, "source": "cli"}


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


def _first_value(mapping: dict, *keys):
    """从兼容字段名中取第一个非空值，保留数值 0。"""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _parse_reset_credits(raw: dict) -> dict:
    """提取重置卡数量和可安全展示的卡片信息，不保留卡片 ID。"""
    payload = raw.get("rateLimitResetCredits")
    if not isinstance(payload, dict):
        payload = raw.get("rate_limit_reset_credits")
    if not isinstance(payload, dict):
        return {"available_count": None, "credits": []}

    available_count = _first_value(payload, "availableCount", "available_count")
    try:
        available_count = max(0, int(float(available_count)))
    except (TypeError, ValueError):
        available_count = None

    cards = []
    raw_cards = payload.get("credits")
    if isinstance(raw_cards, list):
        for raw_card in raw_cards:
            if not isinstance(raw_card, dict):
                continue
            if raw_card.get("status") not in (None, "available"):
                continue

            card = {}
            title = _first_value(raw_card, "title")
            if title:
                card["title"] = str(title)
            granted_at = _first_value(raw_card, "grantedAt", "granted_at")
            if granted_at is not None:
                card["granted_at"] = _time_until(granted_at)
            expires_at = _first_value(raw_card, "expiresAt", "expires_at")
            if expires_at is not None:
                card["expires_at"] = _time_until(expires_at)
            cards.append(card)

    # availableCount 是服务端权威总数，详情数组可能被服务端截断。
    if available_count is None:
        available_count = len(cards)
    return {"available_count": available_count, "credits": cards}


def format_reset_credits(reset_credits: dict, compact: bool = False) -> str:
    """将重置卡信息格式化为桌面/墨水屏可直接显示的文本。"""
    if not isinstance(reset_credits, dict):
        return ""
    count = reset_credits.get("available_count")
    if count is None:
        return ""

    try:
        count = max(0, int(count))
    except (TypeError, ValueError):
        return ""

    text = f"Reset {count}" if compact else f"重置卡 {count}张"
    if count > 0:
        cards = reset_credits.get("credits") or []
        expiry = next(
            (card.get("expires_at") for card in cards if card.get("expires_at")),
            None,
        )
        if expiry:
            text += f"  exp {expiry}" if compact else f" / 到期 {expiry}"
    return text


def build_codex_snapshot(codex: dict) -> dict:
    """兼容 app-server 与旧 HTTP 响应，构建结构化的 Codex 快照。"""
    if not codex.get("ok"):
        status = codex.get("status", "error")
        return {
            "ok": False,
            "short_label": "?",
            "short_used_percent": None,
            "short_reset": "?",
            "long_label": "?",
            "long_used_percent": None,
            "long_reset": "?",
            "reset_credits": {"available_count": None, "credits": []},
            "status": "error",
            "raw_status": status,
        }

    raw = codex.get("raw", {})
    if not isinstance(raw, dict):
        return {
            "ok": False,
            "short_label": "?",
            "short_used_percent": None,
            "short_reset": "?",
            "long_label": "?",
            "long_used_percent": None,
            "long_reset": "?",
            "reset_credits": {"available_count": None, "credits": []},
            "status": "error",
            "raw_status": "invalid response",
        }
    if isinstance(raw.get("result"), dict):
        # 允许调用方直接传入完整 JSON-RPC 响应，便于诊断和测试。
        raw = raw["result"]

    rate_limits = raw.get("rateLimits")
    if isinstance(rate_limits, dict):
        # 新 app-server：camelCase 字段、primary/secondary 窗口。
        primary = rate_limits.get("primary") or {}
        secondary = rate_limits.get("secondary") or {}
        short_pct = primary.get("usedPercent")
        short_reset_ts = primary.get("resetsAt")
        long_pct = secondary.get("usedPercent")
        long_reset_ts = secondary.get("resetsAt")
        short_label = (
            _window_label(primary.get("windowDurationMins"))
            if primary.get("windowDurationMins") is not None
            else "5h"
        )
        long_label = (
            _window_label(secondary.get("windowDurationMins"))
            if secondary.get("windowDurationMins") is not None
            else "Wk"
        )
    else:
        # 旧 HTTP：snake_case 字段、primary_window/secondary_window 窗口。
        rate_limit = raw.get("rate_limit", {})
        primary = rate_limit.get("primary_window", {})
        secondary = rate_limit.get("secondary_window", {})
        short_pct = primary.get("used_percent")
        short_reset_ts = primary.get("reset_at")
        long_pct = secondary.get("used_percent")
        long_reset_ts = secondary.get("reset_at")
        short_label = "5h"
        long_label = "Wk"

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
        "short_label": short_label,
        "short_used_percent": short_pct,
        "short_reset": _time_until(short_reset_ts) if short_reset_ts is not None else "?",
        "long_label": long_label,
        "long_used_percent": long_pct,
        "long_reset": _time_until(long_reset_ts) if long_reset_ts is not None else "?",
        "reset_credits": _parse_reset_credits(raw),
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


def _match_antigravity_group(groups: list, keyword: str) -> dict:
    """按关键字匹配 Antigravity 模型分组（忽略大小写）。"""
    for group in groups:
        if isinstance(group, dict) and keyword in str(group.get("name", "")).lower():
            return group
    return {}


def _build_antigravity_row(key: str, label: str, bucket: dict) -> dict:
    """将单个 Antigravity 额度窗口转换为统一展示行。"""
    frac = bucket.get("remaining_fraction")
    remaining_pct = None
    used_pct = None
    if frac is not None:
        try:
            remaining_pct = max(0, min(100, round(float(frac) * 100)))
            used_pct = 100 - remaining_pct
        except (ValueError, TypeError):
            remaining_pct = None
            used_pct = None

    return {
        "key": key,
        "label": label,
        "remaining_percent": remaining_pct,
        "used_percent": used_pct,
        "reset": _time_until(bucket.get("reset_time")),
        "status": _pct_status(used_pct),
    }


def build_antigravity_snapshot(agy: dict) -> dict:
    """从 `agy -p /usage --output-format json` 响应构建 Antigravity 快照。"""
    if not agy.get("ok"):
        return {
            "ok": False,
            "rows": [],
            "status": "error",
            "raw_status": agy.get("status", "error"),
        }

    raw = agy.get("raw", {})
    groups = (
        raw.get("command", {}).get("data", {}).get("groups", [])
        if isinstance(raw, dict)
        else []
    )
    if not isinstance(groups, list) or not groups:
        return {
            "ok": False,
            "rows": [],
            "status": "error",
            "raw_status": "invalid response",
        }

    # 按固定顺序提取 Gemini 与 Claude/GPT 两组各自的 5h 与 weekly 窗口
    specs = (
        ("gemini", "gemini_5h", "Gem 5h", "5h"),
        ("gemini", "gemini_wk", "Gem Wk", "weekly"),
        ("claude", "claude_5h", "Cld 5h", "5h"),
        ("claude", "claude_wk", "Cld Wk", "weekly"),
    )
    rows = []
    for group_key, row_key, label, window_name in specs:
        group = _match_antigravity_group(groups, group_key)
        buckets = group.get("buckets", []) if isinstance(group, dict) else []
        bucket = next(
            (b for b in buckets if isinstance(b, dict) and b.get("window") == window_name),
            {},
        )
        rows.append(_build_antigravity_row(row_key, label, bucket))

    severity = {"hot": 3, "warn": 2, "ok": 1, "unknown": 0}
    worst = max(rows, key=lambda r: severity.get(r["status"], 0))["status"]

    return {
        "ok": True,
        "rows": rows,
        "status": worst,
        "raw_status": "",
    }


def build_snapshot() -> dict:
    """获取并构建完整数据快照。"""
    antigravity = get_antigravity_usage()
    codex = get_codex_usage()
    deepseek = get_deepseek_balance()
    return {
        "antigravity": build_antigravity_snapshot(antigravity),
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
    # Rand/0 Display Mode：本地 WebSocket 推送 200×200 图片
    parser.add_argument("--display-mode", metavar="IP", help="通过本地 WebSocket 推送到指定 IP 的 Rand/0 设备")
    parser.add_argument("--gray4", action="store_true", help="Display Mode 使用四级灰（默认黑白 bw）")
    args = parser.parse_args()

    if args.display_mode:
        # 惰性导入，避免无 websocket-client 时影响其他命令
        import rand0_display
        mode = "gray4" if args.gray4 else "bw"
        snapshot = build_snapshot()
        payload = rand0_display.render_frame(snapshot, mode)
        print(f"[{mode}] 帧 {len(payload)} 字节 -> {args.display_mode}")
        received = rand0_display.push_frame(args.display_mode, mode, payload)
        print(f"推送完成，收到设备消息 {received} 条")
    elif args.debug_json:
        snapshot = build_snapshot()
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
