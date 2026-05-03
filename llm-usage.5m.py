#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>

import argparse
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

APP_NAME = "llm-usage-swiftbar"
CONFIG_FILE = os.path.expanduser("~/.config/llm-usage-swiftbar/config.json")
CACHE_FILE = os.path.expanduser("~/.local/state/llm-usage-cache.json")
CACHE_TTL = 1800
KEYCHAIN_SERVICE = "llm-usage-swiftbar"
BAR_WIDTH = 20
NOOP = "bash=/usr/bin/true terminal=false"

PROVIDER_LABELS = {
    "new_api": "New API",
    "cursor": "Cursor",
    "trae": "Trae.ai",
}

WINDOW_CATEGORIES = {
    "day": {"label": "日", "icon": "📅", "hours": 24},
    "five_hour": {"label": "5小时", "icon": "⏱", "hours": 5},
    "week": {"label": "周", "icon": "📅", "hours": 168},
    "month": {"label": "月", "icon": "🗓", "hours": 720},
    "custom": {"label": "自定义", "icon": "🧩", "hours": None},
    "no_reset": {"label": "不重置", "icon": "∞", "hours": None},
}

CATEGORY_ORDER = {
    "day": 0,
    "five_hour": 1,
    "week": 2,
    "month": 3,
    "custom": 4,
    "no_reset": 5,
}

NEW_API_PATH_CANDIDATES = [
    "/api/usage/token",
    "/api/usage",
    "/usage",
    "/v1/usage",
    "/v1/dashboard/billing/usage",
]

URL_BASELIKE_PATHS = {
    "",
    "/",
    "/v1",
    "/api",
    "/openai",
    "/v1beta",
    "/v1beta1",
}


class PluginError(RuntimeError):
    pass


@dataclass
class WindowUsage:
    category: str
    label: str
    utilization: float
    resets_at: Optional[str] = None
    total_hours: Optional[float] = None
    note: str = ""


@dataclass
class AccountUsage:
    account_id: str
    provider: str
    account_name: str
    windows: List[WindowUsage]
    error: Optional[str] = None


@dataclass
class NewApiValidationResult:
    level1_ok: bool
    level1_msg: str
    level2_ok: bool
    level2_msg: str
    level3_ok: bool
    level3_msg: str
    token_check_url: Optional[str] = None
    usage_check_url: Optional[str] = None
    usage_path: Optional[str] = None
    is_base_input: bool = True

    def all_green(self) -> bool:
        return self.level1_ok and self.level2_ok and self.level3_ok


class ProviderAdapter:
    provider_name = ""

    def fetch(self, account: Dict) -> AccountUsage:
        raise NotImplementedError


class ManualOnlyProviderAdapter(ProviderAdapter):
    def fetch(self, account: Dict) -> AccountUsage:
        windows = load_manual_windows(account)
        if not windows:
            raise PluginError("尚未配置手工窗口")
        return AccountUsage(
            account_id=account["id"],
            provider=account["provider"],
            account_name=account["name"],
            windows=windows,
        )


class CursorProviderAdapter(ManualOnlyProviderAdapter):
    provider_name = "cursor"


class TraeProviderAdapter(ManualOnlyProviderAdapter):
    provider_name = "trae"


class NewApiProviderAdapter(ProviderAdapter):
    provider_name = "new_api"

    def fetch(self, account: Dict) -> AccountUsage:
        windows = self.fetch_remote_windows(account)
        if not windows:
            windows = load_manual_windows(account)
        if not windows:
            raise PluginError("未识别到远程用量接口，且未配置手工窗口")
        return AccountUsage(
            account_id=account["id"],
            provider=account["provider"],
            account_name=account["name"],
            windows=windows,
        )

    def fetch_remote_windows(self, account: Dict) -> List[WindowUsage]:
        settings = account.get("settings", {})
        base_url = (settings.get("base_url") or "").strip()
        if not base_url:
            return []

        api_key = load_account_api_key(account)
        if not api_key:
            return []

        usage_path = (settings.get("usage_path") or "").strip()
        paths = []
        if usage_path:
            paths.append(usage_path)
        paths.extend(NEW_API_PATH_CANDIDATES)

        last_err = None
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "llm-usage-swiftbar/1.0",
        }

        for path in dedupe_list(paths):
            try:
                data = http_get_json(join_base_url(base_url, path), headers=headers, timeout=10)
                windows = parse_new_api_usage_payload(data)
                if windows:
                    return windows
                last_err = "返回结构未包含可识别的用量字段"
            except Exception as err:
                last_err = str(err)

        if last_err:
            raise PluginError(last_err)
        return []


ADAPTERS = {
    "new_api": NewApiProviderAdapter(),
    "cursor": CursorProviderAdapter(),
    "trae": TraeProviderAdapter(),
}


def load_config() -> Dict:
    default = {"version": 1, "primary_account_id": None, "accounts": []}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        return default

    if not isinstance(raw, dict):
        return default
    if not isinstance(raw.get("accounts"), list):
        raw["accounts"] = []
    if "primary_account_id" not in raw:
        raw["primary_account_id"] = None
    if "version" not in raw:
        raw["version"] = 1
    return raw


