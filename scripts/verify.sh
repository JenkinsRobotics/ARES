#!/usr/bin/env bash
# ARES local verification — the gate that should have run before those commits.
#
# Phase 0 finding F1: local `main` sits 86 commits ahead of origin/main, and
# none of those commits triggered ci.yml, tests.yml or browser-smoke.yml —
# every one of those workflows fires on `push to main` or on a pull request,
# and the work never went through either. The gates were not weak; they were
# never invoked. This script is what makes running them locally cheap enough
# that there is no excuse.
#
#   ./scripts/verify.sh          fast gate  — syntax, lint, architecture, unit
#   ./scripts/verify.sh --full   everything — adds the full pytest suite
#   ./scripts/verify.sh --list   show what each mode runs, run nothing
#
# The fast gate needs NO credentials, NO network and NO Docker, and is meant
# to stay under a couple of minutes. --full runs the ~5,600-test suite and
# takes about eight.
#
# Deliberately NOT a superset of CI: browser-smoke needs Playwright browsers
# and docker-smoke needs a Docker daemon. Both are named at the end so it is
# obvious what this does not cover, rather than implying a green run here
# means CI is green.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROLLER="${ROOT}/services/controller"
VENV_PY="${CONTROLLER}/.venv/bin/python"

MODE="fast"
case "${1:-}" in
  --full) MODE="full" ;;
  --list) MODE="list" ;;
  "")     MODE="fast" ;;
  *)      echo "usage: $0 [--full|--list]" >&2; exit 2 ;;
esac

if [[ "${MODE}" == "list" ]]; then
  cat <<'EOF'
fast (default)
  1. python syntax      compileall over api, fastapi_app, cli, scripts, tests,
                        AND core, integrations, tools — the last three are the
                        ones CI still misses (finding F6).
  2. ruff               curated E9+F+B ruleset, whole tree, report-only
  3. architecture       .github/scripts/check-source-ownership.sh
  4. si_doctor          17 SI wiring assertions
  5. unit tests         pytest -m "not slow" over services/controller/tests

full
  everything above, plus the complete pytest suite (~5,600 tests, ~8 min)

not covered here (needs external deps)
  browser-smoke.yml     Playwright + Chromium
  docker-smoke.yml      a live Docker daemon
  ci.yml                swift build (macOS + Xcode)
EOF
  exit 0
fi

if [[ ! -x "${VENV_PY}" ]]; then
  echo "FAIL: ${VENV_PY} not found. Run services/controller/scripts/test.sh once to build it." >&2
  exit 1
fi

FAILED=()
run_step() {
  local name="$1"; shift
  printf '\n\033[1m── %s ─────────────────────────────────────────\033[0m\n' "${name}"
  if "$@"; then
    printf '\033[32mok\033[0m  %s\n' "${name}"
  else
    printf '\033[31mFAIL\033[0m %s\n' "${name}"
    FAILED+=("${name}")
  fi
}

# 1. Syntax. The compileall list in tests.yml stops at services/controller;
#    core/, integrations/ and tools/ hold ~18k lines of authoritative code that
#    no syntax gate currently reads (F6). Cover them here.
run_step "python syntax" bash -c "
  cd '${CONTROLLER}' && '${VENV_PY}' -m compileall -q api fastapi_app bootstrap.py mcp_server.py cli tests scripts &&
  cd '${ROOT}'       && '${VENV_PY}' -m compileall -q core integrations tools"

# 2. Lint. Report-only, matching CI's whole-tree job — the blocking gate there
#    is diff-scoped against origin/main, which is meaningless on a branch that
#    has diverged by 86 commits.
run_step "ruff (report)" bash -c "cd '${CONTROLLER}' && '${VENV_PY}' scripts/ruff_lint.py --all || true"

# 3. Architecture boundaries.
run_step "source ownership" bash "${ROOT}/.github/scripts/check-source-ownership.sh"

# 4. SI wiring.
run_step "si_doctor" bash -c "cd '${CONTROLLER}' && '${VENV_PY}' scripts/si_doctor.py"

# 5. Tests.
if [[ "${MODE}" == "full" ]]; then
  run_step "pytest (full suite)" bash -c "cd '${CONTROLLER}' && '${VENV_PY}' -m pytest tests -q"
else
  run_step "pytest (fast)" bash -c "cd '${CONTROLLER}' && '${VENV_PY}' -m pytest tests -q -m 'not slow' -x -q"
fi

printf '\n\033[1m═══ summary ═══\033[0m\n'
if (( ${#FAILED[@]} == 0 )); then
  echo "all checks passed (${MODE} mode)"
  echo "not covered: browser-smoke (Playwright), docker-smoke (Docker), swift build"
  exit 0
fi
printf 'failed: %s\n' "${FAILED[*]}"
exit 1
