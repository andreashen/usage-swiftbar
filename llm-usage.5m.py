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

NEW_API_USER_SELF_PATH = "/api/user/self"
NEW_API_TOKEN_LIST_PATH = "/api/token/"
QUOTA_PER_USD = 500000.0


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
    details: Optional[Dict[str, Any]] = None


@dataclass
class NewApiValidationResult:
    level1_ok: bool
    level1_msg: str
    level2_ok: bool
    level2_msg: str
    level3_ok: bool
    level3_msg: str
    user_self_url: Optional[str] = None
    token_list_url: Optional[str] = None

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
        details = fetch_new_api_account_details(account)
        windows = details_to_windows(details)
        if not windows:
            windows = load_manual_windows(account)
        if not windows:
            raise PluginError("未识别到远程数据，且未配置手工窗口")
        return AccountUsage(
            account_id=account["id"],
            provider=account["provider"],
            account_name=account["name"],
            windows=windows,
            details=details,
        )


def new_api_headers(user_id: str, token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "New-Api-User": user_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "llm-usage-swiftbar/1.0",
    }


def http_get_json_allow_query(url: str, headers: Dict[str, str], timeout: int = 10) -> Dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        raise PluginError(f"HTTP {err.code} ({url}): {body[:160]}")
    except urllib.error.URLError as err:
        raise PluginError(f"请求失败 ({url}): {err.reason}")
    except json.JSONDecodeError:
        raise PluginError(f"接口返回非 JSON ({url})")


def extract_success_payload(payload: Dict, url: str) -> Any:
    if not isinstance(payload, dict):
        raise PluginError(f"返回结构非法 ({url})")
    if payload.get("success") is False:
        raise PluginError(payload.get("message") or f"接口返回失败 ({url})")
    return payload.get("data", payload)


def fetch_new_api_user_self(base_url: str, user_id: str, token: str, timeout: int = 10) -> Dict[str, Any]:
    url = join_base_url(base_url, NEW_API_USER_SELF_PATH)
    payload = http_get_json_allow_query(url, headers=new_api_headers(user_id, token), timeout=timeout)
    data = extract_success_payload(payload, url)
    if not isinstance(data, dict):
        raise PluginError("/api/user/self data 结构异常")
    return data


