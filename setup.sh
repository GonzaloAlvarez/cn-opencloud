#!/usr/bin/env bash
# cn-opencloud — idempotent bring-up on kaiser.lan.
#
# Prerequisites (host): amun core + `amun docker`, and the Kauket-managed .env:
#   kauket get kaiser.cn_opencloud_env
#   ./setup.sh
# Creates the PosixFS data dir and the config dir (uid 1000), renders promtail,
# brings the stack up and waits for /status.php. On the very FIRST run
# `opencloud init` writes config/opencloud/opencloud.yaml — retained state that
# must then be stored in Kauket (kaiser.cn_opencloud_yaml); the script prints
# the command. It never regenerates that file. Re-run after `git pull`.
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  -h|--help) sed -n '/^#!/d; /^[^#]/q; s/^# \{0,1\}//p' "$0"; exit 0 ;;
  "") ;;
  *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac

log()  { printf '\n\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }
env_get() { grep -E "^${1}=" .env 2>/dev/null | head -1 | cut -d= -f2- || true; }

[[ -f .env ]] || die ".env not found. Run: kauket get kaiser.cn_opencloud_env"
for k in DRIVE_AUTHKEY OC_ADMIN_PASSWORD RESTIC_PASSWORD INFRA_VPS_TAILNET_IP SMTP_HOST; do
  [[ -n "$(env_get "$k")" ]] || warn "$k is empty in .env"
done

DATA_DIR="$(env_get OC_DATA_DIR)"; DATA_DIR="${DATA_DIR:-/home/gonzalo/docker/cn-opencloud/data}"
CONF_DIR=config/opencloud

# ── directories: OpenCloud runs as 1000:1000 and chmods its tree 0700 ───────
if [[ "$(id -u)" == "1000" ]]; then
  install -d -m 0700 "$DATA_DIR" "$CONF_DIR"
else
  sudo install -d -m 0700 -o 1000 -g 1000 "$DATA_DIR" "$CONF_DIR"
fi
[[ "$(stat -c %u "$DATA_DIR")" == "1000" ]] || die "$DATA_DIR must be owned by uid 1000 (OpenCloud's container user)"
mkdir -p textfile
[[ "$(stat -f -c %T "$DATA_DIR")" != "nfs" ]] || die "$DATA_DIR is on NFS — PosixFS needs xattrs and inotify; keep it on the local SSD"

INFRA_VPS_TAILNET_IP="$(env_get INFRA_VPS_TAILNET_IP)" envsubst < promtail/promtail.yml.tmpl > promtail/promtail.yml
log "rendered promtail/promtail.yml"

FIRST_RUN=0; [[ -f "$CONF_DIR/opencloud.yaml" ]] || FIRST_RUN=1

log "docker compose up -d --remove-orphans"
docker compose up -d --remove-orphans

log "waiting for OpenCloud (/status.php, up to 3m)"
for i in $(seq 1 36); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:9200/status.php || true)"
  if [[ "$code" == "200" ]]; then log "OpenCloud answers after ${i}x5s"; break; fi
  sleep 5
  [[ $i -eq 36 ]] && die "OpenCloud never answered on 127.0.0.1:9200 (last HTTP '$code') — docker compose logs opencloud"
done
curl -s --max-time 5 http://127.0.0.1:9200/status.php | sed 's/^/  /'; echo

LAB_DOMAIN="$(env_get LAB_DOMAIN)"; LAB_DOMAIN="${LAB_DOMAIN:-lab.gn.al}"
LAN_DOMAIN="$(env_get LAN_DOMAIN)"; LAN_DOMAIN="${LAN_DOMAIN:-kaiser.lan}"
cat <<EOT


===============================================================
cn-opencloud is up.

  OpenCloud      :  https://drive.${LAB_DOMAIN}       (canonical; LAN via step-ca, tailnet via LE)
                    https://drive.${LAN_DOMAIN}       (301 → canonical)
  Login          :  Authentik (groups drive / infra-admins → opencloudUser / opencloudAdmin)
  Files on disk  :  ${DATA_DIR}/storage/users/{users,projects}/<id>/  (PosixFS, owner 1000)
  Backup         :  scripts/backup.sh (Sun 06:00 via amun docker) → raidnas restic repo + S3 copy
  App tokens     :  scripts/app-token.sh <user> [expiry]   (WebDAV / rclone / drive-migrate)
  Metrics        :  :9100 node-exporter · :9205 proxy debug (VPS scrapes drive.ts.gn.al)

  Then           :  amun docker        # installs the boot unit, reconcile cron and the backup cron
===============================================================
EOT
if (( FIRST_RUN )) && [[ -f "$CONF_DIR/opencloud.yaml" ]]; then
  cat <<EOT
  ⚠  FIRST RUN: opencloud init wrote ${CONF_DIR}/opencloud.yaml — RETAINED secrets
     (jwt/transfer/machine-auth/service-account keys, storage mount id). Store
     it in Kauket now, from the operator Mac:
       scp kaiser.lan:$(pwd)/${CONF_DIR}/opencloud.yaml /tmp/opencloud.yaml
       kauket add kaiser.cn_opencloud_yaml /tmp/opencloud.yaml --dest $(pwd)/${CONF_DIR}/opencloud.yaml --mode 0600
       rm -f /tmp/opencloud.yaml
     Never run \`opencloud init --force-overwrite\` on this instance.
EOT
fi
