#!/usr/bin/env bash
set -euo pipefail
CACHE_DIR="${CACHE_DIR:-./cache}"
find "$CACHE_DIR" -name metadata.json -print0 | while IFS= read -r -d '' meta; do
  if python3 -c 'import json,sys; from datetime import datetime, timezone; m=json.load(open(sys.argv[1])); exp=datetime.fromisoformat(m.get("expires_at")); sys.exit(0 if datetime.now(timezone.utc) > exp else 1)' "$meta"; then
    dir=$(dirname "$meta")
    echo "Removing expired cache: $dir"
    rm -rf "$dir"
  fi
done