def save_config(config: Dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


def load_cache() -> (Dict[str, AccountUsage], Optional[float]):
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        ts = float(payload.get("ts", 0))
        age = max(0.0, time.time() - ts)
        raw_accounts = payload.get("accounts", {})
        if not isinstance(raw_accounts, dict):
            return {}, None
        parsed = {}
        for account_id, item in raw_accounts.items():
            parsed[account_id] = deserialize_account_usage(item)
        return parsed, age
    except Exception:
        return {}, None


def save_cache(usages: List[AccountUsage]) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    payload = {
        "ts": time.time(),
        "accounts": {item.account_id: serialize_account_usage(item) for item in usages},
    }
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def clear_cache() -> None:
    try:
        os.remove(CACHE_FILE)
    except FileNotFoundError:
        return


def serialize_account_usage(item: AccountUsage) -> Dict:
    return {
        "account_id": item.account_id,
        "provider": item.provider,
        "account_name": item.account_name,
        "error": item.error,
        "windows": [
            {
                "category": window.category,
                "label": window.label,
                "utilization": window.utilization,
                "resets_at": window.resets_at,
                "total_hours": window.total_hours,
                "note": window.note,
            }
            for window in item.windows
        ],
    }


def deserialize_account_usage(data: Dict) -> AccountUsage:
    windows = []
    for raw in data.get("windows", []):
        windows.append(
            WindowUsage(
                category=raw.get("category", "custom"),
                label=raw.get("label", "窗口"),
                utilization=normalize_percentage(raw.get("utilization")),
                resets_at=raw.get("resets_at"),
                total_hours=parse_float(raw.get("total_hours")),
                note=raw.get("note", ""),
            )
        )
    return AccountUsage(
        account_id=data.get("account_id", ""),
        provider=data.get("provider", ""),
        account_name=data.get("account_name", ""),
        windows=sort_windows(windows),
        error=data.get("error"),
    )


def collect_account_usages(config: Dict) -> (List[AccountUsage], Optional[float]):
    accounts = [acc for acc in config.get("accounts", []) if acc.get("enabled", True)]
    if not accounts:
        return [], None

    cache_map, cache_age = load_cache()
    use_cache = cache_age is not None and cache_age < CACHE_TTL
    usage_results = []
    updated = False

    for account in accounts:
        account_id = account.get("id", "")
        if use_cache and account_id in cache_map:
            usage_results.append(cache_map[account_id])
            continue

        adapter = ADAPTERS.get(account.get("provider"))
        if adapter is None:
            usage_results.append(
                AccountUsage(
                    account_id=account_id,
                    provider=account.get("provider", ""),
                    account_name=account.get("name", account_id),
                    windows=load_manual_windows(account),
                    error="未找到该平台适配器",
                )
            )
            updated = True
            continue

        try:
            usage_results.append(adapter.fetch(account))
        except Exception as err:
            usage_results.append(
                AccountUsage(
                    account_id=account_id,
                    provider=account.get("provider", ""),
                    account_name=account.get("name", account_id),
                    windows=load_manual_windows(account),
                    error=str(err),
                )
            )
        updated = True

    if updated:
        save_cache(usage_results)
        return usage_results, 0.0
    return usage_results, cache_age


def choose_primary_usage(config: Dict, usages: List[AccountUsage]) -> Optional[AccountUsage]:
    if not usages:
        return None
    primary_id = config.get("primary_account_id")
    if primary_id:
        for usage in usages:
            if usage.account_id == primary_id:
                return usage
    return usages[0]


def primary_utilization(usage: Optional[AccountUsage]) -> Optional[float]:
    if usage is None:
        return None
    for window in usage.windows:
        if window.utilization is not None:
            return normalize_percentage(window.utilization)
    return None


def render_no_config() -> None:
    print("◆ 配置 | color=#3B82F6 font=Menlo")
    print("---")
    print("尚未添加任何平台账号 | size=12")
    print("请点击下方菜单先完成配置 | size=11")
    print("---")
    print(f"➕ 添加平台账号 | {swiftbar_action_attrs('add-account')}")
    print(f"配置文件: {CONFIG_FILE} | size=10 {NOOP}")


def render_menu(config: Dict, usages: List[AccountUsage], cache_age: Optional[float]) -> None:
    primary = choose_primary_usage(config, usages)
    util = primary_utilization(primary)
    if util is None:
        print("◆ -- | color=#9CA3AF font=Menlo")
    else:
        print(f"◆ {int(util)}% | color={usage_color(util/100)} font=Menlo")

    print("---")
    if primary:
        provider_name = PROVIDER_LABELS.get(primary.provider, primary.provider)
        print(f"主账号: {primary.account_name} ({provider_name}) | size=12 {NOOP}")
    else:
        print(f"主账号: 未设置 | size=12 {NOOP}")
    print("---")

    grouped = group_by_provider(usages)
    for provider, items in grouped.items():
        print(f"{PROVIDER_LABELS.get(provider, provider)} | size=12 {NOOP}")
        for account_usage in items:
            star = "★" if primary and primary.account_id == account_usage.account_id else "•"
            print(f"--{star} {account_usage.account_name} | size=11 {NOOP}")
            if account_usage.error:
                print(f"----⚠ {account_usage.error} | size=10 color=#EF4444 {NOOP}")
            for window in sort_windows(account_usage.windows):
                render_window_line(window)
            if not primary or primary.account_id != account_usage.account_id:
                print(
                    f"----设为主账号 | {swiftbar_action_attrs('set-primary', account_usage.account_id)}"
                )
            print(
                f"----添加手工窗口 | {swiftbar_action_attrs('add-window', account_usage.account_id)}"
            )
            print(
                f"----清空手工窗口 | {swiftbar_action_attrs('clear-windows', account_usage.account_id)}"
            )
            print(
                f"----删除账号 | {swiftbar_action_attrs('remove-account', account_usage.account_id)}"
            )
        print("---")

    print(f"➕ 添加平台账号 | {swiftbar_action_attrs('add-account')}")
    print(f"♻️ 清空缓存并刷新 | {swiftbar_action_attrs('clear-cache')}")
    if cache_age is not None:
        print(f"缓存: {cache_age_str(cache_age)} | size=10 {NOOP}")
    else:
        print(f"已更新 {datetime.now().strftime('%H:%M')} | size=10 {NOOP}")
    print(f"配置文件: {CONFIG_FILE} | size=10 {NOOP}")
    print("立即刷新 | refresh=true")


def render_window_line(window: WindowUsage) -> None:
    cat = WINDOW_CATEGORIES.get(window.category, WINDOW_CATEGORIES["custom"])
    icon = cat["icon"]
    remain = ""
    if window.resets_at:
        remain = f" 剩余 {remaining_str(window.resets_at)}"
    print(f"----{icon} {window.label}{remain} | size=11 {NOOP}")
    util = normalize_percentage(window.utilization) / 100
    print(
        f"------用量  {progress_bar(util)} {int(util*100):3d}% | "
        f"font=Menlo size=10 color={usage_color(util)} {NOOP}"
    )
    tprog = compute_time_progress(window)
    if tprog is not None:
        print(
            f"------时间  {progress_bar(tprog)} {int(tprog*100):3d}% | "
            f"font=Menlo size=10 color={usage_color(tprog)} {NOOP}"
        )
    if window.note:
        print(f"------备注: {window.note} | size=10 {NOOP}")


def group_by_provider(usages: List[AccountUsage]) -> Dict[str, List[AccountUsage]]:
    grouped: Dict[str, List[AccountUsage]] = {}
    for usage in usages:
        grouped.setdefault(usage.provider, []).append(usage)
    return {
        key: sorted(value, key=lambda item: item.account_name.lower())
        for key, value in sorted(grouped.items(), key=lambda kv: provider_sort_key(kv[0]))
    }


def provider_sort_key(provider: str) -> int:
    order = ["new_api", "cursor", "trae"]
    return order.index(provider) if provider in order else len(order) + 1


def load_manual_windows(account: Dict) -> List[WindowUsage]:
    windows = []
    for raw in account.get("manual_windows", []):
        utilization = normalize_percentage(raw.get("utilization"))
        category = raw.get("category", "custom")
        label = raw.get("label") or WINDOW_CATEGORIES.get(category, WINDOW_CATEGORIES["custom"])["label"]
        total_hours = parse_float(raw.get("total_hours"))
        if total_hours is None:
            total_hours = WINDOW_CATEGORIES.get(category, WINDOW_CATEGORIES["custom"])["hours"]
        windows.append(
            WindowUsage(
                category=category,
                label=label,
                utilization=utilization,
                resets_at=raw.get("resets_at"),
                total_hours=total_hours,
                note=raw.get("note", ""),
            )
        )
    return sort_windows(windows)


def sort_windows(windows: List[WindowUsage]) -> List[WindowUsage]:
    return sorted(
        windows,
        key=lambda item: (CATEGORY_ORDER.get(item.category, 99), item.label.lower()),
    )


def normalize_percentage(value) -> float:
    val = parse_float(value)
    if val is None:
        return 0.0
    return min(max(val, 0.0), 100.0)


def parse_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_new_api_usage_payload(data: Dict) -> List[WindowUsage]:
    candidates = [data]
    if isinstance(data, dict):
        for key in ("data", "result", "usage", "quota"):
            if isinstance(data.get(key), dict):
                candidates.append(data[key])
            if isinstance(data.get(key), list):
                for item in data[key]:
                    if isinstance(item, dict):
                        candidates.append(item)

    for candidate in candidates:
        parsed = parse_usage_candidate(candidate)
        if parsed:
            return parsed
    return []


def parse_usage_candidate(candidate: Dict) -> List[WindowUsage]:
    if not isinstance(candidate, dict):
        return []

    window_list = []
    if isinstance(candidate.get("windows"), list):
        for item in candidate["windows"]:
            window = parse_usage_window(item)
            if window:
                window_list.append(window)
        if window_list:
            return sort_windows(window_list)

    single = parse_usage_window(candidate)
    if single:
        return [single]
    return []


def parse_usage_window(item: Dict) -> Optional[WindowUsage]:
    if not isinstance(item, dict):
        return None

    utilization = pick_float(item, ["utilization", "usage_rate", "percent", "percentage"])
    used = pick_float(item, ["used", "used_quota", "usage", "consumed", "spent"])
    total = pick_float(item, ["total", "total_quota", "quota", "limit", "monthly_limit"])
    remaining = pick_float(item, ["remaining", "left", "balance", "available"])

    if utilization is None:
        if used is not None and total and total > 0:
            utilization = used / total * 100.0
        elif remaining is not None and total and total > 0:
            utilization = (1 - remaining / total) * 100.0
        else:
            return None

    label = (
        item.get("label")
        or item.get("name")
        or item.get("window")
        or item.get("period")
        or "额度"
    )
    resets_at = (
        item.get("resets_at")
        or item.get("reset_at")
        or item.get("resetAt")
        or item.get("next_reset_at")
        or item.get("nextResetAt")
    )
    category = infer_category(str(label))
    total_hours = WINDOW_CATEGORIES.get(category, WINDOW_CATEGORIES["custom"])["hours"]
    note = ""
    if used is not None and total is not None:
        note = f"已用 {trim_float(used)} / 总额 {trim_float(total)}"

    return WindowUsage(
        category=category,
        label=str(label),
        utilization=normalize_percentage(utilization),
        resets_at=resets_at,
        total_hours=total_hours,
        note=note,
    )


def pick_float(payload: Dict, keys: List[str]) -> Optional[float]:
    for key in keys:
        if key in payload:
            value = parse_float(payload.get(key))
            if value is not None:
                return value
    return None


def infer_category(name: str) -> str:
    text = name.lower()
    if "5" in text and ("hour" in text or "小时" in text):
        return "five_hour"
    if "day" in text or "日" in text or "daily" in text:
        return "day"
    if "week" in text or "周" in text:
        return "week"
    if "month" in text or "月" in text or "billing" in text:
        return "month"
    if "no reset" in text or "不重置" in text or "永久" in text:
        return "no_reset"
    return "custom"


def trim_float(value: float) -> str:
    if int(value) == value:
        return str(int(value))
    return f"{value:.2f}"


def progress_bar(value, width=BAR_WIDTH):
    value = min(max(value, 0.0), 1.0)
    filled = round(value * width)
    return "█" * filled + " " * (width - filled)


def usage_color(value):
    if value < 0.20:
        return "#22C55E"
    if value < 0.40:
        return "#3B82F6"
    if value < 0.60:
        return "#EAB308"
    if value < 0.80:
        return "#F97316"
    return "#EF4444"


def remaining_str(resets_at_str):
    try:
        dt = parse_iso8601(resets_at_str)
        if dt is None:
            return "?"
        now = datetime.now(timezone.utc)
        remaining = (dt - now).total_seconds()
        if remaining <= 0:
            return "已重置"
        mins = int(remaining / 60)
        days = mins // (60 * 24)
        hours = (mins % (60 * 24)) // 60
        minutes = mins % 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception:
        return "?"


def compute_time_progress(window: WindowUsage) -> Optional[float]:
    if window.category == "no_reset":
        return None
    if not window.resets_at:
        return None
    total_hours = window.total_hours
    if total_hours is None or total_hours <= 0:
        return None
    dt = parse_iso8601(window.resets_at)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    total_secs = total_hours * 3600
    elapsed = total_secs - (dt - now).total_seconds()
    return min(max(elapsed / total_secs, 0.0), 1.0)


def parse_iso8601(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def cache_age_str(cache_age: float) -> str:
    if cache_age < 60:
        return "刚刚"
    if cache_age < 3600:
        return f"{int(cache_age / 60)}m 前"
    return f"{int(cache_age / 3600)}h 前"


def swiftbar_action_attrs(action: str, account_id: Optional[str] = None) -> str:
    script_path = os.path.realpath(__file__)
    parts = [
        'bash="/usr/bin/env"',
        "param0=python3",
        f'param1="{escape_swiftbar(script_path)}"',
        "param2=--action",
        f"param3={action}",
    ]
    if account_id:
        parts.extend(["param4=--account-id", f"param5={account_id}"])
    parts.extend(["terminal=false", "refresh=true"])
    return " ".join(parts)


def escape_swiftbar(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def join_base_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if not path:
        return base
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def http_get_json(url: str, headers: Dict[str, str], timeout: int = 10) -> Dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        raise PluginError(f"HTTP {err.code} ({url}): {body[:120]}")
    except urllib.error.URLError as err:
        raise PluginError(f"请求失败 ({url}): {err.reason}")
    except json.JSONDecodeError:
        raise PluginError(f"接口返回非 JSON ({url})")


def dedupe_list(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        norm = item.strip()
        if not norm or norm in seen:
            continue
        out.append(norm)
        seen.add(norm)
    return out


def load_account_api_key(account: Dict) -> Optional[str]:
    auth = account.get("auth", {})
    if auth.get("type") == "keychain":
        return keychain_get(auth.get("service", KEYCHAIN_SERVICE), auth.get("account", ""))
    plain = auth.get("api_key")
    if plain:
        return plain
    return None


def keychain_set(service: str, account: str, secret: str) -> None:
    if platform.system() != "Darwin":
        raise PluginError("Keychain 仅支持 macOS")
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            service,
            "-a",
            account,
            "-w",
            secret,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PluginError(f"写入 Keychain 失败: {result.stderr.strip()}")


def keychain_get(service: str, account: str) -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def keychain_delete(service: str, account: str) -> None:
    if platform.system() != "Darwin":
        return
    subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True,
        text=True,
    )


def require_macos_interactive() -> None:
    if platform.system() != "Darwin":
        raise PluginError("图形配置仅支持 macOS")


def osascript(script: str) -> str:
    require_macos_interactive()
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise PluginError(result.stderr.strip() or "取消操作")
    return result.stdout.strip()


def apple_quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def choose_from_list(prompt: str, options: List[str]) -> Optional[str]:
    rendered = ", ".join([f'"{apple_quote(opt)}"' for opt in options])
    script = (
        f"choose from list {{{rendered}}} "
        f'with prompt "{apple_quote(prompt)}" OK button name "确定" cancel button name "取消"'
    )
    out = osascript(script)
    if not out or out == "false":
        return None
    return out


def prompt_text(message: str, default: str = "", hidden: bool = False) -> Optional[str]:
    hidden_part = " with hidden answer" if hidden else ""
    script = (
        f'text returned of (display dialog "{apple_quote(message)}" '
        f'default answer "{apple_quote(default)}"{hidden_part} '
        'buttons {"取消", "确定"} default button "确定")'
    )
    out = osascript(script)
    return out if out is not None else None


def confirm_dialog(message: str) -> bool:
    script = (
        f'button returned of (display dialog "{apple_quote(message)}" '
        'buttons {"取消", "确定"} default button "确定")'
    )
    return osascript(script) == "确定"


def notify(message: str) -> None:
    if platform.system() != "Darwin":
        return
    msg = apple_quote(message)
    title = apple_quote(APP_NAME)
    subprocess.run(
        ["osascript", "-e", f'display notification "{msg}" with title "{title}"'],
        capture_output=True,
        text=True,
    )


def provider_choice_options() -> List[str]:
    return [f"{PROVIDER_LABELS['new_api']} (new_api)", f"{PROVIDER_LABELS['cursor']} (cursor)", f"{PROVIDER_LABELS['trae']} (trae)"]


def parse_provider_choice(choice: str) -> Optional[str]:
    if "(new_api)" in choice:
        return "new_api"
    if "(cursor)" in choice:
        return "cursor"
    if "(trae)" in choice:
        return "trae"
    return None


def parse_new_api_api_input(api_input: str) -> Dict[str, Any]:
    value = (api_input or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PluginError("api 必须是完整 HTTP/HTTPS 地址")

    clean = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path or "", "", parsed.query or "", "")
    ).rstrip("/")
    path = (parsed.path or "").rstrip("/")
    is_base = path in URL_BASELIKE_PATHS
    if not is_base and parsed.query:
        is_base = False
    elif not is_base and "usage" not in path.lower() and "billing" not in path.lower():
        # 非 usage-like path 也可能是网关 base（如 /openai/v1）
        is_base = True

    if is_base:
        base_url = clean
        return {
            "api_input": value,
            "is_base_input": True,
            "base_url": base_url,
            "usage_endpoint": None,
        }

    base_root = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "api_input": value,
        "is_base_input": False,
        "base_url": base_root,
        "usage_endpoint": clean,
    }


def build_usage_targets(api_input_parsed: Dict[str, Any]) -> List[str]:
    if not api_input_parsed.get("is_base_input"):
        endpoint = api_input_parsed.get("usage_endpoint")
        return [endpoint] if endpoint else []

    base_url = api_input_parsed.get("base_url", "")
    targets = [join_base_url(base_url, suffix) for suffix in NEW_API_PATH_CANDIDATES]
    return dedupe_list(targets)


def http_probe_status(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            return {"reachable": True, "status": status, "message": f"HTTP {status}", "url": url}
    except urllib.error.HTTPError as err:
        return {"reachable": True, "status": int(err.code), "message": f"HTTP {int(err.code)}", "url": url}
    except urllib.error.URLError as err:
        return {"reachable": False, "status": None, "message": str(err.reason), "url": url}


def derive_usage_path(base_url: str, usage_url: str) -> str:
    if usage_url.startswith("http://") or usage_url.startswith("https://"):
        if usage_url.startswith(base_url.rstrip("/")):
            sub = usage_url[len(base_url.rstrip("/")):]
            return sub or "/"
        return usage_url
    return usage_url


def probe_new_api_usage(url: str, api_token: str, timeout: int = 10) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "User-Agent": "llm-usage-swiftbar/1.0",
    }
    data = http_get_json(url, headers=headers, timeout=timeout)
    windows = parse_new_api_usage_payload(data)
    if not windows:
        raise PluginError("返回结构缺少可识别字段（需要 used/total/remaining 或 utilization）")
    return {"windows": windows, "payload": data}


def validate_new_api_config(api_input: str, api_token: str, timeout: int = 10) -> NewApiValidationResult:
    if not api_input:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg="api 不能为空",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )
    if not api_token:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg="api_token 不能为空",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )

    parsed_input = parse_new_api_api_input(api_input)
    level1_target = parsed_input["base_url"] if parsed_input["is_base_input"] else parsed_input["usage_endpoint"]
    l1 = http_probe_status(level1_target, headers={"User-Agent": "llm-usage-swiftbar/1.0"}, timeout=timeout)
    if not l1["reachable"]:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg=f"不可达: {l1['message']} ({level1_target})",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
            is_base_input=parsed_input["is_base_input"],
        )

    usage_targets = build_usage_targets(parsed_input)
    if not usage_targets:
        return NewApiValidationResult(
            level1_ok=True,
            level1_msg=f"{l1['message']} ({level1_target})",
            level2_ok=False,
            level2_msg="未找到可校验 endpoint",
            level3_ok=False,
            level3_msg="未找到可校验 endpoint",
            is_base_input=parsed_input["is_base_input"],
        )

    token_endpoint = None
    token_msg = "未找到可验证 token 的 endpoint"
    probe_headers = {"User-Agent": "llm-usage-swiftbar/1.0"}
    auth_headers = {
        "User-Agent": "llm-usage-swiftbar/1.0",
        "Authorization": f"Bearer {api_token}",
    }
    for target in usage_targets:
        no_auth = http_probe_status(target, headers=probe_headers, timeout=timeout)
        with_auth = http_probe_status(target, headers=auth_headers, timeout=timeout)
        if not with_auth["reachable"]:
            token_msg = f"请求失败: {with_auth['message']} ({target})"
            continue
        if with_auth["status"] in (401, 403):
            token_msg = f"鉴权失败: HTTP {with_auth['status']} ({target})"
            continue
        if no_auth["status"] in (401, 403) and with_auth["status"] not in (401, 403):
            token_endpoint = target
            token_msg = f"通过（使用 {target}）"
            break
        if no_auth["status"] is None or no_auth["status"] != with_auth["status"]:
            token_endpoint = target
            token_msg = f"通过（状态差异验证，使用 {target}）"
            break

    level2_ok = token_endpoint is not None

    usage_ok = False
    usage_msg = "未校验"
    usage_endpoint = None
    usage_path = None
    for target in usage_targets:
        try:
            probe_new_api_usage(target, api_token, timeout=timeout)
            usage_ok = True
            usage_endpoint = target
            usage_msg = f"可解析用量字段（{target}）"
            usage_path = derive_usage_path(parsed_input["base_url"], target)
            break
        except Exception as err:
            usage_msg = f"{err} ({target})"

    return NewApiValidationResult(
        level1_ok=True,
        level1_msg=f"{l1['message']} ({level1_target})",
        level2_ok=level2_ok,
        level2_msg=token_msg,
        level3_ok=usage_ok,
        level3_msg=usage_msg,
        token_check_url=token_endpoint,
        usage_check_url=usage_endpoint,
        usage_path=usage_path,
        is_base_input=parsed_input["is_base_input"],
    )


