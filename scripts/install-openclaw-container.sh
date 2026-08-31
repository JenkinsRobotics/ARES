#!/bin/zsh
# Provision OpenClaw as an ARES-managed agent runtime in an Apple container.
#
# OpenClaw is an independently owned agent product; per DOCTRINE, ARES never
# imports its code and reaches it only through its published gateway. The
# container is the isolation boundary: OpenClaw gets its own state directory
# and the single shared workspace, and is published only on loopback.
#
# Two non-obvious constraints drive the flags below:
#
#   1. OpenClaw's gateway binds loopback *inside* the container by default,
#      which makes a published port unreachable from the host. It must be set
#      to bind mode `lan`, which in turn makes token auth mandatory rather
#      than optional -- the container's network is not a trust boundary.
#   2. Host Ollama is not on the container's loopback. Apple containers use
#      the stable `host.container.internal` redirect. The raw vmnet gateway is
#      deliberately not used: its subnet moves and a loopback-only host
#      listener is not reachable through the bridge interface directly.
set -eu

container_cli=/opt/homebrew/bin/container
container_name=ares-openclaw
container_image="${ARES_OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw@sha256:2f5ce8848a1a69b3c460622e566cb9395da9fd18d7ef7b038cd8e2c4f195decf}"
gateway_port=18789
ares_home="${ARES_HOME:-$HOME/.ares}"
openclaw_state_dir="$ares_home/openclaw"
shared_workspace="${ARES_SHARED_WORKSPACE:-$HOME/workspace}"
host_ollama="${ARES_CONTAINER_OLLAMA_URL:-http://host.container.internal:11434}"
keychain_service="ares-openclaw-gateway"
gateway_token_file="$openclaw_state_dir/gateway.token"

# Build an explicit agent-suitable catalog from Ollama's owner API.  The local
# daemon may advertise both downloaded models and signed-in cloud stubs in the
# same /api/tags response; OpenClaw should present those as two provider lanes,
# not one mixed list. Embedding-only models are intentionally excluded.
build_ollama_provider_catalog() {
  ARES_OLLAMA_CATALOG_URL="${ARES_HOST_OLLAMA_CATALOG_URL:-http://127.0.0.1:11434}" \
    ARES_CONTAINER_OLLAMA_URL="$host_ollama" /usr/bin/python3 - <<'PY'
import json
import os
import urllib.request

catalog_url = os.environ["ARES_OLLAMA_CATALOG_URL"].rstrip("/")
container_url = os.environ["ARES_CONTAINER_OLLAMA_URL"].rstrip("/")
preferred_cloud_id = os.environ.get("ARES_OPENCLAW_PREFERRED_CLOUD_MODEL", "").strip()
preferred_local_id = os.environ.get("ARES_OPENCLAW_PREFERRED_LOCAL_MODEL", "").strip()


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        catalog_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode() or "{}")


def context_length(row, shown):
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    direct = details.get("context_length")
    if isinstance(direct, int) and direct > 0:
        return direct
    model_info = shown.get("model_info") if isinstance(shown.get("model_info"), dict) else {}
    candidates = [
        value for key, value in model_info.items()
        if str(key).endswith(".context_length") and isinstance(value, int) and value > 0
    ]
    return max(candidates) if candidates else 32768


