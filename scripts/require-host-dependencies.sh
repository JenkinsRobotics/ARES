#!/usr/bin/env bash
# Shared host-dependency gate for ARES doctor, setup, and install.
# Required: Ollama. On Darwin: Xcode or Command Line Tools.
# Missing dependencies fail with a named message and a non-zero exit.
# Do not skip silently.

require_ares_host_dependencies() {
  local missing=0
  if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama is missing. Install Ollama from https://ollama.com and ensure ollama is on PATH." >&2
    missing=1
  fi
  case "$(uname -s)" in
    Darwin)
      if ! command -v xcode-select >/dev/null 2>&1 || ! xcode-select -p >/dev/null 2>&1; then
        echo "Xcode Command Line Tools are missing. Install them with: xcode-select --install" >&2
        missing=1
      fi
      ;;
  esac
  if (( missing )); then
    return 1
  fi
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  require_ares_host_dependencies
fi
