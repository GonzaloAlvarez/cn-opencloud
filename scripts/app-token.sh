#!/usr/bin/env bash
# cn-opencloud/scripts/app-token.sh — mint an OpenCloud app token for a user
# (WebDAV clients, rclone, cn-opencloud/tools/drive-migrate). Printed ONCE as
# a SIX-WORD PASSPHRASE (" token: word word …"); store it where the client
# needs it, never in Git, and never let it into a log (word lists slip past
# "long random string" redaction).
#   scripts/app-token.sh <user-name> [expiration, default 720h]
# The CLI only creates tokens. List/revoke through the HTTP API as the user
# (basic auth user:<any valid app token>):
#   curl -u akadmin:<token> https://drive.lab.gn.al/auth-app/tokens
#   curl -u akadmin:<token> -X DELETE "https://drive.lab.gn.al/auth-app/tokens?token=<url-encoded token>"
# or in the web UI (Account → App tokens). The user must have logged in once
# (autoprovisioning) before a token can be minted for them.
set -euo pipefail
cd "$(dirname "$0")/.."
USER_NAME="${1:-}"; EXP="${2:-720h}"
[[ -n "$USER_NAME" ]] || { sed -n '2,8p' "$0"; exit 2; }
docker compose -p cn-opencloud exec -T opencloud opencloud auth-app create --user-name="$USER_NAME" --expiration="$EXP"
