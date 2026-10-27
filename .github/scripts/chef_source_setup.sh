#!/usr/bin/env bash
# Sourced by each check; direct execution prepares one isolated source bundle.
set -euo pipefail

CHEF_LANE=${1:?expected baseline or candidate}
case "$CHEF_LANE" in
  baseline)
    EXPECTED_CHEF_VERSION=18.8.54
    EXPECTED_CHEF_REVISION=d28f552c2b23b738d670d348d3c19d24e3c874e8
    ;;
  candidate)
    EXPECTED_CHEF_VERSION=18.10.17
    EXPECTED_CHEF_REVISION=dad75f495067c88d1e07c3f5999d88ef8b3f3cf9
    ;;
  *) echo 'Unknown Chef source lane' >&2; exit 1 ;;
esac
export EXPECTED_CHEF_VERSION EXPECTED_CHEF_REVISION
export CHEF_SOURCE_ROOT="${CHEF_WORK_ROOT:?}/$CHEF_LANE/source"
export EVIDENCE_DIR="$CHEF_WORK_ROOT/$CHEF_LANE/evidence"
export BUNDLE_PATH="$CHEF_WORK_ROOT/$CHEF_LANE/bundle"
export BUNDLE_GEMFILE="$CHEF_SOURCE_ROOT/Gemfile"
export BUNDLE_FROZEN=true BUNDLE_FORCE_RUBY_PLATFORM=true BUNDLE_DISABLE_SHARED_GEMS=true
export BUNDLE_WITHOUT=omnibus_package:pry:ruby_shadow:knife_windows_deps

chef_assert_source() {
  test "$(git -C "$CHEF_SOURCE_ROOT" rev-parse HEAD)" = "$EXPECTED_CHEF_REVISION"
  git -C "$CHEF_SOURCE_ROOT" diff --exit-code HEAD
  test -z "$(git -C "$CHEF_SOURCE_ROOT" ls-files --others --exclude-standard)"
}

chef_require_setup() {
  test "${CHEF_SETUP_OUTCOME-success}" = success
  test "$(cat "$EVIDENCE_DIR/setup.complete")" = "$EXPECTED_CHEF_REVISION"
  chef_assert_source
  cd "$CHEF_SOURCE_ROOT"
  sha256sum --check "$EVIDENCE_DIR/source.sha256"
  bundle _2.3.27_ check
}

chef_setup() {
  test -z "${CHEF_LICENSE:-}"
  test -z "${CHEF_LICENSE_KEY:-}"
  test -z "${GEMFILE_MOD:-}"
  test -z "${RUBYOPT:-}"
  test ! -e "$CHEF_SOURCE_ROOT"
  mkdir -p "$CHEF_SOURCE_ROOT" "$EVIDENCE_DIR"
  git -C "$CHEF_SOURCE_ROOT" init
  git -C "$CHEF_SOURCE_ROOT" remote add origin https://github.com/chef/chef.git
  git -C "$CHEF_SOURCE_ROOT" fetch --depth=1 origin "$EXPECTED_CHEF_REVISION"
  git -C "$CHEF_SOURCE_ROOT" checkout --detach FETCH_HEAD
  chef_assert_source
  cd "$CHEF_SOURCE_ROOT"
  test ! -e Gemfile.local
  test ! -e spec/support/local_gems.rb
  sha256sum Gemfile Gemfile.lock chef.gemspec > "$EVIDENCE_DIR/source.sha256"
  {
    printf 'Scope: upstream source file-resource API; not vendor installer or CLI.\n'
    uname -a
    ruby --version
    git rev-parse HEAD
    cat "$EVIDENCE_DIR/source.sha256"
  } | tee "$EVIDENCE_DIR/source-and-host.txt"
  bundle _2.3.27_ install --jobs 4 --retry 2 2>&1 | tee "$EVIDENCE_DIR/bundle-install.log"
  bundle _2.3.27_ check
  chef_assert_source
  sha256sum --check "$EVIDENCE_DIR/source.sha256"
  printf '%s\n' "$EXPECTED_CHEF_REVISION" > "$EVIDENCE_DIR/setup.complete"
}

chef_finish_check() {
  local result=$?
  trap - EXIT
  local status=failed
  if [ "$result" -eq 0 ]; then status=${CHEF_TEST_STATUS:-passed}; fi
  {
    printf 'status=%s\n' "$status"
    printf 'duration=%s\n' "$(( $(date +%s) - CHEF_START_TIME ))"
    if [ "${CHEF_REGRESSION:-false}" = true ]; then
      printf 'decision=%s\n' "${CHEF_DECISION:-next_regression_failed}"
      printf 'current_version=%s\n' "${BASELINE_VERSION:-unknown}"
      printf 'latest_version=%s\n' "$EXPECTED_CHEF_VERSION"
      printf 'next_installed_version=%s\n' "${CHEF_NEXT_OBSERVED:-not_installed}"
      printf 'regression_result=%s\n' "${CHEF_RESULT:-Candidate source API validation failed; see job logs.}"
      printf 'comparison=%s\n' "${CHEF_COMPARISON:-Candidate source API coverage did not complete; no vendor installer or CLI equivalence is claimed.}"
    fi
  } >> "$GITHUB_OUTPUT"
  exit "$result"
}

chef_start_check() {
  CHEF_START_TIME=$(date +%s)
  trap chef_finish_check EXIT
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  chef_setup
fi
