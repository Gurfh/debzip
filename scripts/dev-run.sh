#!/usr/bin/env bash
set -euo pipefail
cp -n .env.example .env || true
mkdir -p cache keys
if [ ! -f keys/debzip-public-key.asc ]; then
  ./scripts/generate-gpg-key.sh
fi
docker compose up -d --build
printf '
DebZip is running at http://localhost:8000
'
