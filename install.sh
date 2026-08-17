#!/usr/bin/env bash
# Install ARES from a checkout or through `curl .../install.sh | bash`.

set -euo pipefail

REPO_URL="${ARES_REPO_URL:-https://github.com/JenkinsRobotics/ARES.git}"
ARES_REF="${ARES_REF:-main}"
NO_START=false
NO_CLI=false
SKIP_NATIVE=false
SOURCE_DIR=""
INSTALL_DIR="${ARES_INSTALL_DIR:-}"

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --dir PATH       Install source at PATH (clone mode only)
  --source PATH    Install an existing ARES checkout
  --ref NAME       Branch or tag used when cloning (default: main)
  --no-start       Do not start the controller after installation
  --no-cli         Do not link `ares` into ~/.local/bin
  --skip-native    Do not build the optional macOS app
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="${2:?--dir requires a path}"; shift 2 ;;
    --source) SOURCE_DIR="${2:?--source requires a path}"; shift 2 ;;
    --ref) ARES_REF="${2:?--ref requires a name}"; shift 2 ;;
    --no-start) NO_START=true; shift ;;
    --no-cli) NO_CLI=true; shift ;;
    --skip-native) SKIP_NATIVE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$SOURCE_DIR" && -d "$SCRIPT_DIR/.git" ]]; then
  SOURCE_DIR="$SCRIPT_DIR"
fi

if [[ -n "$SOURCE_DIR" ]]; then
  ARES_ROOT="$(cd "$SOURCE_DIR" && pwd)"
  if [[ -n "$INSTALL_DIR" && "$(cd "$(dirname "$INSTALL_DIR")" && pwd)/$(basename "$INSTALL_DIR")" != "$ARES_ROOT" ]]; then
    echo "--dir cannot differ from --source; copy or clone the checkout explicitly" >&2
    exit 2
  fi
else
  INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/ares}"
  if [[ -e "$INSTALL_DIR" && ! -d "$INSTALL_DIR/.git" ]]; then
    echo "Install target exists and is not an ARES Git checkout: $INSTALL_DIR" >&2
    exit 1
  fi
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    ARES_ROOT="$(cd "$INSTALL_DIR" && pwd)"
    echo "Using existing checkout at $ARES_ROOT (no automatic reset or stash)."
  else
    command -v git >/dev/null 2>&1 || { echo "Git is required" >&2; exit 1; }
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --branch "$ARES_REF" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    ARES_ROOT="$(cd "$INSTALL_DIR" && pwd)"
  fi
fi

[[ -f "$ARES_ROOT/services/controller/fastapi_app/main.py" ]] || {
  echo "Not a current ARES checkout: $ARES_ROOT" >&2
  exit 1
}
[[ -f "$ARES_ROOT/apps/web/static/index.html" ]] || {
  echo "ARES Web package is missing from $ARES_ROOT" >&2
  exit 1
}


PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON" ]] || { echo "Python 3.11 or newer is required" >&2; exit 1; }

CONTROLLER="$ARES_ROOT/services/controller"
VENV="$CONTROLLER/.venv"

echo "Installing controller dependencies..."
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$CONTROLLER/requirements.txt"

echo "ARES WebUI is pre-built (no build step needed)."

if [[ "$(uname -s)" == "Darwin" && "$SKIP_NATIVE" == false ]]; then
  if command -v swift >/dev/null 2>&1; then
    echo "Building the macOS application..."
    (cd "$ARES_ROOT" && swift build)
  else
    echo "Swift is unavailable; skipping the optional macOS application." >&2
  fi
fi

if [[ "$NO_CLI" == false ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sfn "$ARES_ROOT/bin/ares" "$HOME/.local/bin/ares"
  echo "CLI linked at $HOME/.local/bin/ares"
fi

echo "ARES installation verified at $ARES_ROOT"
echo "State will be stored under ARES_HOME (default: $HOME/.ares)."

if [[ "$NO_START" == true ]]; then
  echo "Start later with: $ARES_ROOT/start.sh"
else
  exec "$ARES_ROOT/start.sh"
fi
