#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-.prefetch-heavy}"
HELPER="${GITHUB_WORKSPACE:-$(pwd)}/.github/scripts/download-with-fallback.sh"
MANIFEST_ROWS="$(mktemp)"

mkdir -p "$OUT_DIR"
: > "$MANIFEST_ROWS"

download_one() {
  local slug="$1"
  local filename="$2"
  shift 2

  local destination_dir="${OUT_DIR}/${slug}"
  local destination="${destination_dir}/${filename}"
  mkdir -p "$destination_dir"
  rm -f "$destination"

  local status="missing"
  local source_url=""

  if DOWNLOAD_ATTEMPTS=2 \
    DOWNLOAD_CONNECT_TIMEOUT=30 \
    DOWNLOAD_MAX_TIME=1200 \
    DOWNLOAD_RETRY_DELAY=5 \
    DOWNLOAD_WGET_TIMEOUT=120 \
    DOWNLOAD_WGET_WAITRETRY=5 \
    bash "$HELPER" "$destination" "$@"; then
    status="cached"
    source_url="$1"
  else
    rm -f "$destination"
  fi

  printf '%s\t%s\t%s\t%s\n' "$slug" "$filename" "$status" "$source_url" >> "$MANIFEST_ROWS"
}

download_one "spark" "spark-3.5.3-bin-hadoop3.tgz" \
  "https://dlcdn.apache.org/spark/spark-3.5.3/spark-3.5.3-bin-hadoop3.tgz" \
  "https://downloads.apache.org/spark/spark-3.5.3/spark-3.5.3-bin-hadoop3.tgz" \
  "https://archive.apache.org/dist/spark/spark-3.5.3/spark-3.5.3-bin-hadoop3.tgz" \
  "http://archive.apache.org/dist/spark/spark-3.5.3/spark-3.5.3-bin-hadoop3.tgz"

download_one "nifi" "nifi-2.7.2-bin.zip" \
  "https://dlcdn.apache.org/nifi/2.7.2/nifi-2.7.2-bin.zip" \
  "https://downloads.apache.org/nifi/2.7.2/nifi-2.7.2-bin.zip" \
  "https://archive.apache.org/dist/nifi/2.7.2/nifi-2.7.2-bin.zip" \
  "http://archive.apache.org/dist/nifi/2.7.2/nifi-2.7.2-bin.zip"

download_one "pinot" "apache-pinot-1.2.0-bin.tar.gz" \
  "https://downloads.apache.org/pinot/apache-pinot-1.2.0/apache-pinot-1.2.0-bin.tar.gz" \
  "https://archive.apache.org/dist/pinot/apache-pinot-1.2.0/apache-pinot-1.2.0-bin.tar.gz" \
  "http://archive.apache.org/dist/pinot/apache-pinot-1.2.0/apache-pinot-1.2.0-bin.tar.gz"

download_one "druid" "apache-druid-31.0.0-bin.tar.gz" \
  "https://dlcdn.apache.org/druid/31.0.0/apache-druid-31.0.0-bin.tar.gz" \
  "https://downloads.apache.org/druid/31.0.0/apache-druid-31.0.0-bin.tar.gz" \
  "https://archive.apache.org/dist/druid/31.0.0/apache-druid-31.0.0-bin.tar.gz" \
  "http://archive.apache.org/dist/druid/31.0.0/apache-druid-31.0.0-bin.tar.gz"

download_one "hive" "apache-hive-4.0.0-bin.tar.gz" \
  "https://archive.apache.org/dist/hive/hive-4.0.0/apache-hive-4.0.0-bin.tar.gz" \
  "http://archive.apache.org/dist/hive/hive-4.0.0/apache-hive-4.0.0-bin.tar.gz"

download_one "hadoop" "hadoop-3.3.6-aarch64.tar.gz" \
  "https://downloads.apache.org/hadoop/common/hadoop-3.3.6/hadoop-3.3.6-aarch64.tar.gz" \
  "https://archive.apache.org/dist/hadoop/common/hadoop-3.3.6/hadoop-3.3.6-aarch64.tar.gz" \
  "http://archive.apache.org/dist/hadoop/common/hadoop-3.3.6/hadoop-3.3.6-aarch64.tar.gz"

download_one "hadoop" "hadoop-3.3.6.tar.gz" \
  "https://downloads.apache.org/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz" \
  "https://archive.apache.org/dist/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz" \
  "http://archive.apache.org/dist/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz"

download_one "storm" "apache-storm-2.8.2.tar.gz" \
  "https://archive.apache.org/dist/storm/apache-storm-2.8.2/apache-storm-2.8.2.tar.gz" \
  "http://archive.apache.org/dist/storm/apache-storm-2.8.2/apache-storm-2.8.2.tar.gz"

download_one "dolphinscheduler" "apache-dolphinscheduler-3.2.1-bin.tar.gz" \
  "https://downloads.apache.org/dolphinscheduler/3.2.1/apache-dolphinscheduler-3.2.1-bin.tar.gz" \
  "https://archive.apache.org/dist/dolphinscheduler/3.2.1/apache-dolphinscheduler-3.2.1-bin.tar.gz" \
  "http://archive.apache.org/dist/dolphinscheduler/3.2.1/apache-dolphinscheduler-3.2.1-bin.tar.gz"

python3 - "$MANIFEST_ROWS" "$OUT_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

rows_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
entries = []
for line in rows_path.read_text().splitlines():
    slug, filename, status, source_url = line.split("\t")
    entries.append(
        {
            "slug": slug,
            "filename": filename,
            "status": status,
            "source_url": source_url,
        }
    )

manifest_path.write_text(json.dumps({"entries": entries}, indent=2) + "\n")
PY

rm -f "$MANIFEST_ROWS"
