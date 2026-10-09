#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/aiallro/loancopilot.privat"
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$ROOT/backup/full_$STAMP"
mkdir -p "$TARGET"
cp -a "$ROOT/dbsqlite" "$TARGET/"
cp -a "$ROOT/documente" "$TARGET/"
find "$ROOT/backup" -maxdepth 1 -type d -name 'full_*' -mtime +30 -exec rm -rf {} +
echo "$TARGET"