def extract_new_api_token_items(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def fetch_new_api_tokens(base_url: str, user_id: str, token: str, timeout: int = 10) -> List[Dict[str, Any]]:
    page = 1
    size = 50
    all_items: List[Dict[str, Any]] = []
    while True:
        query = urllib.parse.urlencode({"p": page, "size": size})
        url = f"{join_base_url(base_url, NEW_API_TOKEN_LIST_PATH)}?{query}"
        payload = http_get_json_allow_query(url, headers=new_api_headers(user_id, token), timeout=timeout)
        data = extract_success_payload(payload, url)
        items = extract_new_api_token_items(data)
        all_items.extend(items)

        if isinstance(data, dict):
            total = int(parse_float(data.get("total")) or 0)
            page_no = int(parse_float(data.get("page")) or page)
            page_size = int(parse_float(data.get("page_size") or data.get("size")) or size)
            if page_size <= 0:
                break
            if page_no * page_size >= total:
                break
            page = page_no + 1
            continue
        break
    return all_items


def quota_to_usd(quota) -> float:
    val = parse_float(quota)
    if val is None:
        return 0.0
    return val / QUOTA_PER_USD


def format_usd(value: float) -> str:
    return f"${value:.2f}"


def normalize_expired_time(value) -> str:
    sec = parse_float(value)
    if sec is None:
        return "--"
    if int(sec) < 0:
        return "永不过期"
    if int(sec) == 0:
        return "--"
    try:
        dt = datetime.fromtimestamp(int(sec), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "--"


def details_to_windows(details: Dict[str, Any]) -> List[WindowUsage]:
    user = details.get("user", {})
    tokens = details.get("tokens", [])
    if not isinstance(user, dict):
        user = {}
    if not isinstance(tokens, list):
        tokens = []
    quota = parse_float(user.get("quota")) or 0.0
    used = parse_float(user.get("used_quota")) or 0.0
    util = 0.0
    if quota > 0:
        util = min(max((used / quota) * 100.0, 0.0), 100.0)
    window = WindowUsage(
        category="month",
        label="余额(USD)",
        utilization=util,
        note=f"余额 {format_usd(quota_to_usd(quota))}",
    )
    if tokens:
        return [window]
    return [window]


def fetch_new_api_account_details(account: Dict) -> Dict[str, Any]:
    settings = account.get("settings", {})
    base_url = (settings.get("base_url") or "").strip()
    user_id = str(settings.get("user_id") or "").strip()
    token = load_account_api_key(account)
    if not base_url:
        raise PluginError("缺少 Base URL")
    if not user_id:
        raise PluginError("缺少 user_id")
    if not token:
        raise PluginError("缺少用户级系统访问令牌")

    user = fetch_new_api_user_self(base_url, user_id, token, timeout=10)
    tokens = fetch_new_api_tokens(base_url, user_id, token, timeout=10)
    enabled = [item for item in tokens if int(parse_float(item.get("status")) or 0) == 1]
    token_cards = []
    for item in enabled:
        remain = parse_float(item.get("remain_quota")) or 0.0
        used = parse_float(item.get("used_quota")) or 0.0
        total = remain + used
        token_cards.append(
            {
                "name": item.get("name") or f"Token-{item.get('id', '')}",
                "remain_quota": remain,
                "used_quota": used,
                "total_quota": total,
                "expired_at": normalize_expired_time(item.get("expired_time")),
            }
        )
    return {"user": user, "tokens": token_cards}

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
        "details": item.details or {},
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
        details=data.get("details") if isinstance(data.get("details"), dict) else {},
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
            if account_usage.provider == "new_api":
                render_new_api_account_details(account_usage)
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


def render_new_api_account_details(account_usage: AccountUsage) -> None:
    details = account_usage.details or {}
    user = details.get("user", {})
    tokens = details.get("tokens", [])
    if not isinstance(user, dict):
        user = {}
    if not isinstance(tokens, list):
        tokens = []

    quota_val = parse_float(user.get("quota")) or 0.0
    wallet_usd = quota_to_usd(quota_val)
    print(f"----💰 钱包余额 ${wallet_usd:.2f} | size=10 {NOOP}")

    if not tokens:
        print(f"----(无已启用 Token) | size=10 {NOOP}")
        return

    for token in tokens:
        if not isinstance(token, dict):
            continue
        token_name = token.get("name") or "Token"
        remain_usd = quota_to_usd(parse_float(token.get("remain_quota")) or 0.0)
        total_usd = quota_to_usd(parse_float(token.get("total_quota")) or 0.0)
        expired = token.get("expired_at") or "永不过期"
        print(f"----🔑 {token_name} | size=10 {NOOP}")
        print(f"------剩余额度 ${remain_usd:.2f} | size=10 {NOOP}")
        print(f"------总额度 ${total_usd:.2f} | size=10 {NOOP}")
        print(f"------过期时间 {expired} | size=10 {NOOP}")


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


def parse_new_api_base_url(api_input: str) -> str:
    value = (api_input or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PluginError("API 链接必须是完整 HTTP/HTTPS Base URL")
    return f"{parsed.scheme}://{parsed.netloc}"


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
    return {"api_input": value, "base_url": parse_new_api_base_url(value)}


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


def validate_new_api_config(
    api_input: str,
    user_id: str,
    api_token: str,
    timeout: int = 10,
) -> NewApiValidationResult:
    if not api_input:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg="api 不能为空",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )
    if not user_id:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg="user_id 不能为空",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )
    if not api_token:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg="用户级系统访问令牌不能为空",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )

    parsed_input = parse_new_api_api_input(api_input)
    base_url = parsed_input["base_url"]
    level1_target = base_url
    l1 = http_probe_status(level1_target, headers={"User-Agent": "llm-usage-swiftbar/1.0"}, timeout=timeout)
    if not l1["reachable"]:
        return NewApiValidationResult(
            level1_ok=False,
            level1_msg=f"不可达: {l1['message']} ({level1_target})",
            level2_ok=False,
            level2_msg="未执行",
            level3_ok=False,
            level3_msg="未执行",
        )

    user_self_url = join_base_url(base_url, NEW_API_USER_SELF_PATH)
    level2_ok = False
    level2_msg = "未执行"
    try:
        user = fetch_new_api_user_self(base_url, user_id, api_token, timeout=timeout)
        if parse_float(user.get("quota")) is None:
            level2_msg = f"/api/user/self 缺少 quota 字段 ({user_self_url})"
        else:
            level2_ok = True
            level2_msg = f"通过（使用 {user_self_url}）"
    except Exception as err:
        level2_msg = f"{err} ({user_self_url})"

    token_list_url = f"{join_base_url(base_url, NEW_API_TOKEN_LIST_PATH)}?p=1&size=50"
    level3_ok = False
    level3_msg = "未执行"
    try:
        tokens = fetch_new_api_tokens(base_url, user_id, api_token, timeout=timeout)
        has_struct = False
        for item in tokens:
            if not isinstance(item, dict):
                continue
            if parse_float(item.get("remain_quota")) is not None:
                has_struct = True
                break
        if not has_struct:
            level3_msg = f"/api/token/ 返回数据缺少 remain_quota ({token_list_url})"
        else:
            level3_ok = True
            level3_msg = f"通过（使用 {token_list_url}）"
    except Exception as err:
        level3_msg = f"{err} ({token_list_url})"

    return NewApiValidationResult(
        level1_ok=True,
        level1_msg=f"{l1['message']} ({level1_target})",
        level2_ok=level2_ok,
        level2_msg=level2_msg,
        level3_ok=level3_ok,
        level3_msg=level3_msg,
        user_self_url=user_self_url,
        token_list_url=token_list_url,
    )


