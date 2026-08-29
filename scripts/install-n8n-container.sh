#!/bin/zsh
set -eu

container_cli=/opt/homebrew/bin/container
container_name=ares-n8n
container_image=docker.io/n8nio/n8n:2.14.2
n8n_state_dir="${ARES_HOME:-$HOME/.ares}/n8n"
shared_workspace="${ARES_SHARED_WORKSPACE:-$HOME/workspace}"

mkdir -p "$n8n_state_dir" "$shared_workspace"
chmod 700 "${ARES_HOME:-$HOME/.ares}" "$n8n_state_dir"
"$container_cli" system start >/dev/null

if "$container_cli" list --all --quiet | /usr/bin/grep -Fxq "$container_name"; then
  if ! "$container_cli" list --quiet | /usr/bin/grep -Fxq "$container_name"; then
    "$container_cli" start "$container_name"
  fi
  echo "n8n container already exists: $container_name"
  exit 0
fi

"$container_cli" image pull "$container_image"
"$container_cli" run --detach \
  --name "$container_name" \
  --cpus 2 \
  --memory 2G \
  --cap-drop ALL \
  --user "$(id -u):$(id -g)" \
  --workdir /workspace \
  --publish 127.0.0.1:5678:5678 \
  --volume "$n8n_state_dir:/n8n-data" \
  --volume "$shared_workspace:/workspace" \
  --env HOME=/n8n-data \
  --env N8N_USER_FOLDER=/n8n-data \
  --env N8N_LISTEN_ADDRESS=0.0.0.0 \
  --env N8N_PORT=5678 \
  --env N8N_PROTOCOL=http \
  --env N8N_SECURE_COOKIE=false \
  --env N8N_DIAGNOSTICS_ENABLED=false \
  --env N8N_PERSONALIZATION_ENABLED=false \
  --env N8N_VERSION_NOTIFICATIONS_ENABLED=false \
  --env N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true \
  --env N8N_BLOCK_ENV_ACCESS_IN_NODE=true \
  --env N8N_COMMUNITY_PACKAGES_ENABLED=false \
  --env GENERIC_TIMEZONE=America/Los_Angeles \
  "$container_image"

echo "n8n is starting at http://127.0.0.1:5678"
