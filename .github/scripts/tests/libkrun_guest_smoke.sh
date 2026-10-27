#!/usr/bin/env bash
# Exact local guest probe used by test-libkrun.yml. Run only on a disposable native Arm64 host.
set -euo pipefail

preflight() {
  test "$(uname -s)" = Linux
  test "$(uname -m)" = aarch64
  if ! test -c /dev/kvm || ! test -r /dev/kvm || ! test -w /dev/kvm; then
    echo "ERROR: usable /dev/kvm required; libkrun guest execution NOT tested." >&2
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

case "${1:-guest}" in
  preflight) preflight; exit ;;
  guest) preflight ;;
  *) echo "Usage: bash libkrun_guest_smoke.sh [preflight|guest]" >&2; exit 2 ;;
esac

: "${LIBKRUN_PREFIX:?Set to the installed pinned libkrun prefix}"
: "${LIBKRUNFW_DIR:?Set to the directory containing pinned libkrunfw.so.5}"
: "${RUNNER_TEMP:?Set to an absolute disposable scratch directory}"
export LD_LIBRARY_PATH="$LIBKRUN_PREFIX/lib64:$LIBKRUNFW_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PKG_CONFIG_PATH="$LIBKRUN_PREFIX/lib64/pkgconfig"
IMAGE=docker.io/library/alpine@sha256:24bb3511a0db7b5114a4aee033c65a8a4148f39b7b80a398e548546db967a36f
WORK=$(mktemp -d "$RUNNER_TEMP/libkrun-guest.XXXXXX")
CONTAINER="libkrun-smoke-${WORK##*.}"
CONTAINER_CREATED=0
cleanup() {
  local rc=$?
  trap - EXIT
  if [ "$CONTAINER_CREATED" -eq 1 ]; then
    if ! timeout -k 5s 15s docker rm -f "$CONTAINER" >/dev/null 2>&1; then
      echo "ERROR: failed to remove owned container $CONTAINER" >&2
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
mkdir "$WORK/rootfs"
timeout -k 5s 180s docker pull --platform linux/arm64 "$IMAGE"
# Track the unique name before create so timeout cannot lose a partially created container.
CONTAINER_CREATED=1
timeout -k 5s 30s docker create --name "$CONTAINER" --platform linux/arm64 "$IMAGE" /bin/true
timeout -k 5s 30s docker export "$CONTAINER" | tar --no-same-owner -xf - -C "$WORK/rootfs"
timeout -k 5s 15s docker rm "$CONTAINER"
CONTAINER_CREATED=0

cat > "$WORK/guest.c" <<'C'
#include <sys/types.h>
#include <libkrun.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static void ok(int32_t rc, const char *name) {
    if (rc < 0) {
        fprintf(stderr, "%s failed: %d\n", name, rc);
        exit(1);
    }
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int32_t ctx = krun_create_ctx();
    ok(ctx, "create context");
    ok(krun_set_vm_config((uint32_t)ctx, 1, 256), "set config");
    ok(krun_set_root((uint32_t)ctx, argv[1]), "set root");
    ok(krun_set_workdir((uint32_t)ctx, "/"), "set workdir");
    const char *args[] = {"-ec", argv[2], NULL};
    const char *env[] = {"PATH=/bin:/usr/bin", NULL};
    ok(krun_set_exec((uint32_t)ctx, "/bin/sh", args, env), "set exec");
    int32_t rc = krun_start_enter((uint32_t)ctx);
    fprintf(stderr, "krun_start_enter unexpectedly returned: %d\n", rc);
    return 1;
}
C
timeout -k 5s 60s cc -std=c11 -Wall -Wextra -Werror "$WORK/guest.c" \
  $(pkg-config --cflags --libs libkrun) -o "$WORK/guest"
timeout -k 5s 90s "$WORK/guest" "$WORK/rootfs" \
  'test "$(uname -m)" = aarch64; printf libkrun-guest > /tmp/probe; test "$(cat /tmp/probe)" = libkrun-guest; echo LIBKRUN_GUEST_OK' \
  | tee "$WORK/output"
grep -Fx LIBKRUN_GUEST_OK "$WORK/output"
set +e
timeout -k 5s 90s "$WORK/guest" "$WORK/rootfs" 'exit 23'
RC=$?
set -e
test "$RC" -eq 23
echo LIBKRUN_GUEST_EXIT_STATUS_OK
