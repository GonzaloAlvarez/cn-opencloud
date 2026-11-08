#!/usr/bin/env bash
# cn-opencloud/scripts/app-token.sh — mint an OpenCloud app token for a user
# (WebDAV clients, rclone, cn-opencloud/tools/drive-migrate). Printed ONCE;
# store it where the client needs it, never in Git.
#   scripts/app-token.sh <user-name> [expiration, default 720h]
# Tokens are revoked in the UI (Account → App tokens) or with
# `opencloud auth-app list|delete` inside the container.
set -euo pipefail
cd "$(dirname "$0")/.."
USER_NAME="${1:-}"; EXP="${2:-720h}"
[[ -n "$USER_NAME" ]] || { sed -n '2,8p' "$0"; exit 2; }
docker compose -p cn-opencloud exec -T opencloud opencloud auth-app create --user-name="$USER_NAME" --expiration="$EXP"