def format_validation_line(ok: bool, title: str, msg: str) -> str:
    lamp = "🟢" if ok else "🔴"
    return f"{lamp} {title}: {msg}"


def validation_summary_text(result: Optional[NewApiValidationResult]) -> str:
    if result is None:
        return (
            "测试结果：\n"
            "🔴 一级 API 可达：未测试\n"
            "🔴 二级 Token 可用：未测试\n"
            "🔴 三级 用量可用：未测试"
        )
    return "\n".join(
        [
            "测试结果：",
            format_validation_line(result.level1_ok, "一级 API 可达", result.level1_msg),
            format_validation_line(result.level2_ok, "二级 Token 可用", result.level2_msg),
            format_validation_line(result.level3_ok, "三级 用量可用", result.level3_msg),
        ]
    )


def prompt_new_api_config() -> Optional[Dict[str, Any]]:
    require_macos_interactive()
    try:
        import tkinter as tk
    except Exception as err:
        raise PluginError(f"无法加载图形窗口: {err}")

    state: Dict[str, Any] = {
        "last_result": None,
        "tested_signature": None,
        "saved_payload": None,
    }

    def signature(name: str, api: str, token: str) -> str:
        return f"{name.strip()}\n{api.strip()}\n{token.strip()}"

    def render_waiting() -> str:
        return (
            "测试结果：\n"
            "⏳ 一级 API 可达：测试中\n"
            "⏳ 二级 Token 可用：测试中\n"
            "⏳ 三级 用量可用：测试中"
        )

    def fail_result(msg: str) -> NewApiValidationResult:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg=msg,
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )

    root = tk.Tk()
    root.title("配置 New API 账号")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = tk.Frame(root, padx=14, pady=12)
    frame.grid(row=0, column=0, sticky="nsew")

    title_label = tk.Label(
        frame,
        text="同一弹窗内填写账号名称、API 链接和 API token",
        anchor="w",
        justify="left",
    )
    title_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    tk.Label(frame, text="账号名称").grid(row=1, column=0, sticky="w")
    name_var = tk.StringVar(value="")
    name_entry = tk.Entry(frame, textvariable=name_var, width=54)
    name_entry.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 8))

    tk.Label(frame, text="API 链接（Base URL 或完整 Usage Endpoint）").grid(
        row=3, column=0, sticky="w"
    )
    api_var = tk.StringVar(value="https://")
    api_entry = tk.Entry(frame, textvariable=api_var, width=54)
    api_entry.grid(row=4, column=0, columnspan=2, sticky="we", pady=(0, 8))

    tk.Label(frame, text="API Token").grid(row=5, column=0, sticky="w")
    token_var = tk.StringVar(value="")
    token_entry = tk.Entry(frame, textvariable=token_var, width=54, show="*")
    token_entry.grid(row=6, column=0, columnspan=2, sticky="we", pady=(0, 8))

    status_var = tk.StringVar(value=validation_summary_text(None))
    status_label = tk.Label(
        frame,
        textvariable=status_var,
        justify="left",
        anchor="w",
        wraplength=520,
    )
    status_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 10))

    button_frame = tk.Frame(frame)
    button_frame.grid(row=8, column=0, columnspan=2, sticky="e")

    def update_status_from_result(result: Optional[NewApiValidationResult]) -> None:
        status_var.set(validation_summary_text(result))
        root.update_idletasks()

    def on_test() -> None:
        name = name_var.get().strip()
        api = api_var.get().strip()
        token = token_var.get().strip()
        if not name:
            result = fail_result("账号名称不能为空")
            state["last_result"] = result
            state["tested_signature"] = None
            update_status_from_result(result)
            return
        status_var.set(render_waiting())
        root.update_idletasks()
        root.update()
        try:
            result = validate_new_api_config(api, token, timeout=10)
        except Exception as err:
            result = fail_result(str(err))
        state["last_result"] = result
        if result.all_green():
            state["tested_signature"] = signature(name, api, token)
        else:
            state["tested_signature"] = None
        update_status_from_result(result)

    def on_save() -> None:
        name = name_var.get().strip()
        api = api_var.get().strip()
        token = token_var.get().strip()
        if not name:
            update_status_from_result(fail_result("账号名称不能为空"))
            return
        last_result = state.get("last_result")
        if not isinstance(last_result, NewApiValidationResult) or not last_result.all_green():
            update_status_from_result(fail_result("保存前必须先测试且三级全绿"))
            return
        current_sig = signature(name, api, token)
        if state.get("tested_signature") != current_sig:
            update_status_from_result(fail_result("参数已变更，请重新测试"))
            return
        parsed_input = parse_new_api_api_input(api)
        state["saved_payload"] = {
            "name": name,
            "api_input": api,
            "api_token": token,
            "base_url": parsed_input["base_url"],
            "usage_path": last_result.usage_path or "",
            "usage_endpoint": last_result.usage_check_url,
        }
        root.destroy()

    def on_cancel() -> None:
        state["saved_payload"] = None
        root.destroy()

    test_btn = tk.Button(button_frame, text="测试连接", command=on_test, width=11)
    test_btn.grid(row=0, column=0, padx=(0, 8))
    save_btn = tk.Button(button_frame, text="保存配置", command=on_save, width=11)
    save_btn.grid(row=0, column=1, padx=(0, 8))
    cancel_btn = tk.Button(button_frame, text="取消", command=on_cancel, width=11)
    cancel_btn.grid(row=0, column=2)

    def on_close() -> None:
        on_cancel()

    root.protocol("WM_DELETE_WINDOW", on_close)
    name_entry.focus_set()
    root.mainloop()
    return state.get("saved_payload")


