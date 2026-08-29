#!/bin/zsh
set -eu

container_cli=/opt/homebrew/bin/container
"$container_cli" system start >/dev/null 2>&1 || true

for managed_container in hermes-webui-hermes-webui ares-n8n; do
  if "$container_cli" list --all --quiet | /usr/bin/grep -Fxq "$managed_container"; then
    if ! "$container_cli" list --quiet | /usr/bin/grep -Fxq "$managed_container"; then
      "$container_cli" start "$managed_container"
    fi
  fi
done