def format_validation_line(ok: bool, title: str, msg: str) -> str:
    lamp = "🟢" if ok else "🔴"
    return f"{lamp} {title}: {msg}"


def validation_summary_text(result: Optional[NewApiValidationResult]) -> str:
    if result is None:
        return (
            "测试结果：\n"
            "🔴 一级 API 可达：未测试\n"
            "🔴 二级 /api/user/self：未测试\n"
            "🔴 三级 /api/token/：未测试"
        )
    return "\n".join(
        [
            "测试结果：",
            format_validation_line(result.level1_ok, "一级 API 可达", result.level1_msg),
            format_validation_line(result.level2_ok, "二级 /api/user/self", result.level2_msg),
            format_validation_line(result.level3_ok, "三级 /api/token/", result.level3_msg),
        ]
    )


def prompt_new_api_native_dialog(
    name_value: str,
    api_value: str,
    user_id_value: str,
    token_value: str,
    status_text: str,
) -> Optional[Dict[str, str]]:
    """Use a basic native macOS dialog; custom accessory views render blank under SwiftBar."""
    require_macos_interactive()
    form_text = "\n".join(
        [
            f"name={name_value}",
            f"base_url={api_value}",
            f"user_id={user_id_value}",
            f"user_token={token_value}",
        ]
    )
    message = (
        "请按每行 key=value 填写配置：\n"
        "name=账号名称\n"
        "base_url=https://example.com\n"
        "user_id=用户ID\n"
        "user_token=用户级系统访问令牌\n\n"
        f"{status_text}"
    )
    script = f'''
use scripting additions
set dialogResult to display dialog "{apple_quote(message)}" default answer "{apple_quote(form_text)}" buttons {{"取消", "保存配置", "测试连接"}} default button "测试连接" with title "配置 New API 账号"
set buttonTitle to button returned of dialogResult
set formText to text returned of dialogResult
return buttonTitle & (ASCII character 31) & formText
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if "(-128)" in (result.stderr or ""):
            return None
        raise PluginError(result.stderr.strip() or "配置弹窗打开失败")
    parts = result.stdout.rstrip("\n").split(chr(31), 1)
    if len(parts) != 2:
        raise PluginError("配置弹窗结果解析失败")
    values = parse_key_value_form(parts[1])
    return {
        "button": parts[0].strip(),
        "name": values.get("name", ""),
        "api": values.get("base_url") or values.get("api", ""),
        "user_id": values.get("user_id", ""),
        "token": values.get("user_token") or values.get("api_token") or values.get("token", ""),
    }


def parse_key_value_form(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return values


def prompt_new_api_config() -> Optional[Dict[str, Any]]:
    def signature(name: str, api: str, user_id: str, token: str) -> str:
        return f"{name.strip()}\n{api.strip()}\n{user_id.strip()}\n{token.strip()}"

    def render_waiting() -> str:
        return (
            "测试结果：\n"
            "⏳ 一级 API 可达：测试中\n"
            "⏳ 二级 /api/user/self：测试中\n"
            "⏳ 三级 /api/token/：测试中"
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

    name = ""
    api = "https://"
    user_id = ""
    token = ""
    last_result: Optional[NewApiValidationResult] = None
    tested_signature = None

    while True:
        dialog = prompt_new_api_native_dialog(
            name,
            api,
            user_id,
            token,
            validation_summary_text(last_result),
        )
        if dialog is None or dialog["button"] == "取消":
            return None

        name = dialog["name"]
        api = dialog["api"]
        user_id = dialog["user_id"]
        token = dialog["token"]

        if dialog["button"] == "测试连接":
            if not name:
                last_result = fail_result("账号名称不能为空")
                tested_signature = None
                continue
            notify("New API 测试连接中...")
            try:
                last_result = validate_new_api_config(api, user_id, token, timeout=10)
            except Exception as err:
                last_result = fail_result(str(err))
            if last_result.all_green():
                tested_signature = signature(name, api, user_id, token)
            else:
                tested_signature = None
            continue

        if dialog["button"] == "保存配置":
            if not name:
                last_result = fail_result("账号名称不能为空")
                continue
            if not last_result or not last_result.all_green():
                last_result = fail_result("保存前必须先测试且三级全绿")
                continue
            if tested_signature != signature(name, api, user_id, token):
                last_result = fail_result("参数已变更，请重新测试")
                continue
            parsed_input = parse_new_api_api_input(api)
            return {
                "name": name,
                "api_input": api,
                "api_token": token,
                "user_id": user_id,
                "base_url": parsed_input["base_url"],
            }

        raise PluginError(f"未知按钮: {dialog['button']}")


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
            "user_id": config_result.get("user_id") or "",
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
