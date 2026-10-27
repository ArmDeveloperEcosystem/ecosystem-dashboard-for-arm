#!/usr/bin/env bash
set -euo pipefail

require_arm() {
  test "$(uname -s)" = Linux
  test "$(uname -m)" = aarch64
}

build_release() {
  local version=$1 digest=$2 prefix=$3 archive
  archive="$prefix/source.tar.xz"
  mkdir -p "$prefix/source"
  curl --fail --location --proto '=https' --proto-redir '=https' \
    --tlsv1.2 --retry 3 --connect-timeout 20 --max-time 180 \
    "https://github.com/containers/bubblewrap/releases/download/v${version}/bubblewrap-${version}.tar.xz" \
    --output "$archive"
  printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --strict
  tar --extract --xz --file "$archive" --strip-components=1 --directory "$prefix/source"
  meson setup "$prefix/build" "$prefix/source" -Dman=disabled -Dtests=true \
    -Dselinux=disabled -Dbash_completion=disabled -Dzsh_completion=disabled
  meson compile -C "$prefix/build"
  test -x "$prefix/build/bwrap"
  test "$("$prefix/build/bwrap" --version)" = "bubblewrap $version"
  readelf -h "$prefix/build/bwrap" | grep -Eq 'Machine:[[:space:]]+AArch64'
}

sandbox() {
  local binary=$1
  shift
  timeout --kill-after=5s 30s "$binary" --unshare-user --unshare-pid \
    --unshare-net --new-session --die-with-parent --ro-bind / / \
    --proc /proc --dev /dev --tmpfs /tmp "$@"
}

execution_probe() {
  local binary=$1 work
  work=$(mktemp -d "${RUNNER_TEMP:?}/bwrap-execution.XXXXXX")
  # shellcheck disable=SC2016 -- Commands expand inside the sandbox shell.
  sandbox "$binary" /bin/sh -ec \
    'test "$(uname -m)" = aarch64; printf arm64-probe > /tmp/probe; test "$(cat /tmp/probe)" = arm64-probe; echo BWRAP_EXECUTION_OK' \
    > "$work/output"
  grep -Fxq BWRAP_EXECUTION_OK "$work/output"
  local code=0
  sandbox "$binary" /bin/sh -c 'exit 23' > "$work/nonzero.log" 2>&1 || code=$?
  test "$code" -eq 23
}

readonly_probe() {
  local binary=$1 work
  work=$(mktemp -d "${RUNNER_TEMP:?}/bwrap-readonly.XXXXXX")
  printf protected > "$work/protected"
  # shellcheck disable=SC2016 -- Positional arguments belong to the sandbox shell.
  sandbox "$binary" /bin/sh -ec \
    'test "$(cat "$1")" = protected; if printf changed > "$1"; then exit 1; fi; test "$(cat "$1")" = protected; echo BWRAP_READONLY_OK' \
    sh "$work/protected" > "$work/output" 2> "$work/denial.log"
  grep -Fxq BWRAP_READONLY_OK "$work/output"
  test "$(cat "$work/protected")" = protected
}

namespace_probe() {
  local binary=$1 work host_pid host_net
  work=$(mktemp -d "${RUNNER_TEMP:?}/bwrap-namespaces.XXXXXX")
  host_pid=$(readlink /proc/self/ns/pid)
  host_net=$(readlink /proc/self/ns/net)
  # shellcheck disable=SC2016 -- Read namespace identifiers inside the sandbox.
  sandbox "$binary" /bin/sh -ec \
    'test "$(readlink /proc/self/ns/pid)" != "$1"; test "$(readlink /proc/self/ns/net)" != "$2"; echo BWRAP_NAMESPACES_OK' \
    sh "$host_pid" "$host_net" > "$work/output"
  grep -Fxq BWRAP_NAMESPACES_OK "$work/output"
}

suite_probe() {
  local prefix=$1
  BWRAP_MUST_WORK=1 timeout --kill-after=10s 180s \
    meson test -C "$prefix/build" --print-errorlogs --no-rebuild --num-processes 1
}

require_arm
case "${1:-}" in
  build)
    test "$#" -eq 4
    build_release "$2" "$3" "$4"
    ;;
  identity)
    test "$#" -eq 3
    test "$("$2" --version)" = "bubblewrap $3"
    readelf -h "$2" | grep -Eq 'Machine:[[:space:]]+AArch64'
    ;;
  execution|readonly|namespaces)
    test "$#" -eq 2
    "${1}_probe" "$2"
    ;;
  suite)
    test "$#" -eq 2
    suite_probe "$2"
    ;;
  complete)
    test "$#" -eq 3
    test "$("$2/build/bwrap" --version)" = "bubblewrap $3"
    readelf -h "$2/build/bwrap" | grep -Eq 'Machine:[[:space:]]+AArch64'
    execution_probe "$2/build/bwrap"
    readonly_probe "$2/build/bwrap"
    namespace_probe "$2/build/bwrap"
    suite_probe "$2"
    ;;
  *)
    echo 'Expected build, identity, execution, readonly, namespaces, suite, or complete.' >&2
    exit 2
    ;;
esac
