#!/usr/bin/env bash
# cn-opencloud/scripts/backup.sh — restic snapshot of the PosixFS tree + config
# into the raidnas NFS repo, then a dedup copy to S3 (the `backup` service,
# profile tools). Installed as a Sunday 06:00 cron by amun-docker from
# resiliency.yml; also fine by hand.
#
#   scripts/backup.sh            online snapshot (default): OpenCloud keeps
#                                running; a file written mid-backup lands in
#                                the next snapshot (restic preserves xattrs,
#                                which carry PosixFS's metadata)
#   scripts/backup.sh --stop     fully consistent snapshot as upstream
#                                recommends: stops opencloud (and the watchdog
#                                that would restart it) for the duration —
#                                minutes of downtime, so by hand only
#
# After a restore: `opencloud posixfs consistency` / `posixfs index`.
set -euo pipefail
cd "$(dirname "$0")/.."
P=cn-opencloud
NFS=/home/gonzalo/docker/data/nfs
REPO="$NFS/backups/cn-opencloud"
STOP=0; [[ "${1:-}" == "--stop" ]] && STOP=1

log() { printf '%s [backup] %s\n' "$(date -Is)" "$*"; logger -t cn-opencloud-backup "$*" 2>/dev/null || true; }

[[ "$(stat -f -c %T "$NFS" 2>/dev/null)" == "nfs" ]] || { log "refusing: $NFS is not an NFS mount (placeholder dir?)"; exit 1; }
[[ -d "$REPO" ]] || { log "refusing: $REPO missing on the NAS"; exit 1; }
[[ -f .env ]] || { log "refusing: .env missing"; exit 1; }

restore_services() {
  if (( STOP )); then
    log "starting opencloud + watchdog again"
    docker compose -p "$P" start opencloud ts-drive-watchdog >/dev/null 2>&1 || true
  fi
}
trap restore_services EXIT

if (( STOP )); then
  log "stopping the watchdog and opencloud for a consistent snapshot"
  docker compose -p "$P" stop ts-drive-watchdog opencloud
fi

start=$(date +%s)
log "restic backup → $REPO (then copy → S3)"
if docker compose -p "$P" run --rm --no-deps backup backup; then
  end=$(date +%s)
  mkdir -p textfile
  {
    echo "# HELP opencloud_backup_last_success_timestamp_seconds Unix time of the last successful restic run (NAS + S3 copy)."
    echo "# TYPE opencloud_backup_last_success_timestamp_seconds gauge"
    echo "opencloud_backup_last_success_timestamp_seconds $end"
    echo "# HELP opencloud_backup_duration_seconds Duration of the last successful restic run."
    echo "# TYPE opencloud_backup_duration_seconds gauge"
    echo "opencloud_backup_duration_seconds $((end - start))"
  } > textfile/.opencloud_backup.prom.tmp
  mv textfile/.opencloud_backup.prom.tmp textfile/opencloud_backup.prom
  chmod 0644 textfile/opencloud_backup.prom
  log "done in $((end - start))s"
else
  log "restic FAILED (see docker compose run output above)"
  exit 1
fi
