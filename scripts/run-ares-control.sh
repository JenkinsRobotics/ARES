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

# Beszel is ARES's self-hosted host monitor. It remains independently useful,
# but starting ARES also ensures both native services are awake.
launch_domain="gui/$(id -u)"
for beszel_job in com.jenkinsrobotics.beszel-hub com.jenkinsrobotics.beszel-agent; do
  /bin/launchctl kickstart "$launch_domain/$beszel_job" 2>/dev/null || true
done
# Tailscale Serve makes the proxied connection from loopback, so the raw TCP
# peer is already trusted by default and no CIDR needs widening here. The
# previous ${tailscale_ip}/32 entry was based on a wrong assumption about which
# address ARES observes, and it did not help: uvicorn enables --proxy-headers by
# default, which rewrites request.client to the address in X-Forwarded-For --
# i.e. the *phone*, not the proxy. ARES' raw-peer check then saw 100.95.x and
# failed closed with "Tailscale identity is accepted only from the loopback
# Serve proxy", so every API call 403'd while the HTML shell still loaded.
#
# --no-proxy-headers keeps request.client as the real TCP peer (loopback), which
# is exactly what api.network_trust.raw_peer_is_trusted_proxy is written to
# check. Code that legitimately wants the originating client still resolves it
# through forwarded_client_ip_from_trusted_proxy(). This keeps the security
# posture the old comment was reaching for -- the 100.64/10 range stays
# untrusted -- while letting identity actually work.

exec "$repo_dir/services/controller/.venv/bin/python" -m uvicorn \
  fastapi_app.main:app --host "$ARES_WEBUI_HOST" --port "$ARES_WEBUI_PORT" \
  --no-server-header --no-proxy-headers
