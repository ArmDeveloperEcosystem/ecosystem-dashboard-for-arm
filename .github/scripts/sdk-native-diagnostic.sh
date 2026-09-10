#!/usr/bin/env bash
set -euo pipefail

scope="$RUNNER_TEMP/sdk-native-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
mkdir -m 700 "$scope"
export FLATPAK_USER_DIR="$scope/flatpak"
export XDG_DATA_HOME="$scope/data"
export XDG_CACHE_HOME="$scope/cache"
export XDG_CONFIG_HOME="$scope/config"
export FLATPAK_FANCY_OUTPUT=0
export FLATPAK_TTY_PROGRESS=0
mkdir -p "$FLATPAK_USER_DIR" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"

branch=26.08
sdk="runtime/org.freedesktop.Sdk/aarch64/$branch"
platform="runtime/org.freedesktop.Platform/aarch64/$branch"
flatpak --version
test "$(flatpak --default-arch)" = aarch64
# Flatpak can have a different AppArmor transition from standalone bubblewrap.
# Record this diagnostic; only actual SDK execution can establish success.
if timeout --kill-after=5s 30s bwrap --unshare-user --uid 0 --gid 0 --ro-bind / / --proc /proc --dev /dev -- /usr/bin/true; then
  printf 'standalone_bwrap_exit=0\n'
else
  printf 'standalone_bwrap_exit=%s\n' "$?"
fi
timeout --kill-after=5s 120s flatpak remote-add --user flathub https://flathub.org/repo/flathub.flatpakrepo
sdk_commit=$(timeout --kill-after=5s 120s flatpak remote-info --user --show-commit flathub "$sdk")
platform_commit=$(timeout --kill-after=5s 120s flatpak remote-info --user --show-commit flathub "$platform")
[[ "$sdk_commit" =~ ^[0-9a-f]{64}$ ]]
[[ "$platform_commit" =~ ^[0-9a-f]{64}$ ]]
printf 'requested_sdk_ref=%s\nrequested_sdk_commit=%s\nrequested_platform_ref=%s\nrequested_platform_commit=%s\n' \
  "$sdk" "$sdk_commit" "$platform" "$platform_commit"
timeout --kill-after=30s 1500s flatpak install --user --assumeyes --noninteractive --no-related --no-deps flathub "$sdk" "$platform"
test "$(flatpak info --user --show-ref "$sdk")" = "$sdk"
test "$(flatpak info --user --show-ref "$platform")" = "$platform"
test "$(flatpak info --user --show-commit "$sdk")" = "$sdk_commit"
test "$(flatpak info --user --show-commit "$platform")" = "$platform_commit"
flatpak info --user "$sdk"
flatpak info --user --show-metadata "$sdk"

app="$scope/application"
flatpak build-init --arch=aarch64 "$app" org.arm.EcosystemSdkSmoke org.freedesktop.Sdk org.freedesktop.Platform "$branch"
python3 -I - "$app/metadata" "$branch" <<'PY'
import configparser
from pathlib import Path
import sys
metadata = configparser.ConfigParser(interpolation=None)
metadata.read_string(Path(sys.argv[1]).read_text())
assert metadata['Application']['sdk'] == f'org.freedesktop.Sdk/aarch64/{sys.argv[2]}'
assert metadata['Application']['runtime'] == f'org.freedesktop.Platform/aarch64/{sys.argv[2]}'
print(dict(metadata['Application']))
PY
mkdir -p "$app/files/src" "$app/files/bin"
cp .github/scripts/sdk-native-smoke.c "$app/files/src/sdk-native-smoke.c"
timeout --kill-after=5s 120s flatpak build --unshare=network "$app" sh -euc '
  cat /usr/lib/os-release
  . /usr/lib/os-release
  case "$ID" in org.freedesktop.Sdk|org.freedesktop.Platform) ;; *) exit 71 ;; esac
  test "$(uname -m)" = aarch64
  gcc --version
  target=$(gcc -dumpmachine)
  case "$target" in aarch64-*) ;; *) exit 72 ;; esac
  gcc -std=c11 -O2 -Wall -Wextra -Werror /app/src/sdk-native-smoke.c -o /app/bin/sdk-native-smoke
'
file "$app/files/bin/sdk-native-smoke"
sha256sum "$app/files/bin/sdk-native-smoke"
python3 -I - "$app/files/bin/sdk-native-smoke" <<'PY'
from pathlib import Path
import struct
import sys
header = Path(sys.argv[1]).read_bytes()[:64]
assert header[:6] == b'\x7fELF\x02\x01'
assert struct.unpack_from('<H', header, 18)[0] == 183
print('compiled_elf=64-bit-little-endian-aarch64')
PY
output=$(timeout --kill-after=5s 60s flatpak build --unshare=network "$app" /app/bin/sdk-native-smoke 42)
printf '%s\n' "$output"
test "$output" = "$(printf 'SDK_RESULT=42\nPTR_BITS=64')"
if timeout --kill-after=5s 60s flatpak build --unshare=network "$app" /app/bin/sdk-native-smoke 43 > "$scope/negative.log" 2>&1; then
  printf 'ERROR: wrong expected result was accepted\n' >&2
  exit 73
else
  negative_exit=$?
fi
cat "$scope/negative.log"
test "$negative_exit" -eq 9
printf 'wrong-expectation-exit=%s\nsdk-diagnostic=passed\n' "$negative_exit"
