#!/usr/bin/env bash
set -euo pipefail

# These are measured hashes of exact upstream CI objects, not publisher signatures.
ARTIFACT_BASE=https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/20261021-1e5fcc27b59f-0/aarch64
KERNEL_SHA256=8bc7fc7d1eabc0dd7dd8a33cb53b0bb11f25c09d4276757cfe16eb5c8509fa90
ROOTFS_SHA256=490be704c18868cde014fbdf4e025a1548bd3efe23bff5086becdf43d6fb05ad

validate_guest_log() {
  local log=$1 rc=$2 normalized
  [ "$rc" -eq 0 ] || return 1
  # Linux serial consoles can translate newlines to CRLF.
  normalized=$(tr -d '\r' < "$log")
  grep -Fx FIRECRACKER_GUEST_FILE_IO_OK <<< "$normalized" || return 1
  grep -Fx FIRECRACKER_GUEST_CHILD_EXIT_37 <<< "$normalized" || return 1
  grep -Fx FIRECRACKER_GUEST_REBOOT <<< "$normalized" || return 1
  ! grep -Eq 'Kernel panic|FIRECRACKER_GUEST_FAILED' <<< "$normalized"
}

main() {
  local binary=${1:?firecracker path required} tag=${2:-v1.17.0}
  [ "$(uname -s)" = Linux ]
  [ "$(uname -m)" = aarch64 ]
  [ "$(getconf PAGESIZE)" = 4096 ]
  # Fail before downloads on hosted runners without KVM; never use an API-only fallback.
  [ -c /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ] || {
    echo "Guest boot NOT TESTED: usable /dev/kvm is mandatory." >&2
    return 1
  }
  python3 - <<'PY'
import fcntl
import os
fd = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
try:
    assert fcntl.ioctl(fd, 0xAE00, 0) == 12, "Unexpected KVM API version"
finally:
    os.close(fd)
PY
  [ "$(bash "$(dirname "${BASH_SOURCE[0]}")/firecracker_version.sh" "$binary" Firecracker "$tag")" = "$tag" ]
  WORK=$(mktemp -d /tmp/dashboard-firecracker-guest.XXXXXX)
  cleanup_guest() {
    rc=$?
    trap - EXIT
    if [ "$rc" -ne 0 ]; then
      [ ! -f "$WORK/serial.log" ] || cat "$WORK/serial.log"
    fi
    rm -rf "$WORK"
    exit "$rc"
  }
  trap cleanup_guest EXIT
  trap 'exit 143' TERM
  trap 'exit 130' INT
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 120 \
    "$ARTIFACT_BASE/vmlinux-6.1.188" -o "$WORK/vmlinux-6.1.188"
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 120 \
    "$ARTIFACT_BASE/initramfs.cpio" -o "$WORK/upstream-initramfs.cpio"
  printf '%s  %s\n' "$KERNEL_SHA256" "$WORK/vmlinux-6.1.188" \
    "$ROOTFS_SHA256" "$WORK/upstream-initramfs.cpio" | sha256sum -c -
  mkdir "$WORK/rootfs"
  (cd "$WORK/rootfs" && cpio -idmu --no-absolute-filenames < "$WORK/upstream-initramfs.cpio")
  # Replace only the init program in the checksum-verified BusyBox initramfs.
  python3 - "$WORK" <<'PY'
import json
from pathlib import Path
import shutil
import sys

work = Path(sys.argv[1])
root = work / "rootfs"
shutil.copyfile(root / "bin/sh", root / "bin/busybox")
(root / "bin/busybox").chmod(0o755)
init = root / "init"
init.write_text("""#!/bin/sh
set -eu
/bin/busybox mount -t devtmpfs devtmpfs /dev
exec 0</dev/console
exec 1>/dev/console
exec 2>/dev/console
/bin/busybox mount -t proc proc /proc
test "$(/bin/busybox uname -m)" = aarch64
printf "%s" arm64-guest-data > /guest-probe
test "$(/bin/busybox cat /guest-probe)" = arm64-guest-data
printf "%s\\n" FIRECRACKER_GUEST_FILE_IO_OK
rc=0
/bin/sh -c 'exit 37' || rc=$?
test "$rc" -eq 37
printf "%s\\n" FIRECRACKER_GUEST_CHILD_EXIT_37
/bin/busybox sync
printf "%s\\n" FIRECRACKER_GUEST_REBOOT
/bin/busybox reboot -f
while :; do /bin/busybox sleep 1; done
""")
init.chmod(0o755)
config = {
    "boot-source": {
        "kernel_image_path": str(work / "vmlinux-6.1.188"),
        "initrd_path": str(work / "smoke-initramfs.cpio"),
        "boot_args": "console=ttyS0 keep_bootcon reboot=k panic=1 pci=off rdinit=/init",
    },
    "machine-config": {"vcpu_count": 1, "mem_size_mib": 256, "smt": False},
}
(work / "vm.json").write_text(json.dumps(config))
PY
  (cd "$WORK/rootfs" && find . -print0 | LC_ALL=C sort -z | cpio --null -o --format=newc --reproducible > "$WORK/smoke-initramfs.cpio")
  sha256sum "$WORK/vmlinux-6.1.188" "$WORK/upstream-initramfs.cpio" "$WORK/smoke-initramfs.cpio"
  bash "$(dirname "${BASH_SOURCE[0]}")/firecracker_api_smoke.sh" "$binary" "$tag"
  rc=0
  timeout --kill-after=5s 60s "$binary" --no-api --config-file "$WORK/vm.json" > "$WORK/serial.log" 2>&1 || rc=$?
  validate_guest_log "$WORK/serial.log" "$rc"
  echo "Firecracker Arm64 KVM guest boot, guest file I/O, child exit 37 and clean VMM shutdown verified."
  echo "Guest child exit is verified in-guest; it is not a VMM exit-code-37 claim. Jailer isolation is not tested."
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
