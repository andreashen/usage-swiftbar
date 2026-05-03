# LLM Usage SwiftBar Plugin (Multi-provider)

[中文](README.md) | English

A macOS menu bar plugin that displays usage and reset windows for multiple LLM platforms (remote APIs or official clients). Built for [SwiftBar](https://github.com/swiftbar/SwiftBar).

This repository is an independently evolved fork with a provider-pluggable architecture.

## Features

### Supported providers

- **New API providers (priority)**  
  - Uses `Base URL + API Key`  
  - Attempts common usage endpoints automatically (or supports custom path)  
  - Falls back to manual windows when remote usage API cannot be detected

- **Cursor (low-priority integration path now)**  
  - Manual window mode (official personal usage API is not assumed)

- **Trae.ai (low-priority integration path now)**  
  - Manual window mode (official usage API is not assumed)

### Unified architecture

- **Provider > Account > Window** menu structure
- **Primary account** selection (for menu bar headline `%`)
- **Window categories**: day, 5-hour, week, month, custom, no-reset
- **GUI-driven configuration** in SwiftBar menu (no manual JSON editing required)
- **Pluggable adapters** for future providers/contributors
- **30-minute cache** to reduce API pressure

## Requirements

- **macOS** (SwiftBar is macOS-only)
- **Python 3.9+** (included with macOS)
- (Optional) `security` command (Keychain) when storing API keys securely

## Install

### Manual

```bash
git clone https://github.com/andreashen/usage-swiftbar.git
cd usage-swiftbar
./install.sh
```

The install script will:
1. Install [SwiftBar](https://github.com/swiftbar/SwiftBar) via Homebrew (if needed)
2. Verify Python 3 is available
3. Copy the plugin to `~/Library/SwiftBar/`
4. Start SwiftBar if not running

## Usage

After installation:

1. Click the `◆` icon in menu bar.
2. Choose **Add provider account**.
3. Select provider:
   - New API
   - Cursor
   - Trae.ai
4. Follow GUI prompts:
   - For New API: account name, base URL, optional usage path, optional API key
   - For Cursor / Trae: account name (manual window mode)
5. Optionally add manual windows (you can define day/5-hour/week/month/custom/no-reset).
6. Set a primary account to control the top bar usage indicator.

### Color Scale

| Usage | Color | Meaning |
|-------|-------|---------|
| 0-19% | 🟢 Green | Plenty of quota |
| 20-39% | 🔵 Blue | Normal usage |
| 40-59% | 🟡 Yellow | Over halfway |
| 60-79% | 🟠 Orange | Getting tight |
| 80-100% | 🔴 Red | Running low |

## Configuration

The plugin refreshes every 5 minutes (configured via filename `claude-usage.5m.py`). To change refresh interval, rename the file:

- `claude-usage.1m.py` - Every minute
- `claude-usage.10m.py` - Every 10 minutes
- `claude-usage.30m.py` - Every 30 minutes

API calls are cached for 30 minutes regardless of refresh interval to avoid rate limiting. You can clear cache from menu and refresh immediately.

### Data files

- Config: `~/.config/llm-usage-swiftbar/config.json`
- Cache: `~/.local/state/llm-usage-cache.json`
- Keychain service (default): `llm-usage-swiftbar`

## Uninstall

```bash
rm ~/Library/SwiftBar/claude-usage.5m.py
rm -f ~/.local/state/llm-usage-cache.json
rm -f ~/.config/llm-usage-swiftbar/config.json
```

## Acknowledgements

- Thanks to the upstream project [joewongjc/claude-usage-swiftbar](https://github.com/joewongjc/claude-usage-swiftbar) for the inspiration and initial implementation.
- Thanks to [SwiftBar](https://github.com/swiftbar/SwiftBar) for making menu bar plugins easy.

> **Note:** This repository is an independently evolved fork.

## License

MIT
