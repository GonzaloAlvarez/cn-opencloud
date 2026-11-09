# cn-opencloud

[OpenCloud](https://opencloud.eu/) — the homelab's Google Drive replacement: a folder tree for any file, share links, desktop/mobile/web clients. Lives on `kaiser.lan` in the homelab "sidecar stack" shape (see [cn-fitness](https://github.com/GonzaloAlvarez/cn-fitness)), canonical URL **`https://drive.lab.gn.al`** on both the LAN (step-ca) and the tailnet (LE), login through Authentik. Documents that should be OCR'd and tagged go to [cn-paperless](https://github.com/GonzaloAlvarez/cn-paperless) instead; `tools/drive-migrate` moves the Google Drive tree into OpenCloud and the document-shaped subset into Paperless.

## Stack

```
ts-drive (tailscale, tag:svc, publishes 127.0.0.1:9200)   ── netns ──┐
  ├─ opencloud        opencloudeu/opencloud:7.2.4 (one binary: proxy :9200, debug :9205, web, graph, storage-users, idm, nats…)
  ├─ consul-register  advertises drive.lab.gn.al → drive.ts.gn.al:9200 (VPS traefik-lab, LE)
  ├─ promtail / node-exporter (+ ./textfile: opencloud_backup_*)
  └─ ts-drive-watchdog (recreates dependents after a sidecar restart)
backup (profile tools): mazzolino/restic — run by scripts/backup.sh (Sun 06:00) → raidnas NFS repo + restic copy → S3 opencloud-restic
```

Why it looks like this:

- **PosixFS on kaiser's SSD.** OpenCloud's default storage driver keeps files as a plain tree (`OC_DATA_DIR/storage/users/users/<id>/…`, trash in `.Trash`, metadata in extended attributes) and demands a POSIX filesystem with xattrs — NFS only from 4.2 with `noac`. The raidnas export is NFSv3 (no xattrs, no inotify), so the data lives on the local SSD and restic carries it to the NAS and S3 instead. The tree is OpenCloud's: non-collaborative mode (`STORAGE_USERS_POSIX_WATCH_FS=false`), edit it only through OpenCloud (or stop it first).
- **Authentik is the IdP**, OpenCloud's built-in `idp` is excluded; its built-in `idm` stays as the user store and `PROXY_AUTOPROVISION_ACCOUNTS` creates people on first login. The web client is a **public PKCE client** with the fixed id `web` (`cn-authentik/setup-opencloud-oidc.sh`); the `roles` scope mapping turns `infra-admins` into `opencloudAdmin` and everyone else (`drive` group) into `opencloudUser` (`PROXY_ROLE_ASSIGNMENT_DRIVER=oidc`). Access tokens are RS256 JWTs verified against Authentik's JWKS (`PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD=jwt`).
- **One canonical origin.** `OC_URL` and the OIDC redirect URIs are `https://drive.lab.gn.al`; `drive.kaiser.lan` is a 301 in cn-home. LAN clients resolve the name to kaiser (Technitium + pfSense override), tailnet clients through the VPS.
- **`config/opencloud/opencloud.yaml` is state.** `opencloud init` writes it once (jwt secret, transfer secret, machine-auth key, service-account secret, storage mount id — all retained); it is Kauket `kaiser.cn_opencloud_yaml` and is never regenerated (`--force-overwrite` would orphan every space).
- **Pin.** Production channel `opencloudeu/opencloud:7.2.4`, excluded from Watchtower. Upgrade by hand per the [upgrade guide](https://docs.opencloud.eu/docs/admin/maintenance/upgrade/upgrade-guide): stop → backup → new tag → `opencloud init --diff` in a throwaway container with the config mounted → `patch opencloud.yaml` → `up -d`. Move to the next production tag after the 2026-11-17 release; rolling 9.x is "not intended for production".

## Setup

Once, on the operator Mac:

```sh
ssh neptune.lan 'cd ~/cn-authentik && git pull && ./setup-opencloud-oidc.sh'   # groups drive/infra-admins, public client web
# .env from .env.example (OC_ADMIN_PASSWORD, RESTIC_PASSWORD via openssl rand; DRIVE_AUTHKEY minted on the VPS with --user 2 --tags tag:svc --expiration 1h)
kauket add kaiser.cn_opencloud_env ./opencloud.env --dest /home/gonzalo/cn-opencloud/.env --mode 0600
ssh kaiser.lan 'mkdir -p /home/gonzalo/docker/data/nfs/backups/cn-opencloud'   # restic repo dir on the NAS (1024:100 through the export)
# DNS both sides: cn-dnsdhcpd/dns/records.tsv (seed-dns.sh on pki) + cn-home LAN_HOSTS (./deploy)
```

On kaiser (fresh clone):

```sh
git clone https://github.com/GonzaloAlvarez/cn-opencloud ~/cn-opencloud && cd ~/cn-opencloud
kauket get kaiser.cn_opencloud_env
./setup.sh          # dirs, render, up, wait for /status.php; FIRST run prints the Kauket command for opencloud.yaml
amun docker         # boot unit, reconcile cron, Sunday backup cron
```

Store `config/opencloud/opencloud.yaml` in Kauket right after the first run (the script prints the exact commands). Deploy after a change: `git pull && ./setup.sh`; one service: `docker compose up -d --force-recreate --no-deps <svc>`.

| Access | URL | Notes |
|---|---|---|
| Web UI | **`https://drive.lab.gn.al`** | Authentik login (`drive` or `infra-admins`) |
| LAN alias | `https://drive.kaiser.lan` | 301 to the canonical name |
| WebDAV | `https://drive.lab.gn.al/remote.php/dav/files/<user>/` (or `/remote.php/dav/spaces/<space-id>/`) | username + **app token** (`scripts/app-token.sh <user>` or Account → App tokens; the token is a six-word passphrase); basic auth with the password is off. The operator's account is `akadmin` (the Authentik username). |
| rclone | `type=webdav`, `vendor=infinitescale`, `url=…/remote.php/dav/files/<user>/`, `user`, `pass=<app token>` | TUS chunked uploads (10 MB); rclone ≥ 1.75 |
| Desktop / iOS / Android | not yet — see follow-ups | the native clients use three more OIDC clients and a global issuer |

## Leaving Google Drive — `tools/drive-migrate`

A stdlib Python CLI (plus `rclone` ≥ 1.75 and `fzf`) that runs on the operator Mac at home; state in `~/.config/drive-migrate/` (0700, nothing in Git). Google side, once: your **own** Google Cloud project with the Drive API enabled, an OAuth *Desktop app* client, scope `drive.readonly`, consent screen in *Testing* with you as test user (a restricted scope in a published app would need Google verification; in Testing the grant expires after 7 days — just re-run `auth drive`). Keep it separate from cn-printer's `drive.file` client.

```sh
tools/drive-migrate/drive-migrate auth drive --client-id … --client-secret …   # prints the consent URL (paste it in the browser with the right Google account); --open-browser to launch one
tools/drive-migrate/drive-migrate auth opencloud --user gonzalo --token "$(ssh kaiser.lan ~/cn-opencloud/scripts/app-token.sh gonzalo)"
tools/drive-migrate/drive-migrate auth paperless --token <API token>          # a Paperless user's token (My Profile)
tools/drive-migrate/drive-migrate mirror --dry-run && tools/drive-migrate/drive-migrate mirror   # whole tree → OpenCloud "Google Drive/"
tools/drive-migrate/drive-migrate verify
tools/drive-migrate/drive-migrate pick                                        # fzf multi-select → selection file (PDFs only by default; --ext pdf,docx or --ext all; --under Scanned)
tools/drive-migrate/drive-migrate push --selection ~/.config/drive-migrate/selection-*.txt --tags-from-path
tools/drive-migrate/drive-migrate status
```

Reading a `mirror` log: one `INFO … Failed to read metadata: object not found` per copied file is **noise** — rclone asks OpenCloud for the new object's size/modtime right after the TUS upload, before OpenCloud's asynchronous post-processing has made it visible; the copy is still counted (`Copied (new)`) and the file ends up with the right size and modtime (checked). `ERROR … can't read dangling shortcut` is a Drive shortcut whose target is gone (skipped since `--drive-skip-dangling-shortcuts`). `NOTICE … Duplicate object found in source - ignoring` means Drive holds two files with the same name in one folder (Google Photos exports do this): rclone copies one and ignores the other — review those names in the log and rename the twin in Drive if both matter. `mirror` is a resumable `rclone copy` (Docs/Sheets/Slides exported as docx/xlsx/pptx, folders kept, re-runs move only changes); `push` downloads each pick and POSTs it to Paperless with the title, the Drive creation date, a **storage path mirroring its Drive folder** (`Google Drive/<folder>/<title>` on the media tree, so the folder structure survives on disk and is filterable in Paperless; `--no-folders` to skip, `--root` to rename the prefix) and, with `--tags-from-path`, every folder of its path as a tag. Uploads are queued (Paperless consumes with its task workers); `drive-migrate settle` polls the queued tasks and finalises `ledger.csv` (`--wait` does it inline, slowly). Re-runs skip successes and queued rows — Paperless 3 accepts duplicates, so the ledger is the guard. `--source takeout:/path/to/extracted/Takeout/Drive` uses a Google Takeout export instead of the live Drive (no OAuth). The self-test `tools/drive-migrate/test` uses rclone `alias` remotes and a fake Paperless API. The operator must have logged into OpenCloud once (autoprovisioning) before an app token can be minted for them.

## Identity

- Groups are capabilities: Authentik `drive` → user, `infra-admins` → admin. The mapping is a claim, evaluated at every login; the first login autoprovisions the account in the built-in idm (username = Authentik username, e-mail + display name copied).
- **Break-glass**: the local `admin` (password `OC_ADMIN_PASSWORD`, set on the first start only). To use it during an Authentik outage, set `PROXY_ENABLE_BASIC_AUTH=true` temporarily and recreate `opencloud`; turn it off again afterwards.
- App tokens survive an IdP account being disabled (OpenCloud's documented caveat) — revoke them in OpenCloud when a person leaves.

## State, backup, restore

| What | Where | Backup |
|---|---|---|
| Files, spaces, trash, versions, system data | `OC_DATA_DIR` (`/home/gonzalo/docker/cn-opencloud/data`, owner 1000, 0700) | restic (`scripts/backup.sh`, Sunday 06:00): snapshot → `raidnas:/volume1/data/backups/cn-opencloud/restic`, then `restic copy` → `s3://cloudnet-lab-storage/opencloud-restic`; keep 8 weekly / 6 monthly in both; search index and thumbnails excluded (rebuilt) |
| `opencloud.yaml` (retained secrets) | `config/opencloud/` | Kauket `kaiser.cn_opencloud_yaml` + inside every restic snapshot |
| `RESTIC_PASSWORD`, `OC_ADMIN_PASSWORD`, Tailscale key | `.env` | Kauket `kaiser.cn_opencloud_env` |
| `ts_state` volume | Docker | disposable (new preauth key) |

Upstream wants the instance **stopped** for a consistent backup. The scheduled run is online (a file written during the few minutes of restic lands in the next snapshot; xattrs are preserved); `scripts/backup.sh --stop` does the by-the-book version (stops the watchdog and `opencloud` for the duration — the reconciler would otherwise restart it within five minutes, so keep manual runs short). Prove a run by hand: `scripts/backup.sh`, then `docker compose run --rm backup snapshots` and the same against `$S3_REPOSITORY`. **Restore**: `kauket get` both secrets, `./setup.sh` once so the dirs exist, stop `opencloud`, `restic restore latest --target /` into the data + config paths (ownership 1000:1000), start, then `docker compose exec opencloud opencloud posixfs consistency` and `opencloud posixfs index`. The textfile metric `opencloud_backup_last_success_timestamp_seconds` feeds the VPS alert `OpenCloudBackupStale` (> 8 days).

## Observability

Dashboard: **OpenCloud (cn-opencloud)** on `https://grafana.lab.gn.al` (uid `opencloud`), generated by `grafana/build-dashboard.py` into `cn-root-docker/tailnet/grafana/provisioning/dashboards/opencloud.json` — probe/TLS, request rate and error ratio, latency percentiles, TUS upload sessions and throughput, post-processing/search backlog and durations, thumbnail latency, backup age and duration, process memory, kaiser disk/CPU, and the stack's Loki stream. Re-run the builder after editing and recreate the VPS `grafana` container.

VPS plane: jobs `opencloud-node` (`drive.ts.gn.al:9400` — 9100 belongs to OpenCloud's `web` service inside the netns; with `opencloud_backup_*` from `./textfile`) and `opencloud` (`drive.ts.gn.al:9205` — proxy metrics `opencloud_proxy_requests_total`, `_errors_total`, `_duration_seconds`), probe `https://drive.lab.gn.al/status.php` (200, unauthenticated JSON), promtail → VPS Loki under `stack=cn-opencloud`, alert group `cn-opencloud`. LAN plane: kaiser probes `https://drive.kaiser.lan` (301). Glance and dynacat list it under Apps.

Health first: `docker compose ps` · `curl -s https://drive.lab.gn.al/status.php` · `docker compose logs --tail=100 opencloud` (JSON lines) · `docker compose exec opencloud opencloud posixfs consistency`.

## Gotchas

- **A crash-looping first start leaves half-initialised state.** On 2026-11-07 the `web` port clash made the supervisor restart services for minutes; afterwards `data/search/bleve` held an unreadable index ("error parsing mapping JSON") and `data/idm/idm.boltdb` lacked the service users (`uid=reva`/`uid=libregraph` bind → "not found", every OIDC login died with "Autoprovisioning user failed"). On an instance with no users yet: stop, remove/rename those two, start — idm and search re-bootstrap from the env/`opencloud.yaml`. Never do this on an instance that already has users (idm holds them).
- **App tokens are passphrases** ("word word word …"): treat any log that prints `token:` as a leak; revoke via `DELETE /auth-app/tokens?token=…` (see `scripts/app-token.sh`).

- **Never `opencloud init --force-overwrite`**: it regenerates the secrets and the storage mount id baked into every space id. `init --diff` + `patch` is the upgrade path.
- **`/etc/opencloud` must be writable by uid 1000** (the init step writes there); `setup.sh` creates both dirs with that owner.
- **Environment beats `opencloud.yaml`**: everything configured here is env; the YAML only holds what init generated.
- **No basic auth by default** — WebDAV clients and rclone need an app token (`scripts/app-token.sh`), not the password.
- **CSP**: `csp.yaml` must list the IdP (`auth.lab.gn.al`) in `connect-src`/`frame-src`/`script-src`, or the web client's silent token renewal fails after the first hour.
- **Thumbnails** exist for images/text/audio only; PDFs and office files show an icon (previewing PDFs still works in the viewer). Office editing needs Collabora (follow-up).
- **Watchtower** on kaiser (`cn-books-watchtower-1`) is told to skip the pinned image; the sidecar and exporters float.
- **Native clients** (desktop `OpenCloudDesktop`, iOS `OpenCloudIOS`, Android `OpenCloudAndroid`) need one public Authentik provider each, all sharing one signing key in **global issuer mode**, `OC_OIDC_ISSUER=https://auth.lab.gn.al/`, and a `replacePath` of `/.well-known/openid-configuration` → `/application/o/opencloud/.well-known/openid-configuration` on both Authentik edges (neptune `cn-authentik/traefik-lan`, VPS `traefik-lab`). Deferred because it touches the shared identity edge.