def prompt_new_api_config_legacy(account_name: str) -> Optional[Dict[str, Any]]:
    """Legacy osascript flow retained for reference; no longer used."""
    api_value = "https://"
    token_value = ""
    last_result: Optional[NewApiValidationResult] = None
    tested_signature = None
    while True:
        message = (
            f"配置 New API 账号：{account_name}\n\n"
            "请在同一输入框按如下格式填写：\n"
            "api=<Base URL 或完整 Usage Endpoint>\n"
            "api_token=<Token>\n\n"
            "点击“测试连接”执行三级校验（仅测试，不保存）。\n"
            "仅当三级全绿时可“保存配置”。\n\n"
            f"{validation_summary_text(last_result)}"
        )
        default_text = f"api={api_value}\napi_token={token_value}"
        dialog = prompt_text_with_buttons(
            message=message,
            default_text=default_text,
            buttons=["取消", "测试连接", "保存配置"],
            default_button="测试连接",
        )
        if dialog is None:
            return None
        button = dialog["button"]
        # 兼容旧版输入解析
        raw_lines = [line.strip() for line in dialog["text"].splitlines() if line.strip()]
        mapping = {}
        for line in raw_lines:
            if "=" in line:
                k, v = line.split("=", 1)
                mapping[k.strip().lower()] = v.strip()
        api_value = mapping.get("api", api_value)
        token_value = mapping.get("api_token", token_value)
        current_signature = f"{api_value}\n{token_value}"

        if button == "测试连接":
            try:
                last_result = validate_new_api_config(api_value, token_value, timeout=10)
                if last_result.all_green():
                    tested_signature = current_signature
            except Exception as err:
                last_result = NewApiValidationResult(
                    level1_ok=False,
                    level1_msg=str(err),
                    level2_ok=False,
                    level2_msg="未执行",
                    level3_ok=False,
                    level3_msg="未执行",
                )
                tested_signature = None
            continue

        if button == "保存配置":
            if not last_result or not last_result.all_green():
                last_result = last_result or NewApiValidationResult(
                    level1_ok=False,
                    level1_msg="尚未测试",
                    level2_ok=False,
                    level2_msg="尚未测试",
                    level3_ok=False,
                    level3_msg="尚未测试",
                )
                continue
            if tested_signature != current_signature:
                last_result = NewApiValidationResult(
                    level1_ok=False,
                    level1_msg="参数已变更，请重新测试",
                    level2_ok=False,
                    level2_msg="参数已变更，请重新测试",
                    level3_ok=False,
                    level3_msg="参数已变更，请重新测试",
                )
                continue
            parsed_input = parse_new_api_api_input(api_value)
            return {
                "api_input": api_value,
                "api_token": token_value,
                "base_url": parsed_input["base_url"],
                "usage_path": last_result.usage_path or "",
                "usage_endpoint": last_result.usage_check_url,
            }

        raise PluginError(f"未知按钮: {button}")