local_models = []
cloud_models = []
for row in request("/api/tags").get("models") or []:
    if not isinstance(row, dict):
        continue
    model_id = str(row.get("name") or row.get("model") or "").strip()
    if not model_id:
        continue
    try:
        shown = request("/api/show", {"model": model_id})
    except Exception:
        shown = {}
    capabilities = {
        str(value).strip().lower()
        for value in (shown.get("capabilities") or row.get("capabilities") or [])
    }
    if "completion" not in capabilities or "tools" not in capabilities:
        continue
    remote = bool(row.get("remote_host") or row.get("remote_model")) or model_id.endswith(":cloud")
    window = context_length(row, shown)
    entry = {
        "id": model_id,
        "name": model_id,
        "input": ["text", "image"] if "vision" in capabilities else ["text"],
        "reasoning": "thinking" in capabilities,
        "contextWindow": window,
        "maxTokens": min(32768, max(4096, window // 4)),
    }
    (cloud_models if remote else local_models).append(entry)

if not local_models:
    raise SystemExit("No tool-capable local Ollama chat model is available")

providers = {
    "ollama-local": {
        "baseUrl": container_url,
        "api": "ollama",
        "apiKey": "ollama-local",
        "models": local_models,
    },
    # Do not use OpenClaw's reserved ``ollama-cloud`` provider id here. That
    # id means direct https://ollama.com and requires a separate API key. This
    # custom lane deliberately routes signed-in ``:cloud`` models through the
    # owner's local Ollama daemon, so it uses the private-host auth marker.
    "ollama-cloud-via-host": {
        # Cloud requests deliberately pass through the signed-in host daemon.
        # This keeps the Ollama credential in its owner process and out of the
        # OpenClaw container while preserving a distinct cloud model lane.
        "baseUrl": container_url,
        "api": "ollama",
        "apiKey": "ollama-local",
        "models": cloud_models,
    },
}
preferred_cloud = next(
    (row["id"] for row in cloud_models if row["id"] == preferred_cloud_id),
    cloud_models[0]["id"] if cloud_models else "",
)
preferred_local = next(
    (row["id"] for row in local_models if row["id"] == preferred_local_id),
    local_models[0]["id"],
)
default_ref = (
    f"ollama-cloud-via-host/{preferred_cloud}"
    if preferred_cloud
    else f"ollama-local/{preferred_local}"
)
print(json.dumps({"providers": providers, "default": default_ref}, separators=(",", ":")))
PY
}

mkdir -p "$openclaw_state_dir" "$shared_workspace"
chmod 700 "$ares_home" "$openclaw_state_dir"
"$container_cli" system start >/dev/null

container_exists=false
if "$container_cli" list --all --quiet | /usr/bin/grep -Fxq "$container_name"; then
  container_exists=true
  if ! "$container_cli" list --quiet | /usr/bin/grep -Fxq "$container_name"; then
    "$container_cli" start "$container_name"
  fi
fi

# Keychain is the owner source of truth. The container receives a mode-0600
# runtime copy inside its already-private state mount. Do not use ``--env`` for
# the token: Apple Container persists environment values in inspect metadata.
# The shell entrypoint reads this file after the container starts, so host-side
# container inspection reveals only the file path, never the credential.
if ! gateway_token=$(/usr/bin/security find-generic-password \
      -a "$USER" -s "$keychain_service" -w 2>/dev/null); then
  gateway_token=$(/usr/bin/openssl rand -hex 32)
  /usr/bin/security add-generic-password \
    -a "$USER" -s "$keychain_service" -w "$gateway_token" -U
  echo "Generated a new gateway token in the login keychain ($keychain_service)."
fi
token_tmp=$(/usr/bin/mktemp "$openclaw_state_dir/.gateway.token.XXXXXX")
/bin/chmod 600 "$token_tmp"
/usr/bin/printf '%s\n' "$gateway_token" > "$token_tmp"
/bin/mv -f "$token_tmp" "$gateway_token_file"
/bin/chmod 600 "$gateway_token_file"

if [ "$container_exists" = false ]; then
  "$container_cli" image pull "$container_image"
fi

# Onboard into the mounted state directory before the long-running gateway
# starts, so the first boot already has a provider, bind mode, and auth.
# --skip-health because host Ollama is probed from inside the container and a
# cold daemon should not fail provisioning.
if [ "$container_exists" = false ] && [ ! -f "$openclaw_state_dir/openclaw.json" ]; then
  echo "Onboarding OpenClaw (provider: ollama at $host_ollama) ..."
  "$container_cli" run --rm \
    --name "${container_name}-onboard" \
    --volume "$openclaw_state_dir:/home/node/.openclaw" \
    --env "ARES_OPENCLAW_OLLAMA_URL=$host_ollama" \
    --entrypoint sh \
    "$container_image" \
    -lc 'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; exec node dist/index.js onboard --non-interactive --accept-risk --skip-health \
      --mode local \
      --auth-choice ollama \
      --custom-base-url "$ARES_OPENCLAW_OLLAMA_URL" \
      --secret-input-mode ref \
      --gateway-auth token \
      --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
      --skip-channels \
      --no-install-daemon'
fi

# Bind mode is a config value, not a host alias: `lan` (not 0.0.0.0) is what
# makes the published loopback port reachable.
catalog_json=$(build_ollama_provider_catalog)
providers_json=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])["providers"],separators=(",",":")))' "$catalog_json")
default_model=$(/usr/bin/python3 -c 'import json,sys; print(json.loads(sys.argv[1])["default"])' "$catalog_json")

if [ "$container_exists" = true ]; then
  openclaw_cli=("$container_cli" exec "$container_name" sh -lc \
    'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; exec node dist/index.js "$@"' sh)
else
  openclaw_cli=("$container_cli" run --rm \
    --name "${container_name}-config" \
    --volume "$openclaw_state_dir:/home/node/.openclaw" \
    --entrypoint sh "$container_image" -lc \
    'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; exec node dist/index.js "$@"' sh)
