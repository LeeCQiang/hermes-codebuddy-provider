#!/bin/bash
# CodeBuddy channel guard.
#
# Designed for Hermes cron in `no_agent` mode: print nothing when healthy
# (silence == success), print an alert only when something is wrong.
#
#   0 10 * * *  script: codebuddy_guard.sh
#
# Flow: probe -> on failure refresh token and probe again -> on repeated failure
# alert, and if CodeBuddy is the active provider, switch the config back to
# FALLBACK_PROVIDER so new sessions keep working.
set -uo pipefail

CB="${CODEBUDDY_HOME:-$HOME/.hermes/codebuddy}"
COUNT_FILE="$CB/fail_count"
PY="$(command -v python3)"
FALLBACK_PROVIDER="${FALLBACK_PROVIDER:-deepseek}"
FALLBACK_MODEL="${FALLBACK_MODEL:-deepseek-chat}"
MAX_FAILS="${MAX_FAILS:-2}"

out="$("$PY" "$CB/check.py" 2>&1)"; rc=$?

if [ "$rc" -ne 0 ]; then
  # One refresh attempt before declaring the channel dead.
  "$PY" "$CB/codebuddy_login.py" refresh >/dev/null 2>&1
  out="$("$PY" "$CB/check.py" 2>&1)"; rc=$?
fi

if [ "$rc" -eq 0 ]; then
  echo 0 > "$COUNT_FILE" 2>/dev/null
  # Renew proactively when the access token has under 7 days left.
  left="$("$PY" - "$CB/credentials.json" <<'PYEOF'
import json, sys, time
try:
    c = json.load(open(sys.argv[1]))
    print(int((c.get("obtained_at", 0) + (c.get("expires_in") or 0)) - time.time()))
except Exception:
    print(0)
PYEOF
)"
  if [ "${left:-0}" -lt $((7 * 86400)) ]; then
    "$PY" "$CB/codebuddy_login.py" refresh >/dev/null 2>&1 && echo 0 > "$COUNT_FILE"
  fi
  exit 0
fi

n=$(( $(cat "$COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$COUNT_FILE" 2>/dev/null
msg="CodeBuddy channel probe failed (${n} consecutive):
$(echo "$out" | head -3)"

if [ "$n" -ge "$MAX_FAILS" ]; then
  primary="$("$PY" - <<'PYEOF'
import os, re
try:
    text = open(os.path.expanduser("~/.hermes/config.yaml"), encoding="utf-8").read()
    m = re.search(r"^model:\n(?:\s+.*\n)*?\s+provider:\s*(\S+)", text, re.M)
    print((m.group(1) if m else "").strip("'\""))
except Exception:
    print("")
PYEOF
)"
  if [ "$primary" = "codebuddy" ]; then
    hermes config set model.default "$FALLBACK_MODEL" >/dev/null 2>&1 \
      && hermes config set model.provider "$FALLBACK_PROVIDER" >/dev/null 2>&1 \
      && msg="$msg

Switched model.default back to ${FALLBACK_PROVIDER}/${FALLBACK_MODEL}.
Running sessions keep working through fallback_providers; new sessions use the
fallback directly. Restore once CodeBuddy is healthy:

  hermes config set model.default <model>; hermes config set model.provider codebuddy
  echo 0 > $COUNT_FILE"
  fi
fi

echo "$msg"
