#!/usr/bin/env bash
# ==============================================================================
# ARES Auto-Launch & Auto-Recovery Service Installer for macOS (launchd)
# ==============================================================================
set -euo pipefail

PLIST_LABEL="com.ares.controller"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/services/controller/.venv/bin/python"
LOG_DIR="$HOME/.ares/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[!] Error: Python venv not found at ${PYTHON_BIN}"
  exit 1
fi

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>-m</string>
        <string>fastapi_app.main</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}/services/controller</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${HOME}/.local/bin</string>
        <key>PYTHONPATH</key>
        <string>${REPO_ROOT}/services/controller:${REPO_ROOT}</string>
        <key>ARES_BIND_HOST</key>
        <string>0.0.0.0</string>
        <key>ARES_PORT</key>
        <string>8788</string>
        <key>ARES_HEADLESS</key>
        <string>1</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/controller.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/controller.err.log</string>
</dict>
</plist>
EOF

chmod 644 "$PLIST_PATH"

# Unload any existing instance before loading fresh
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✅ ARES Auto-Launch & Auto-Recovery daemon enabled!"
echo "   - Plist: $PLIST_PATH"
echo "   - Status: Active under launchd (KeepAlive=true, RunAtLoad=true)"
echo "   - Logs:   $LOG_DIR/controller.log"
