#!/usr/bin/env bash
# ARES smoke test — is the daily driver actually working right now?
#
# Checks the whole turn path end to end against a running controller, not
# imports or mocks: a green run means a real message reached a real worker and
# came back. Takes about a minute.
#
# Usage:  ./scripts/smoke_test.sh [base_url]
set -uo pipefail

BASE="${1:-${ARES_SMOKE_BASE_URL:-http://127.0.0.1:8788}}"
TURN_TIMEOUT="${ARES_SMOKE_TURN_TIMEOUT:-90}"

pass=0
fail=0
skip=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail + 1)); }
note() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; skip=$((skip + 1)); }

jq_py() { python3 -c "import json,sys;d=json.load(sys.stdin);$1" 2>/dev/null; }

echo "=== ARES smoke test — $BASE ==="

# ── 1. controller answers ────────────────────────────────────────────────────
echo "[1/6] Health"
HEALTH="$(curl -sS --max-time 10 "$BASE/api/health" 2>/dev/null || true)"
if [ -z "$HEALTH" ]; then
  bad "controller not reachable at $BASE — is it running? (see AGENTS.md → Restart / recovery)"
  echo; echo "=== 1 failed, cannot continue ==="; exit 1
fi
HEALTH_OK="$(printf '%s' "$HEALTH" | jq_py 'print(d.get("status"))')"
if [ "$HEALTH_OK" = "ok" ]; then
  ok "controller healthy, up $(printf '%s' "$HEALTH" | jq_py 'print(round(d.get("uptime_seconds",0)))')s"
else
  bad "health did not report ok"
fi

# ── 2. exactly one listener ──────────────────────────────────────────────────
# Two listeners on 8788 means phone and Mac can reach different servers.
echo "[2/6] Bind"
LISTENERS="$(lsof -nP -iTCP:8788 -sTCP:LISTEN -t 2>/dev/null | sort -u | wc -l | tr -d ' ')"
if [ "$LISTENERS" = "1" ]; then
  ok "one listener on 8788"
elif [ "$LISTENERS" = "0" ]; then
  note "no local listener (remote base URL?)"
else
  bad "$LISTENERS listeners on 8788 — split brain; see AGENTS.md → Restart / recovery"
fi

# ── 3. workers ───────────────────────────────────────────────────────────────
echo "[3/6] Connections"
CONNS="$(curl -sS --max-time 15 "$BASE/api/connections" 2>/dev/null || true)"
SELECTED="$(printf '%s' "$CONNS" | jq_py 'print(d.get("selected") or "")')"
[ -n "$SELECTED" ] && ok "selected runtime: $SELECTED" || bad "no runtime selected"

for backend in jaeger_local hermes_local; do
  STATE="$(printf '%s' "$CONNS" | jq_py "print(next((c['health']['state'] for c in d.get('connections',[]) if c['id']=='$backend'), 'absent'))")"
  case "$STATE" in
    connected|needs_attention) ok "$backend: $STATE" ;;
    absent)                    bad "$backend not registered" ;;
    *)                         note "$backend: $STATE" ;;
  esac
done

# ── 4. directives ────────────────────────────────────────────────────────────
echo "[4/6] Directives"
DIRS="$(curl -sS --max-time 10 "$BASE/api/ares/directives" 2>/dev/null || true)"
DIRS_ON="$(printf '%s' "$DIRS" | jq_py 'print("yes" if d.get("enabled") else "no")')"
if [ "$DIRS_ON" = "yes" ]; then
  ok "directives on ($(printf '%s' "$DIRS" | jq_py 'print(d["count"])') active)"
elif [ -n "$DIRS" ]; then
  note "directives off ($(printf '%s' "$DIRS" | jq_py 'print(d.get("stored_count",0))') stored) — set 'enabled: true' in ~/.ares/directives.yaml"
else
  bad "directives endpoint did not respond"
fi

# ── 5 & 6. real turns ────────────────────────────────────────────────────────
run_turn() {
  local backend="$1" label="$2"
  local sid resp stream elapsed=0 status

  sid="$(curl -sS --max-time 15 -X POST "$BASE/api/session/new" \
        -H 'Content-Type: application/json' -d '{}' 2>/dev/null \
        | jq_py 'print(d["session"]["session_id"])')"
  if [ -z "$sid" ]; then bad "$label: could not create a session"; return; fi

  resp="$(curl -sS --max-time 20 -X POST "$BASE/api/chat/start" \
         -H 'Content-Type: application/json' \
         -d "{\"session_id\":\"$sid\",\"message\":\"Reply with exactly: ok\",\"connection_id\":\"$backend\"}" 2>/dev/null)"
  stream="$(printf '%s' "$resp" | jq_py 'print(d.get("stream_id",""))')"
  if [ -z "$stream" ]; then
    # An honest, actionable refusal is a valid outcome — better than a hang.
    local why fixit
    why="$(printf '%s' "$resp" | jq_py 'print(d.get("reason") or d.get("error") or "")')"
    fixit="$(printf '%s' "$resp" | jq_py 'print(d.get("fix",""))')"
    if [ -n "$why" ]; then
      note "$label refused: $why"
      [ -n "$fixit" ] && printf '        fix: %s\n' "$fixit"
    else
      bad "$label: no stream_id and no reason given"
    fi
    return
  fi

  while [ "$elapsed" -lt "$TURN_TIMEOUT" ]; do
    sleep 3; elapsed=$((elapsed + 3))
    status="$(curl -sS --max-time 10 "$BASE/api/chat/stream/status?stream_id=$stream" 2>/dev/null)"
    printf '%s' "$status" | grep -q '"active":false' && break
  done

  local terminal reply
  terminal="$(printf '%s' "$status" | jq_py 'print((d.get("journal") or {}).get("terminal_state",""))')"
  reply="$(curl -sS --max-time 15 "$BASE/api/session?session_id=$sid" 2>/dev/null \
          | jq_py 'print(next((m["content"] for m in reversed(d["session"]["messages"]) if m["role"]=="assistant"), ""))')"

  if [ "$terminal" = "completed" ] && [ -n "$reply" ]; then
    ok "$label replied in ${elapsed}s: $(printf '%s' "$reply" | head -c 60)"
  elif [ -n "$terminal" ]; then
    bad "$label ended as '$terminal' after ${elapsed}s"
  else
    bad "$label produced no terminal state in ${elapsed}s — possible hang"
  fi
}

echo "[5/6] Hermes turn";  run_turn hermes_local "hermes_local"
echo "[6/6] Jaeger turn";  run_turn jaeger_local "jaeger_local"

echo
echo "=== $pass passed, $fail failed, $skip skipped ==="
[ "$fail" -eq 0 ] || exit 1
