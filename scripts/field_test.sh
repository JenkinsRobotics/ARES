#!/usr/bin/env bash
# ARES/Jaeger field test — bounded, isolated release qualification.
#
# Every stage runs under a deadline in its own process group (see
# scripts/lib/field_stage.py) and appends a machine-readable record to
# report.jsonl, so a run is auditable after the fact rather than only
# watchable while it happens.
#
# ISOLATION IS THE POINT. A field test that runs against the operator's
# live ~/.ares, live instance or live port is not a test, it is an
# outage — so this script allocates a temp home per run, asks the kernel
# for a free port, and REFUSES TO START if any of that resolves onto
# something real. There is no flag to skip the guard.
#
# Usage:
#   ./scripts/field_test.sh                 # all implemented stages
#   ./scripts/field_test.sh 01 02           # only these stages
#   ./scripts/field_test.sh --list          # what exists and what does not
#
# Env:
#   JAEGER_REPO   path to the JaegerAI checkout (default: ../JaegerAI)
#   FIELD_KEEP    set to 1 to keep the temp run dir for inspection

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAEGER_REPO="${JAEGER_REPO:-$HOME/GitHub/JaegerAI}"
STAGE_RUNNER="$REPO_ROOT/scripts/lib/field_stage.py"
# Committed, not local state: budgets move through review, and a stage that
# starts needing twice as long shows up as a diff.
BASELINE="$REPO_ROOT/scripts/field_baseline.json"
GROW=""
RECORD_BASELINE=""

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'
c_dim=$'\033[2m';  c_bold=$'\033[1m'; c_off=$'\033[0m'

die() { printf '%sABORT%s  %s\n' "$c_red" "$c_off" "$1" >&2; exit 2; }

# ── isolation ───────────────────────────────────────────────────────────
# Deliberately /tmp and deliberately short. macOS caps AF_UNIX paths at
# 104 bytes, and the bridge's attach socket lives at
# <instance>/run/bridge.sock — under the default $TMPDIR
# (/var/folders/<hash>/T/...) that budget is already spent before the
# instance dir is appended, so the bridge logs "attach socket skipped:
# AF_UNIX path too long" and the stage silently stops covering attach at
# all. Production is 79 bytes and fine; only the harness was at risk of
# testing a degraded configuration and calling it a pass.
RUN_DIR="$(mktemp -d "/tmp/aresft.XXXXXX")" || die "mktemp failed"
export ARES_HOME="$RUN_DIR/ares-home"
export JAEGER_INSTANCE_DIR="$RUN_DIR/jaeger-instance"
mkdir -p "$ARES_HOME" "$JAEGER_INSTANCE_DIR" "$RUN_DIR/logs"
REPORT="$RUN_DIR/report.jsonl"

ARES_WEBUI_PORT="$(python3 -c 'import sys;sys.path.insert(0,"'"$REPO_ROOT"'/scripts/lib");import field_stage;print(field_stage.free_port())')" \
  || die "could not allocate a port"
export ARES_WEBUI_PORT

# The guard. Each of these has a real failure mode behind it.
[ -n "${ARES_HOME:-}" ] || die "ARES_HOME unset"
case "$ARES_HOME" in
  "$HOME/.ares"|"$HOME/.ares/"*) die "ARES_HOME resolved onto the live install" ;;
esac
case "$JAEGER_INSTANCE_DIR" in
  "$JAEGER_REPO/.jaeger_ai"*) die "JAEGER_INSTANCE_DIR resolved onto the live instance" ;;
esac
[ "$ARES_WEBUI_PORT" != "8788" ] || die "allocator handed back the production port"
if lsof -nP -iTCP:"$ARES_WEBUI_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  die "port $ARES_WEBUI_PORT is already in use"
fi

cleanup() {
  if [ "${FIELD_KEEP:-0}" = "1" ]; then
    printf '%srun dir kept: %s%s\n' "$c_dim" "$RUN_DIR" "$c_off"
  else
    rm -rf "$RUN_DIR"
  fi
}
trap cleanup EXIT

# ── stage table ─────────────────────────────────────────────────────────
# name|timeout|implemented|description
STAGES=(
  "01-static|60|300|yes|static checks (compileall)"
  "02-unit|300|3600|yes|controller unit tests"
  "03-protocol|60|300|yes|cross-language protocol fixtures"
  "04-bridge-lifecycle|60|180|yes|clean bridge boot/query/quit under a deadline"
  "05-ares-http|120|300|yes|controller boot + /health + shutdown on an isolated port"
  "06-model-turn|300|1800|no|real local model turn"
  "07-tool-exec|120|300|no|native tool execution"
  "08-cancel|60|180|no|cancellation and timeout"
  "09-crash-recovery|120|300|no|stale pid/lock/socket recovery"
  "10-restart|120|300|no|restart and persistence"
  "11-privacy|60|180|no|permissions and privacy"
  "12-clean-install|300|1800|yes|install and boot from the committed source artifact"
)