def action_add_new_api_account(config: Dict) -> None:
    config_result = prompt_new_api_config()
    if not config_result:
        return

    name = config_result["name"]
    existing_ids = [item.get("id", "") for item in config.get("accounts", [])]
    account_id = generate_account_id("new_api", name, existing_ids)
    keychain_account = f"new_api:{account_id}"
    keychain_set(KEYCHAIN_SERVICE, keychain_account, config_result["api_token"])
    account = {
        "id": account_id,
        "provider": "new_api",
        "name": name,
        "enabled": True,
        "settings": {
            "base_url": config_result["base_url"],
            "usage_path": config_result.get("usage_path") or "",
        },
        "auth": {
            "type": "keychain",
            "service": KEYCHAIN_SERVICE,
            "account": keychain_account,
        },
        "manual_windows": [],
    }
    config.setdefault("accounts", []).append(account)
    if not config.get("primary_account_id"):
        config["primary_account_id"] = account_id
    save_config(config)
    clear_cache()
    notify(f"已添加账号: {name}")


def generate_account_id(provider: str, name: str, existing_ids: List[str]) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not slug:
        slug = "account"
    base = f"{provider}-{slug}"
    candidate = base
    idx = 2
    while candidate in existing_ids:
        candidate = f"{base}-{idx}"
        idx += 1
    return candidate


