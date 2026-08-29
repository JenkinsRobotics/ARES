#!/bin/zsh
set -eu

ares_state_dir="${ARES_HOME:-$HOME/.ares}"
gateway_binary="$HOME/Library/Application Support/ARES/bin/agentgateway-v1.5.0"
gateway_config="$ares_state_dir/gateway/config.yaml"

if [[ ! -x "$gateway_binary" ]]; then
  print -u2 "Agentgateway is not installed. Run scripts/install-agentgateway.py."
  exit 1
fi
if [[ ! -f "$gateway_config" ]]; then
  print -u2 "Agentgateway config is missing. Run scripts/configure-system-fabric.py."
  exit 1
fi

export STATS_ADDR=127.0.0.1:15020
export READINESS_ADDR=127.0.0.1:15021

exec "$gateway_binary" --file "$gateway_config"
