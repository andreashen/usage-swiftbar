# LLM Usage SwiftBar Plugin (Multi-provider)

[中文](README.md) | English

A macOS menu bar plugin that displays usage and reset windows for multiple LLM platforms (remote APIs or official clients). Built for [SwiftBar](https://github.com/swiftbar/SwiftBar).

This repository evolved from an earlier single-provider usage plugin. It is now driven by a **multi-provider, extensible architecture** (product requirements live in `docs/spec.md`). This README only covers install and usage.

> **Work in progress:** this project is still under active development and not feature-complete. Today it only has **early support for** `new_api` (other providers may be manual-window-only fallbacks; see the current implementation).

## Features

### Supported (current implementation)

- **Unified hierarchy** - Provider > Account > Windows (with primary account rule)
- **Multi-account management** - Add/remove accounts, set primary account from the menu
- **Window model** - Day / 5-hour / week / month / custom / no-reset (manual windows as a fallback)
- **New API (official endpoints)** - Configure Base URL + User ID + user-level system access token; “Test connection” (3-level traffic light) gating before save
- **Manual windows** - `Cursor` and `Trae.ai` can be tracked via manual utilization input for now
- **Smart caching** - 30-minute cache with clear-cache / refresh actions

### Planned (see `docs/spec.md`)

- **Unified dimensions** - Aggregate by provider + account + model/plan
- **Pluggable providers** - Add new platforms without touching core rendering/caching
- **More platforms** - Incrementally add new LLM vendors and proxy platforms (as implemented)

## Requirements

- **macOS** (SwiftBar is macOS-only; configuration dialogs use `osascript`)
- **Python 3.9+**
- **Homebrew** (used to install SwiftBar)

Security & storage:

- **Secrets** (e.g. `new_api` access token) may be stored in **macOS Keychain**
- **Non-sensitive config** (e.g. Base URL) is stored in a local config file

## Install

### Manual

```bash
git clone https://github.com/andreashen/usage-swiftbar.git
cd usage-swiftbar
./install.sh
```

The install script will:
1. Install [SwiftBar](https://github.com/swiftbar/SwiftBar) via Homebrew (if needed)
2. Copy the plugin to `~/Library/SwiftBar/`
3. Start SwiftBar if not running

## What it looks like

Menu bar shows: `◆ 55%` (primary account’s primary window utilization, color changes with usage level)

Clicking reveals a dropdown with detailed breakdowns:

```
New API / Cursor / Trae.ai (example)
─────────────────────────────
📅 Weekly (7d)  Remaining 4d 2h
  Usage  ███████████           55%
  Time   ██████████████████    90%
─────────────────────────────
⏱ 5-Hour Burst  Remaining 1h 11m
  Usage  ████████              39%
  Time   ███████████████       76%
─────────────────────────────
Updated 18:48
Refresh now
```

### Color Scale

| Usage | Color | Meaning |
|-------|-------|---------|
| 0-19% | 🟢 Green | Plenty of quota |
| 20-39% | 🔵 Blue | Normal usage |
| 40-59% | 🟡 Yellow | Over halfway |
| 60-79% | 🟠 Orange | Getting tight |
| 80-100% | 🔴 Red | Running low |

## Configuration

The plugin refreshes every 5 minutes (configured via the filename `llm-usage.5m.py`). To change the refresh interval, rename the file:

- `llm-usage.1m.py` - Every minute
- `llm-usage.10m.py` - Every 10 minutes
- `llm-usage.30m.py` - Every 30 minutes

API calls are cached for 30 minutes regardless of refresh interval to avoid rate limiting. You can click "Refresh now" to force a fresh API call when the cache expires.

> **Tip:** The plugin script filename now uses `llm-usage.*.py`; the refresh interval mechanism remains the same.

### Configure via SwiftBar menu (no manual config editing required)

- **Add account**: choose “Add account” and follow the prompts
  - `new_api`: single dialog for name / Base URL / User ID / user-level system access token; you must “Test connection” (all green) before you can save
  - `Cursor` / `Trae.ai`: currently tracked via “manual windows” mode as a fallback
- **Manage accounts**: set primary account, remove account
- **Manual windows**: add/clear windows (day / 5-hour / week / month / custom / no-reset)
- **Cache**: clear cache and refresh

## Uninstall

```bash
./uninstall.sh
```

If you configured `new_api` tokens, they are stored in macOS Keychain. Prefer removing the account from the menu first to delete the corresponding Keychain entry.

## Acknowledgements

- Thanks to the upstream project [joewongjc/claude-usage-swiftbar](https://github.com/joewongjc/claude-usage-swiftbar) for the inspiration and initial implementation.
- Thanks to [SwiftBar](https://github.com/swiftbar/SwiftBar) for making menu bar plugins easy.

> **Note:** This repository is an independently evolved fork.

## License

MIT
