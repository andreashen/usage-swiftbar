# LLM Usage SwiftBar Plugin (Multi-provider Planned)

[中文](README.md) | English

A macOS menu bar plugin that displays usage and reset windows for multiple LLM platforms (remote APIs or official clients). Built for [SwiftBar](https://github.com/swiftbar/SwiftBar).

This repository is an evolving fork of a Claude Code usage plugin: **today it still only supports Claude Code** (OAuth via macOS Keychain). This README has been updated to reflect the goal of becoming a generic, extensible multi-provider usage bar.

## Features

### Supported (current implementation: Claude Code)

- **Real-time usage tracking** - Weekly (7-day), per-model (Sonnet/Opus), and 5-hour burst usage
- **Color-coded progress bars** - 5-tier color system (green/blue/yellow/orange/red)
- **Usage vs time progress** - Compare usage progress against time progress to decide whether to conserve or use freely
- **Extra usage credits** - Track overage spending if enabled
- **Smart caching** - 30-minute cache to avoid API rate limits, with manual refresh option
- **Auto plan detection** - Displays your subscription tier (Pro, Max, Max 5x, Max 20x)

### Planned (multi-provider)

- **Unified dimensions** - Aggregate by provider + account + model/plan
- **Pluggable providers** - Add new platforms without touching core rendering/caching
- **More platforms** - Incrementally add new LLM vendors and proxy platforms (as implemented)

## Requirements

### Current (Claude Code only)

- **macOS** (SwiftBar is macOS-only)
- **Claude Code** with OAuth login (`claude login`)
- **Python 3.9+** (included with macOS)

> **Note:** The current version reads Claude Code OAuth credentials from macOS Keychain. It does NOT work with API key authentication (`ANTHROPIC_API_KEY`). You must be logged in via `claude login`.

### Future (multi-provider)

Different providers may require different auth methods (API keys, OAuth, enterprise gateways, etc.). Requirements and configuration will be documented as each provider is added.

## Install

### One-liner (with Claude Code)

Give this repo URL to your Claude Code and ask it to install.

### Manual

```bash
git clone https://github.com/andreashen/usage-swiftbar.git
cd usage-swiftbar
./install.sh
```

The install script will:
1. Install [SwiftBar](https://github.com/swiftbar/SwiftBar) via Homebrew (if needed)
2. Verify your Claude Code OAuth credentials
3. Copy the plugin to `~/Library/SwiftBar/`
4. Start SwiftBar if not running

## What it looks like

Menu bar shows: `◆ 55%` (your weekly usage percentage, color changes with usage level)

Clicking reveals a dropdown with detailed breakdowns:

```
Claude Max 5x
─────────────────────────────
📅 Weekly (7d)  Remaining 4d 2h
  Usage  ███████████           55%
  Time   ██████████████████    90%
─────────────────────────────
📅 Sonnet (7d)
  Usage                         2%
  Time   ██████████████████    89%
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

## Uninstall

```bash
rm ~/Library/SwiftBar/llm-usage.5m.py
rm -f ~/.local/state/llm-usage-cache.json
```

## Acknowledgements

- Thanks to the upstream project [joewongjc/claude-usage-swiftbar](https://github.com/joewongjc/claude-usage-swiftbar) for the inspiration and initial implementation.
- Thanks to [SwiftBar](https://github.com/swiftbar/SwiftBar) for making menu bar plugins easy.

> **Note:** This repository is an independently evolved fork.

## License

MIT
