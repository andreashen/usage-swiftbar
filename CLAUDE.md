# Usage SwiftBar Plugin (LLM Usage Bar)

## Goal

Evolve this fork (originally from `joewongjc/claude-usage-swiftbar`) into a generic macOS SwiftBar menu bar plugin that can display usage/quota windows for multiple LLM platforms (remote APIs or official clients), and make it easy to add new providers over time.

> **Note:** This repository is an independently evolved fork.

## Current State

- Only Claude Code usage is implemented today.
- Auth relies on Claude Code OAuth credentials stored in macOS Keychain (via `claude login`).
- Plugin script name is `llm-usage.5m.py`.

## Deployment

Run `./install.sh` to install. The script will:
1. Check that this is macOS
2. Install SwiftBar via Homebrew if not present
3. Verify Claude Code OAuth credentials exist in Keychain
4. Copy the plugin to `~/Library/SwiftBar/`
5. Set executable permissions

## Prerequisites (current)

- macOS
- Claude Code, logged in via `claude login` (OAuth authentication)
- Homebrew (will be used to install SwiftBar if needed)

## Development Notes

- Keep provider-specific logic isolated so adding a new platform does not touch the core rendering logic.
- Preserve the existing caching behavior to avoid rate limits.
- When adding a new provider, update README (supported providers + prerequisites) and keep secrets out of the repo.

## Project Structure (current)

- `llm-usage.5m.py` - The SwiftBar plugin script (refreshes every 5 minutes)
- `install.sh` - Automated installer
- `README.md` - User-facing documentation