def find_account(config: Dict, account_id: str) -> Optional[Dict]:
    for account in config.get("accounts", []):
        if account.get("id") == account_id:
            return account
    return None


def action_add_account() -> None:
    config = load_config()
    choice = choose_from_list("选择接入平台", provider_choice_options())
    if not choice:
        return
    provider = parse_provider_choice(choice)
    if provider is None:
        raise PluginError("无效的平台选择")

    if provider == "new_api":
        action_add_new_api_account(config)
        return

    name = (prompt_text("输入账号显示名称", "") or "").strip()
    if not name:
        raise PluginError("账号名称不能为空")

    existing_ids = [item.get("id", "") for item in config.get("accounts", [])]
    account_id = generate_account_id(provider, name, existing_ids)

    account = {
        "id": account_id,
        "provider": provider,
        "name": name,
        "enabled": True,
        "settings": {"mode": "manual"},
        "manual_windows": [],
    }
    config.setdefault("accounts", []).append(account)
    if not config.get("primary_account_id"):
        config["primary_account_id"] = account_id
    save_config(config)
    clear_cache()
    notify(f"{PROVIDER_LABELS[provider]} 暂以手工窗口模式接入")

    if confirm_dialog("是否立即添加一个手工窗口？"):
        action_add_window(account_id)
    notify(f"已添加账号: {name}")


