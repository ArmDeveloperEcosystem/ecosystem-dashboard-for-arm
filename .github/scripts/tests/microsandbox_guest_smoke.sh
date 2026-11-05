#!/usr/bin/env bash
# Exact local guest probes used by test-microsandbox.yml; no cloud backend or KVM bypass.
set -euo pipefail

preflight() {
  test "$(uname -s)" = Linux
  test "$(uname -m)" = aarch64
  if ! test -c /dev/kvm || ! test -r /dev/kvm || ! test -w /dev/kvm; then
    echo "ERROR: usable /dev/kvm required; Microsandbox guest execution NOT tested." >&2
    return 1
  fi
  python3 - <<'PY'
import fcntl
import os
fd = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
try:
    if fcntl.ioctl(fd, 0xAE00, 0) != 12:
        raise RuntimeError("Unexpected KVM API version")
    vm = fcntl.ioctl(fd, 0xAE01, 0)
    os.close(vm)
finally:
    os.close(fd)
PY
}
MODE=${1:-guest}
case "$MODE" in
  preflight|guest|exit-status|lifecycle) ;;
  *) echo "Usage: bash microsandbox_guest_smoke.sh [preflight|guest|exit-status|lifecycle]" >&2; exit 2 ;;
esac
preflight
export MSB_BACKEND=local
: "${MSB_PATH:?Set to the pinned msb executable}"
: "${MSB_LIBKRUNFW_PATH:?Set to matching bundled firmware}"
: "${MSB_HOME:?Set to a fresh absolute disposable directory}"
: "${RUNNER_TEMP:?Set to an absolute disposable scratch directory}"
IMAGE=docker.io/library/alpine@sha256:24bb3511a0db7b5114a4aee033c65a8a4148f39b7b80a398e548546db967a36f
if [ "$MODE" = preflight ]; then
  timeout -k 5s 30s "$MSB_PATH" doctor
  exit
fi
WORK=$(mktemp -d "$RUNNER_TEMP/microsandbox-guest.XXXXXX")
NAME="arm-smoke-${WORK##*.}"
OWNED=0
cleanup() {
  local rc=$?
  trap - EXIT
  if [ "$OWNED" -eq 1 ]; then
    if ! timeout -k 5s 30s "$MSB_PATH" rm --force "$NAME" >/dev/null 2>&1; then
      echo "ERROR: failed to remove owned sandbox $NAME" >&2
      if [ "$rc" -eq 0 ]; then rc=1; fi
    fi
  fi
  if ! rm -rf "$WORK"; then
    echo "ERROR: failed to remove scratch directory $WORK" >&2
    if [ "$rc" -eq 0 ]; then rc=1; fi
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Named runs allow deterministic cleanup even if a detached runtime outlives the CLI timeout.
OWNED=1
case "$MODE" in
  guest)
    timeout -k 5s 240s "$MSB_PATH" run --name "$NAME" --no-tty --no-stdin --cpus 1 --memory 512M \
      --entrypoint /bin/sh "$IMAGE" -- -ec \
      'test "$(uname -m)" = aarch64; printf arm-smoke > /tmp/probe; test "$(cat /tmp/probe)" = arm-smoke; echo MICROSANDBOX_ARM64_OK' \
      | tee "$WORK/guest.log"
    grep -Fx MICROSANDBOX_ARM64_OK "$WORK/guest.log"
    ;;
  exit-status)
    set +e
    timeout -k 5s 120s "$MSB_PATH" run --name "$NAME" --no-tty --no-stdin --entrypoint /bin/sh "$IMAGE" -- -c 'exit 23'
    RC=$?
    set -e
    test "$RC" -eq 23
    echo MICROSANDBOX_EXIT_STATUS_OK
    ;;
  lifecycle)
    timeout -k 5s 180s "$MSB_PATH" create --name "$NAME" --cpus 1 --memory 512M "$IMAGE"
    timeout -k 5s 30s "$MSB_PATH" exec "$NAME" -- /bin/sh -ec 'printf persisted > /tmp/lifecycle'
    timeout -k 5s 30s "$MSB_PATH" exec "$NAME" -- /bin/sh -ec \
      'test "$(cat /tmp/lifecycle)" = persisted; echo MICROSANDBOX_LIFECYCLE_OK' \
      | tee "$WORK/lifecycle.log"
    grep -Fx MICROSANDBOX_LIFECYCLE_OK "$WORK/lifecycle.log"
    timeout -k 5s 30s "$MSB_PATH" stop "$NAME"
    ;;
  *)
    echo "Usage: bash microsandbox_guest_smoke.sh [preflight|guest|exit-status|lifecycle]" >&2
    exit 2
    ;;
esac
