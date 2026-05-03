#!/bin/bash
set -euo pipefail

PLUGIN_NAME="claude-usage.5m.py"
SWIFTBAR_DIR="$HOME/Library/SwiftBar"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
error() { printf '\033[1;31m==>\033[0m %s\n' "$1" >&2; }

# 1. macOS check
if [[ "$(uname)" != "Darwin" ]]; then
    error "This plugin only works on macOS (SwiftBar is macOS-only)."
    exit 1
fi

# 2. Homebrew
if ! command -v brew &>/dev/null; then
    info "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 3. SwiftBar
if ! brew list --cask swiftbar &>/dev/null; then
    info "Installing SwiftBar..."
    brew install --cask swiftbar
fi

# 4. Python 3
if ! command -v python3 &>/dev/null; then
    error "python3 is required but not found."
    exit 1
fi
ok "python3 detected."

# 5. Plugin directory
if [[ ! -d "$SWIFTBAR_DIR" ]]; then
    info "Creating SwiftBar plugin directory: $SWIFTBAR_DIR"
    mkdir -p "$SWIFTBAR_DIR"
fi

# 6. Copy plugin
info "Installing plugin..."
cp "$SCRIPT_DIR/$PLUGIN_NAME" "$SWIFTBAR_DIR/$PLUGIN_NAME"
chmod +x "$SWIFTBAR_DIR/$PLUGIN_NAME"
ok "Plugin installed to $SWIFTBAR_DIR/$PLUGIN_NAME"

# 7. Launch SwiftBar if not running
if ! pgrep -q SwiftBar; then
    info "Starting SwiftBar..."
    open -a SwiftBar

    # First launch: SwiftBar needs a plugin directory configured
    # Give it a moment to start, then check
    sleep 2
    if ! defaults read com.ameba.SwiftBar PluginDirectory &>/dev/null 2>&1; then
        info "Setting SwiftBar plugin directory to $SWIFTBAR_DIR"
        defaults write com.ameba.SwiftBar PluginDirectory -string "$SWIFTBAR_DIR"
    fi
fi

echo ""
ok "Done! Look for the ◆ icon in your menu bar."
ok "Use the plugin menu to add providers/accounts via GUI prompts."
