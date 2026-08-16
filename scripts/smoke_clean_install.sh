#!/usr/bin/env bash
# Exercise the real installer and health endpoint without touching user state.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ares-install-smoke.XXXXXX")"
SOURCE_COPY="$SMOKE_ROOT/source"
SMOKE_HOME="$SMOKE_ROOT/home"
STATE_HOME="$SMOKE_ROOT/state"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$SMOKE_ROOT"
}
trap cleanup EXIT INT TERM

mkdir -p "$SOURCE_COPY" "$SMOKE_HOME" "$STATE_HOME"
rsync -a \
  --exclude '/.git/' \
  --exclude '/.build/' \
  --exclude '/.venv/' \
  --exclude '/apps/web/node_modules/' \
  --exclude '/apps/web/dist/' \
  --exclude '/services/controller/.venv/' \
  --exclude '/services/controller/venv/' \
  --exclude '/services/controller/node_modules/' \
  --exclude '**/__pycache__/' \
  --exclude '**/.pytest_cache/' \
  "$REPO_ROOT/" "$SOURCE_COPY/"

HOME="$SMOKE_HOME" ARES_HOME="$STATE_HOME" \
  bash "$SOURCE_COPY/install.sh" \
    --source "$SOURCE_COPY" --no-cli --no-start --skip-native

PORT="$($SOURCE_COPY/services/controller/.venv/bin/python - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"

(
  cd "$SOURCE_COPY/services/controller"
  HOME="$SMOKE_HOME" ARES_HOME="$STATE_HOME" \
    ARES_WEBUI_HOST=127.0.0.1 ARES_WEBUI_PORT="$PORT" \
    .venv/bin/python -m uvicorn fastapi_app.main:app \
      --host 127.0.0.1 --port "$PORT" --no-server-header
) >"$SMOKE_ROOT/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$PORT/health" \
      | grep -Eq '"service"[[:space:]]*:[[:space:]]*"ares-webui"|"accept_loop"'; then
    echo "Clean install smoke passed on port $PORT"
    exit 0
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Controller exited before becoming healthy" >&2
    sed -n '1,240p' "$SMOKE_ROOT/server.log" >&2
    exit 1
  fi
  sleep 1
done

echo "Controller did not become healthy within 60 seconds" >&2
sed -n '1,240p' "$SMOKE_ROOT/server.log" >&2
exit 1
