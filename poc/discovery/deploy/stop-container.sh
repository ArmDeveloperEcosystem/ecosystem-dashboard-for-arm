#!/bin/sh
# Remove only the container recorded for this service invocation. Docker --rm may
# have removed it already; a daemon failure must not be mistaken for that case.
set -eu
cidfile=${1:?Path to service container ID file required}
docker_bin=${DOCKER_BIN:-/usr/bin/docker}
if [ ! -s "$cidfile" ]; then
    exit 0
fi
container_id=$(cat "$cidfile")
case "$container_id" in
    *[!0-9a-f]*|'') echo "Invalid service container ID" >&2; exit 1 ;;
esac
if [ "${#container_id}" -ne 64 ]; then
    echo "Invalid service container ID length" >&2
    exit 1
fi
remaining=$("$docker_bin" container ls -aq --no-trunc --filter "id=$container_id")
if [ -z "$remaining" ]; then
    exit 0
fi
if ! "$docker_bin" container rm -f "$container_id"; then
    # A normal --rm completion can race the first existence check.
    remaining=$("$docker_bin" container ls -aq --no-trunc --filter "id=$container_id")
    if [ -n "$remaining" ]; then
        echo "Could not stop service container" >&2
        exit 1
    fi
fi
