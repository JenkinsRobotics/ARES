#!/usr/bin/env bash
# ARES uninstaller
#
# Usage:
#   bash uninstall.sh          Remove the ARES install (server, launchd, app command).
#                              Keeps all worker-owned JaegerAI data.
#   bash uninstall.sh --purge  Also removes ARES-owned companion profile data.

set -e

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }

PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

echo "── ARES uninstall ──"

# 1. Stop processes
pkill -f "\.build/.*/ARES$" 2>/dev/null || true
pkill -f "swift run ARES" 2>/dev/null || true
pkill -f "$HOME/.ares/webui/server.py" 2>/dev/null || true
ok "Processes stopped"

# 2. launchd service
if [ -f "$HOME/Library/LaunchAgents/com.ares.webui.plist" ]; then
    launchctl unload "$HOME/Library/LaunchAgents/com.ares.webui.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/com.ares.webui.plist"
    ok "launchd service removed"
fi

# 3. Production install
if [ -d "$HOME/.ares" ]; then
    rm -rf "$HOME/.ares"
    ok "~/.ares removed"
fi

# 4. Launcher command + Mac app defaults
rm -f "$HOME/.local/bin/ares"
rm -rf "$HOME/Applications/ARES.app"
defaults delete ARES 2>/dev/null || true
ok "Launcher command, ARES.app, and app defaults removed"

if [ "$PURGE" = false ]; then
    echo ""
    ok "Uninstalled. JaegerAI and other worker-owned data were not changed."
    echo "  Run with --purge to remove the ARES-owned companion profile too."
    exit 0
fi

# ── --purge: remove remaining ARES-owned state ───────────────────────────────
echo ""
echo "── Purging ARES-owned state ──"

# Companion profile dir
if [ -d "$HOME/Desktop/ARES/companion" ]; then
    rm -rf "$HOME/Desktop/ARES/companion"
    ok "Companion profile removed (~/Desktop/ARES/companion)"
fi

echo ""
ok "Fully purged. Next install will run the complete onboarding sequence."
