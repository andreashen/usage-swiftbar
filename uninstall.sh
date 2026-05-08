#!/bin/bash
set -euo pipefail

PLUGIN_NAME="llm-usage.5m.py"
SWIFTBAR_DIR="$HOME/Library/SwiftBar"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
error() { printf '\033[1;31m==>\033[0m %s\n' "$1" >&2; }

if [[ "$(uname)" != "Darwin" ]]; then
  error "This plugin only works on macOS (SwiftBar is macOS-only)."
  exit 1
fi

info "Removing SwiftBar plugin file..."
rm -f "$SWIFTBAR_DIR/$PLUGIN_NAME"

info "Removing local cache/config..."
rm -f "$HOME/.local/state/llm-usage-cache.json"
rm -f "$HOME/.config/llm-usage-swiftbar/config.json"

echo ""
ok "Uninstall complete."
ok "If you added accounts, remove them from the plugin menu to delete related Keychain entries."