def action_set_primary(account_id: str) -> None:
    config = load_config()
    account = find_account(config, account_id)
    if not account:
        raise PluginError("账号不存在")
    config["primary_account_id"] = account_id
    save_config(config)
    clear_cache()
    notify(f"主账号已设置为 {account.get('name')}")


def action_remove_account(account_id: str) -> None:
    config = load_config()
    account = find_account(config, account_id)
    if not account:
        raise PluginError("账号不存在")
    if not confirm_dialog(f"确认删除账号「{account.get('name')}」？"):
        return

    auth = account.get("auth", {})
    if auth.get("type") == "keychain":
        keychain_delete(auth.get("service", KEYCHAIN_SERVICE), auth.get("account", ""))

    config["accounts"] = [item for item in config.get("accounts", []) if item.get("id") != account_id]
    if config.get("primary_account_id") == account_id:
        config["primary_account_id"] = config["accounts"][0]["id"] if config["accounts"] else None
    save_config(config)
    clear_cache()
    notify("账号已删除")


def action_add_window(account_id: str) -> None:
    config = load_config()
    account = find_account(config, account_id)
    if not account:
        raise PluginError("账号不存在")

    options = [
        "日 (day)",
        "5小时 (five_hour)",
        "周 (week)",
        "月 (month)",
        "自定义 (custom)",
        "不重置 (no_reset)",
    ]
    choice = choose_from_list("选择窗口类型", options)
    if not choice:
        return

    category = "custom"
    if "(day)" in choice:
        category = "day"
    elif "(five_hour)" in choice:
        category = "five_hour"
    elif "(week)" in choice:
        category = "week"
    elif "(month)" in choice:
        category = "month"
    elif "(no_reset)" in choice:
        category = "no_reset"

    default_label = WINDOW_CATEGORIES.get(category, WINDOW_CATEGORIES["custom"])["label"]
    label = (prompt_text("窗口名称", default_label) or "").strip() or default_label
    utilization_raw = (prompt_text("输入用量百分比（0-100）", "0") or "").strip()
    utilization = parse_float(utilization_raw)
    if utilization is None:
        raise PluginError("用量百分比格式不正确")

    window = {
        "category": category,
        "label": label,
        "utilization": normalize_percentage(utilization),
    }

    if category != "no_reset":
        resets_at = (prompt_text("可选：重置时间 ISO8601（例如 2026-05-03T18:00:00Z）", "") or "").strip()
        if resets_at:
            window["resets_at"] = resets_at
    if category == "custom":
        total_hours_raw = (prompt_text("可选：窗口总时长（小时）", "") or "").strip()
        total_hours = parse_float(total_hours_raw)
        if total_hours is not None and total_hours > 0:
            window["total_hours"] = total_hours

    note = (prompt_text("可选：备注", "") or "").strip()
    if note:
        window["note"] = note

    account.setdefault("manual_windows", []).append(window)
    save_config(config)
    clear_cache()
    notify(f"已添加窗口: {label}")


