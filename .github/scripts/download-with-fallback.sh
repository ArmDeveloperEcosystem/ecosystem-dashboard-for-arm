#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <output> <url> [<url> ...]" >&2
  exit 2
fi

OUTPUT="$1"
shift

ATTEMPTS="${DOWNLOAD_ATTEMPTS:-3}"
CONNECT_TIMEOUT="${DOWNLOAD_CONNECT_TIMEOUT:-30}"
MAX_TIME="${DOWNLOAD_MAX_TIME:-600}"
RETRY_DELAY="${DOWNLOAD_RETRY_DELAY:-5}"
WGET_TIMEOUT="${DOWNLOAD_WGET_TIMEOUT:-30}"
WGET_WAITRETRY="${DOWNLOAD_WGET_WAITRETRY:-5}"

mkdir -p "$(dirname "$OUTPUT")"
touch "$OUTPUT"

URL_INDEX=0
for URL in "$@"; do
  [ -n "$URL" ] || continue
  URL_INDEX=$((URL_INDEX + 1))
  if [ "$URL_INDEX" -gt 1 ]; then
    rm -f "$OUTPUT"
    touch "$OUTPUT"
  fi
  for ATTEMPT in $(seq 1 "$ATTEMPTS"); do
    if [ -s "$OUTPUT" ]; then
      CONTINUE_ARGS=(-C -)
    else
      CONTINUE_ARGS=()
    fi

    if curl \
      --fail \
      --location \
      --http1.1 \
      --ipv4 \
      --retry 0 \
      --connect-timeout "$CONNECT_TIMEOUT" \
      --max-time "$MAX_TIME" \
      --progress-bar \
      "${CONTINUE_ARGS[@]}" \
      -o "$OUTPUT" \
      "$URL"; then
      exit 0
    fi

    sleep $((RETRY_DELAY * ATTEMPT))
  done
done

for URL in "$@"; do
  [ -n "$URL" ] || continue
  if wget -4 -c --tries="$ATTEMPTS" --waitretry="$WGET_WAITRETRY" --retry-connrefused --timeout="$WGET_TIMEOUT" -O "$OUTPUT" "$URL"; then
    exit 0
  fi
done

exit 1
