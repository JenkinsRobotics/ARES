#!/usr/bin/env bash
# ARES controller launcher — thin wrapper that delegates to services/controller/start.sh.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/services/controller/start.sh"

# On macOS, the native menu app is the product lifecycle owner. Starting the
# controller directly creates a split state where HTTP is healthy but the menu
# app neither owns nor accurately reports it.
if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ] && [ "$#" -eq 0 ] && [ -x "$SCRIPT_DIR/bin/ares" ]; then
    exec "$SCRIPT_DIR/bin/ares" start
fi

if [ ! -f "$TARGET" ]; then
    echo "ERROR: controller launcher not found at $TARGET"
    echo "Make sure this script is run from the root of the ARES repository."
    exit 1
fi

exec bash "$TARGET" "$@"
