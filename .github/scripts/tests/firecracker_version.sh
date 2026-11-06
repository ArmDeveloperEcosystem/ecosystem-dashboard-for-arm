#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 3
binary=$1
product=$2
expected=$3
case "$product" in Firecracker|Jailer) ;; *) exit 2 ;; esac
reported=$(timeout --kill-after=2s 10s "$binary" --version)
printf '%s\n' "$reported" >&2
# New releases also print an exit log. Require exactly one matching product line.
line=$(printf '%s\n' "$reported" | grep -E "^${product} ")
test "$line" = "$product $expected"
printf '%s\n' "${line#"$product "}"