fi

"${openclaw_cli[@]}" config set models.providers "$providers_json" --strict-json --replace
batch_json=$(/usr/bin/python3 -c '
import json, sys
print(json.dumps([
    {"path": "models.mode", "value": "replace"},
    {"path": "agents.defaults.model.primary", "value": sys.argv[1]},
    {"path": "gateway.mode", "value": "local"},
    {"path": "gateway.bind", "value": "lan"},
    {
        "path": "gateway.controlUi.allowedOrigins",
        "value": ["http://localhost:18789", "http://127.0.0.1:18789"],
    },
    {"path": "plugins.entries.codex.enabled", "value": False},
], separators=(",", ":")))
' "$default_model")
"${openclaw_cli[@]}" config set --batch-json "$batch_json"

ensure_provider_auth() {
  local provider=$1
  local profile_id=$2
  # OpenClaw 2026.7 keeps per-agent provider eligibility in SQLite even
  # when a private custom Ollama provider has apiKey="ollama-local" in the
  # endpoint config. The marker is not a credential and is never sent as a
  # bearer token; it declares that this exact private host needs no auth.
  if "$container_cli" exec "$container_name" sh -lc \
      'node dist/index.js models auth list --agent main --json' \
      | /usr/bin/grep -Fq "\"provider\": \"$provider\""; then
    return 0
  fi
  /usr/bin/printf 'ollama-local\n' \
    | "$container_cli" exec --interactive "$container_name" sh -lc \
      "node dist/index.js models auth paste-api-key --provider '$provider' --profile-id '$profile_id'" \
      >/dev/null
}

if [ "$container_exists" = true ]; then
  echo "Updated existing OpenClaw provider catalog: Ollama Local + Ollama Cloud"
  ensure_provider_auth ollama-local ollama-local:local-marker
  ensure_provider_auth ollama-cloud-via-host ollama-cloud-via-host:local-marker
  # Provider/plugin changes are read at gateway startup. Restart only this
  # container; the mounted OpenClaw state and sessions remain intact.
  "$container_cli" stop "$container_name"
  "$container_cli" start "$container_name"
  for attempt in {1..30}; do
    if "$container_cli" exec "$container_name" sh -lc \
      'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; node dist/index.js gateway health --token "$OPENCLAW_GATEWAY_TOKEN"' >/dev/null 2>&1; then
      break
    fi
    /bin/sleep 1
  done
  "$container_cli" exec "$container_name" sh -lc \
    'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; node dist/index.js gateway health --token "$OPENCLAW_GATEWAY_TOKEN"'
  exit 0
fi

# Deliberately no --user or --workdir, unlike the n8n container:
#   * The image ships a non-root `node` user and pre-created 0700 state dirs;
#     Apple's runtime already maps bind-mount ownership back to the host user,
#     so forcing --user only breaks access to image-owned paths.
#   * The default CMD is `node openclaw.mjs gateway`, resolved relative to the
#     image WORKDIR (/app). Repointing it at /workspace makes Node fail with
#     "Cannot find module '/workspace/openclaw.mjs'".
"$container_cli" run --detach \
  --name "$container_name" \
  --cpus 4 \
  --memory 4G \
  --publish "127.0.0.1:${gateway_port}:${gateway_port}" \
  --volume "$openclaw_state_dir:/home/node/.openclaw" \
  --volume "$shared_workspace:/workspace" \
  --env "HOME=/home/node" \
  --env NODE_ENV=production \
  --entrypoint sh \
  "$container_image" \
  -lc 'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; exec node openclaw.mjs gateway'

for attempt in {1..30}; do
  if "$container_cli" exec "$container_name" true >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
ensure_provider_auth ollama-local ollama-local:local-marker
ensure_provider_auth ollama-cloud-via-host ollama-cloud-via-host:local-marker
"$container_cli" stop "$container_name" >/dev/null
"$container_cli" start "$container_name" >/dev/null
for attempt in {1..30}; do
  if "$container_cli" exec "$container_name" sh -lc \
    'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; node dist/index.js gateway health --token "$OPENCLAW_GATEWAY_TOKEN"' >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
"$container_cli" exec "$container_name" sh -lc \
  'export OPENCLAW_GATEWAY_TOKEN="$(cat /home/node/.openclaw/gateway.token)"; node dist/index.js gateway health --token "$OPENCLAW_GATEWAY_TOKEN"'

echo "OpenClaw is starting at http://127.0.0.1:${gateway_port}"
echo "Health:  curl -fsS http://127.0.0.1:${gateway_port}/healthz"
echo "Credential source: macOS Keychain service $keychain_service"