if [ "${1:-}" = "--list" ]; then
  printf '%sfield-test stages%s\n' "$c_bold" "$c_off"
  for row in "${STAGES[@]}"; do
    IFS='|' read -r n fl ce impl desc <<<"$row"
    if [ "$impl" = yes ]; then mark="${c_grn}impl${c_off}"; else mark="${c_yel}TODO${c_off}"; fi
    earned="$(python3 - "$BASELINE" "$n" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
v=d.get(sys.argv[2],{}).get("seconds")
print(f"{v:.1f}s observed" if isinstance(v,(int,float)) else "never passed")
PY
)"
    printf '  %-22s %-14s %s  %-52s %s\n' "$n" "${fl}-${ce}s" "$mark" "$desc" "$c_dim$earned$c_off"
  done
  exit 0
fi

ARGS=()
for a in "$@"; do
  case "$a" in
    --grow) GROW=1 ;;          # let a timed-out stage earn one longer retry
    --record-baseline) RECORD_BASELINE=1 ;;
    *) ARGS+=("$a") ;;
  esac
done
WANTED=("${ARGS[@]}")
want() {
  [ ${#WANTED[@]} -eq 0 ] && return 0
  for w in "${WANTED[@]}"; do case "$1" in "$w"*) return 0 ;; esac; done
  return 1
}

stage() {  # stage <name> <floor> <ceiling> <cwd> -- cmd...
  local name="$1" floor="$2" ceil="$3" cwd="$4"; shift 5
  printf '\n%s▸ %s%s\n' "$c_bold" "$name" "$c_off"
  python3 "$STAGE_RUNNER" --name "$name" --floor "$floor" --ceiling "$ceil" \
      --baseline "$BASELINE" ${GROW:+--grow} \
      ${RECORD_BASELINE:+--record-baseline} \
      --cwd "$cwd" --log "$RUN_DIR/logs/$name.log" --report "$REPORT" -- "$@"
}

printf '%sARES/Jaeger field test%s\n' "$c_bold" "$c_off"
printf '  run dir   %s\n  port      %s\n  ares home %s\n  instance  %s\n' \
  "$RUN_DIR" "$ARES_WEBUI_PORT" "$ARES_HOME" "$JAEGER_INSTANCE_DIR"

CTL="$REPO_ROOT/services/controller"
PY="$CTL/.venv/bin/python"
[ -x "$PY" ] || die "controller venv missing: $PY"

want 01 && stage "01-static" 60 300 "$CTL" -- \
  "$PY" -m compileall -q cli fastapi_app api

want 02 && stage "02-unit" 300 3600 "$CTL" -- \
  "$PY" -m pytest tests -q --no-header

want 03 && stage "03-protocol" 60 300 "$JAEGER_REPO" -- \
  "$JAEGER_REPO/.venv/bin/python" -m pytest dev/tests/jaeger_ai/interfaces -q --no-header

want 04 && stage "04-bridge-lifecycle" 60 180 "$JAEGER_REPO" -- \
  "$JAEGER_REPO/.venv/bin/python" "$REPO_ROOT/scripts/lib/field_bridge_probe.py"

want 05 && stage "05-ares-http" 120 300 "$CTL" -- \
  "$PY" "$REPO_ROOT/scripts/lib/field_http_probe.py"

want 12 && stage "12-clean-install" 300 1800 "$REPO_ROOT" -- \
  bash "$REPO_ROOT/scripts/smoke_clean_install.sh"

# ── report ──────────────────────────────────────────────────────────────
printf '\n%ssummary%s\n' "$c_bold" "$c_off"
python3 - "$REPORT" <<'PYEOF'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print("  no stages ran"); raise SystemExit(0)
recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
worst = 0
for r in recs:
    mark = {"pass": "\033[32mPASS\033[0m", "fail": "\033[31mFAIL\033[0m",
            "timeout": "\033[31mTIMEOUT\033[0m"}[r["status"]]
    print(f"  {mark}  {r['stage']:<22} {r['seconds']:>7.2f}s  rc={r['exit_code']}")
    if r["status"] != "pass":
        worst = 1
print(f"\n  {len(recs)} stage(s); "
      f"{sum(1 for r in recs if r['status']=='pass')} passed")
raise SystemExit(worst)
PYEOF
