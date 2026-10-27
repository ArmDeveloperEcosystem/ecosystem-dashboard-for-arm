#!/usr/bin/env bash
set -euo pipefail
BINARY=${1:?runsc path required}
BUSYBOX=${2:?verified static busybox path required}
[ -x "$BINARY" ]
[ -x "$BUSYBOX" ]
command -v mountpoint >/dev/null
command -v umount >/dev/null
WORK=$(mktemp -d /tmp/dashboard-gvisor-smoke.XXXXXX)
cleanup() {
  rc=$?
  trap - EXIT
  timeout --kill-after=2s 5s "$BINARY" --root="$WORK/state" delete --force dashboard-ok >/dev/null 2>&1 || true
  timeout --kill-after=2s 5s "$BINARY" --root="$WORK/state" delete --force dashboard-exit >/dev/null 2>&1 || true
  cleanup_failed=0
  # runsc keeps a bind-mounted network namespace even after its containers exit.
  if mountpoint -q -- "$WORK/state/null-netns"; then
    timeout --kill-after=2s 5s umount -- "$WORK/state/null-netns" || cleanup_failed=1
  fi
  if [ "$rc" -ne 0 ]; then
    for log in "$WORK"/*.log; do [ ! -f "$log" ] || cat "$log"; done
  fi
  rm -rf "$WORK" || cleanup_failed=1
  if [ "$rc" -eq 0 ] && [ "$cleanup_failed" -ne 0 ]; then rc=1; fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
mkdir -p "$WORK/bundle/rootfs/bin" "$WORK/bundle/rootfs/tmp" "$WORK/bundle/rootfs/proc" "$WORK/state"
cp "$BUSYBOX" "$WORK/bundle/rootfs/bin/busybox"
chmod -R a+rX "$WORK"
cd "$WORK/bundle"
timeout --kill-after=2s 10s "$BINARY" spec
# A read-only root plus a separate tmpfs tests guest writes without a host bind.
# shellcheck disable=SC2016
GUEST='test "$(/bin/busybox uname -m)" = aarch64
printf "%s" guest-data > /tmp/probe
test "$(/bin/busybox cat /tmp/probe)" = guest-data
if /bin/busybox touch /rootfs-must-stay-readonly; then exit 91; fi
printf "%s\n" GVISOR_GUEST_OK'
jq --arg guest "$GUEST" '
  .root = {path:"rootfs",readonly:true} |
  .process.terminal = false |
  .process.cwd = "/" |
  .process.args = ["/bin/busybox","sh","-ec",$guest] |
  .process.env = ["PATH=/bin","HOME=/"] |
  .mounts = [
    {destination:"/proc",type:"proc",source:"proc",options:["nosuid","noexec","nodev"]},
    {destination:"/tmp",type:"tmpfs",source:"tmpfs",options:["nosuid","nodev","mode=1777","size=16777216"]}
  ] |
  .linux.namespaces = [{type:"pid"},{type:"ipc"},{type:"uts"},{type:"mount"},{type:"network"}] |
  del(.linux.resources, .linux.cgroupsPath)
' config.json > config.new
mv config.new config.json
timeout --kill-after=3s 30s "$BINARY" --root="$WORK/state" --platform=systrap --network=none --ignore-cgroups run dashboard-ok > "$WORK/guest.log" 2>&1
grep -Fx GVISOR_GUEST_OK "$WORK/guest.log"
jq '.process.args = ["/bin/busybox","sh","-ec","printf \"%s\\n\" GVISOR_EXIT_37; exit 37"]' config.json > config.new
mv config.new config.json
rc=0
timeout --kill-after=3s 30s "$BINARY" --root="$WORK/state" --platform=systrap --network=none --ignore-cgroups run dashboard-exit > "$WORK/exit.log" 2>&1 || rc=$?
[ "$rc" -eq 37 ]
grep -Fx GVISOR_EXIT_37 "$WORK/exit.log"
echo "gVisor systrap OCI guest: marker, tmpfs read/write, read-only root, and exit 37 verified."
