#!/usr/bin/env bash
set -euo pipefail

PACKAGES=""
EXTRA_PACKAGES=""
RETRIES=5
INITIAL_BACKOFF_SECONDS=5
QUIET=false
UPDATE_ONLY=false
NO_INSTALL_RECOMMENDS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --packages)
      PACKAGES="${2-}"
      shift 2
      ;;
    --extra-packages)
      EXTRA_PACKAGES="${2-}"
      shift 2
      ;;
    --retries)
      RETRIES="${2-5}"
      shift 2
      ;;
    --initial-backoff-seconds)
      INITIAL_BACKOFF_SECONDS="${2-5}"
      shift 2
      ;;
    --quiet)
      QUIET="${2-false}"
      shift 2
      ;;
    --update-only)
      UPDATE_ONLY="${2-false}"
      shift 2
      ;;
    --no-install-recommends)
      NO_INSTALL_RECOMMENDS="${2-false}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

apt_update() {
  sudo apt-get clean
  sudo rm -rf /var/lib/apt/lists/*
  local cmd=(
    sudo apt-get
    -o Acquire::Retries=3
    -o Acquire::http::No-Cache=true
    -o Acquire::https::No-Cache=true
    update
  )
  if [[ "$QUIET" == "true" ]]; then
    "${cmd[@]}" >/dev/null
  else
    "${cmd[@]}"
  fi
}

attempt=1
backoff="$INITIAL_BACKOFF_SECONDS"
until apt_update; do
  if (( attempt >= RETRIES )); then
    echo "apt-get update failed after ${RETRIES} attempts" >&2
    exit 100
  fi
  echo "apt-get update failed on attempt ${attempt}; retrying in ${backoff}s" >&2
  sleep "$backoff"
  attempt=$((attempt + 1))
  backoff=$((backoff * 2))
done

FULL_PACKAGES="$PACKAGES"
if [[ -n "${EXTRA_PACKAGES// }" ]]; then
  if [[ -n "${FULL_PACKAGES// }" ]]; then
    FULL_PACKAGES="${FULL_PACKAGES} ${EXTRA_PACKAGES}"
  else
    FULL_PACKAGES="${EXTRA_PACKAGES}"
  fi
fi

if [[ "$UPDATE_ONLY" == "true" || -z "${FULL_PACKAGES// }" ]]; then
  exit 0
fi

read -r -a package_array <<< "$FULL_PACKAGES"
install_cmd=(
  sudo env
  DEBIAN_FRONTEND=noninteractive
  APT_LISTCHANGES_FRONTEND=none
  apt-get
  install
  -y
)
if [[ "$NO_INSTALL_RECOMMENDS" == "true" ]]; then
  install_cmd+=(--no-install-recommends)
fi
install_cmd+=("${package_array[@]}")

if [[ "$QUIET" == "true" ]]; then
  "${install_cmd[@]}" >/dev/null
else
  "${install_cmd[@]}"
fi
