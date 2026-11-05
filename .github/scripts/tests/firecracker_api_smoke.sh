#!/usr/bin/env bash
set -euo pipefail
BINARY=${1:?firecracker path required}
TAG=${2:?exact version tag required}
WORK=$(mktemp -d /tmp/dashboard-firecracker-api.XXXXXX)
PID=
cleanup() {
  rc=$?
  trap - EXIT
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    sleep 0.1
    kill -KILL "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  if [ "$rc" -ne 0 ]; then
    for log in "$WORK"/*.log "$WORK/response.json"; do [ ! -f "$log" ] || cat "$log"; done
  fi
  rm -rf "$WORK"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
SOCKET="$WORK/api.socket"
"$BINARY" --api-sock "$SOCKET" > "$WORK/firecracker.log" 2>&1 &
PID=$!
ready=false
for i in $(seq 1 50); do
  kill -0 "$PID"
  if [ -S "$SOCKET" ]; then ready=true; break; fi
  sleep 0.1
done
[ "$ready" = true ]
request() {
  local method=$1 path=$2 expected=$3
  shift 3
  local code
  code=$(curl --silent --show-error --noproxy '*' --connect-timeout 1 --max-time 3 \
    --unix-socket "$SOCKET" -X "$method" -H 'Content-Type: application/json' \
    "$@" -o "$WORK/response.json" -w '%{http_code}' "http://localhost$path")
  [ "$code" = "$expected" ]
}
request GET /version 200
jq -e --arg expected "${TAG#v}" '.firecracker_version == $expected' "$WORK/response.json"
request GET /machine-config 200
jq -e '.vcpu_count == 1 and .mem_size_mib == 128' "$WORK/response.json"
request PUT /machine-config 204 --data '{"vcpu_count":2,"mem_size_mib":256,"smt":false}'
request GET /machine-config 200
jq -e '.vcpu_count == 2 and .mem_size_mib == 256 and .smt == false' "$WORK/response.json"
# Invalid configuration must be rejected atomically, leaving the valid state intact.
request PUT /machine-config 400 --data '{"vcpu_count":0,"mem_size_mib":256}'
jq -e '.fault_message | type == "string" and length > 0' "$WORK/response.json"
request PUT /machine-config 400 --data '{'
jq -e '.fault_message | type == "string" and length > 0' "$WORK/response.json"
request GET /machine-config 200
jq -e '.vcpu_count == 2 and .mem_size_mib == 256 and .smt == false' "$WORK/response.json"
kill -0 "$PID"
echo "Firecracker control-plane/API smoke; guest boot not tested"
