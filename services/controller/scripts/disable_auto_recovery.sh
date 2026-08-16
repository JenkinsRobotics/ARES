#!/usr/bin/env bash
# ==============================================================================
# Disable ARES Auto-Launch & Auto-Recovery Service
# ==============================================================================
set -euo pipefail

PLIST_LABEL="com.ares.controller"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [[ -f "$PLIST_PATH" ]]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "✅ ARES Auto-Launch & Auto-Recovery daemon disabled and unloaded."
else
  echo "ℹ️  ARES launchd daemon was not installed."
fi
