#!/bin/zsh
set -eu

repo_dir="${0:A:h:h}"
ares_state_dir="${ARES_HOME:-$HOME/.ares}"

cd "$repo_dir/services/controller"
export PYTHONPATH="$repo_dir"
export ARES_HOME="$ares_state_dir"
export ARES_WEBUI_STATE_DIR="${ARES_WEBUI_STATE_DIR:-$ares_state_dir/webui}"
export ARES_WEBUI_HOST="${ARES_WEBUI_HOST:-127.0.0.1}"
export ARES_WEBUI_PORT="${ARES_WEBUI_PORT:-8788}"
# Tailscale Serve originates the loopback-targeted proxy connection from this
# node's own tailnet address on macOS. Trust only that exact /32 as the proxy;
# never the whole 100.64/10 range.
if tailscale_ip="$(/opt/homebrew/bin/tailscale ip -4 2>/dev/null | /usr/bin/head -1)" && [[ -n "$tailscale_ip" ]]; then
  export ARES_WEBUI_TRUSTED_PROXY_CIDRS="${ARES_WEBUI_TRUSTED_PROXY_CIDRS:+$ARES_WEBUI_TRUSTED_PROXY_CIDRS,}${tailscale_ip}/32"
fi

exec "$repo_dir/services/controller/.venv/bin/python" -m uvicorn \
  fastapi_app.main:app --host "$ARES_WEBUI_HOST" --port "$ARES_WEBUI_PORT" --no-server-header