def action_clear_windows(account_id: str) -> None:
    config = load_config()
    account = find_account(config, account_id)
    if not account:
        raise PluginError("账号不存在")
    if not confirm_dialog(f"确认清空「{account.get('name')}」的手工窗口？"):
        return
    account["manual_windows"] = []
    save_config(config)
    clear_cache()
    notify("手工窗口已清空")


def action_clear_cache() -> None:
    clear_cache()
    notify("缓存已清空")


def run_action(action: str, account_id: Optional[str]) -> None:
    if action == "add-account":
        action_add_account()
        return
    if action == "set-primary":
        if not account_id:
            raise PluginError("缺少 account_id")
        action_set_primary(account_id)
        return
    if action == "remove-account":
        if not account_id:
            raise PluginError("缺少 account_id")
        action_remove_account(account_id)
        return
    if action == "add-window":
        if not account_id:
            raise PluginError("缺少 account_id")
        action_add_window(account_id)
        return
    if action == "clear-windows":
        if not account_id:
            raise PluginError("缺少 account_id")
        action_clear_windows(account_id)
        return
    if action == "clear-cache":
        action_clear_cache()
        return
    raise PluginError(f"未知 action: {action}")


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--action")
    parser.add_argument("--account-id")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.action:
        try:
            run_action(args.action, args.account_id)
        except Exception as err:
            notify(f"操作失败: {err}")
        return

    config = load_config()
    usages, cache_age = collect_account_usages(config)
    if not usages:
        render_no_config()
        return
    render_menu(config, usages, cache_age)


if __name__ == "__main__":
    main()
