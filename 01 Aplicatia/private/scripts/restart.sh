#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="/home/aiallro/loancopilot_app"
mkdir -p "$APP_ROOT/tmp"
touch "$APP_ROOT/tmp/restart.txt"
if command -v cloudlinux-selector >/dev/null 2>&1; then
  cloudlinux-selector restart --json \
    --interpreter python \
    --user aiallro \
    --app-root loancopilot_app || true
fi
echo "LoanCopilot restart solicitat."
