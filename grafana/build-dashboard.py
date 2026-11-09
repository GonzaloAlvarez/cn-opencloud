#!/usr/bin/env python3
"""Generate the OpenCloud dashboard for the VPS Grafana (grafana.lab.gn.al).

Output (committed into cn-root-docker's provisioning dir):
  <cn-root-docker>/tailnet/grafana/provisioning/dashboards/opencloud.json   uid: opencloud

Metric sources (VPS-plane scrapes of drive.ts.gn.al): OpenCloud's proxy debug server on :9205
(job=opencloud: opencloud_proxy_requests_total/errors_total/duration_seconds, reva_upload_*,
opencloud_postprocessing_*, opencloud_search_*, opencloud_thumbnails_*, process_*), the stack's
node-exporter on :9400 (job=opencloud-node, incl. the opencloud_backup_* textfile metrics from
scripts/backup.sh), blackbox-tailnet-http (https://drive.lab.gn.al/status.php), promtail → Loki
(stack=cn-opencloud). Re-run after editing; keep the uid stable; recreate the VPS grafana to load it.

    ./build-dashboard.py [path/to/cn-root-docker]   (default ../../cn-root-docker)
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
PROBE = 'instance="https://drive.lab.gn.al/status.php"'
OKFAIL = [{"type": "value", "options": {"0": {"text": "FAIL", "color": "red"}, "1": {"text": "OK", "color": "green"}}}]
UPDOWN = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]
GREEN_ON_1 = [{"color": "red", "value": None}, {"color": "green", "value": 1}]
RED_ON_1 = [{"color": "green", "value": None}, {"color": "red", "value": 1}]


def q(expr, legend=None, ref="A", instant=False, fmt=None):
    t = {"datasource": PROM, "expr": expr, "refId": ref}
    if legend:
        t["legendFormat"] = legend
    if instant:
        t["instant"] = True
    if fmt:
        t["format"] = fmt
    return t


def row(pid, title, y):
    return {"id": pid, "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(pid, title, targets, x, y, w, h, unit=None, thresholds=None, decimals=None, mappings=None, color_mode="value", graph="none"):
    fc = {"thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]}}
    if unit:
        fc["unit"] = unit
    if decimals is not None:
        fc["decimals"] = decimals
    if mappings:
        fc["mappings"] = mappings
    return {"id": pid, "type": "stat", "title": title, "datasource": PROM, "targets": targets,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": color_mode, "graphMode": graph, "textMode": "auto", "orientation": "auto"}}


def ts(pid, title, targets, x, y, w, h, unit=None, min_=None, max_=None, stack=False):
    fc = {"custom": {"lineWidth": 1, "fillOpacity": 10, "showPoints": "never"}}
    if stack:
        fc["custom"]["stacking"] = {"mode": "normal", "group": "A"}
    if unit:
        fc["unit"] = unit
    if min_ is not None:
        fc["min"] = min_
    if max_ is not None:
        fc["max"] = max_
    return {"id": pid, "type": "timeseries", "title": title, "datasource": PROM, "targets": targets,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def gauge(pid, title, targets, x, y, w, h, unit="percent", thresholds=None):
    steps = thresholds or [{"color": "green", "value": None}, {"color": "orange", "value": 75}, {"color": "red", "value": 90}]
    return {"id": pid, "type": "gauge", "title": title, "datasource": PROM, "targets": targets,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": 100, "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "showThresholdLabels": False, "showThresholdMarkers": True}}


def bargauge(pid, title, targets, x, y, w, h, unit=None):
    fc = {"thresholds": {"mode": "absolute", "steps": [{"color": "blue", "value": None}]}}
    if unit:
        fc["unit"] = unit
    return {"id": pid, "type": "bargauge", "title": title, "datasource": PROM, "targets": targets,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                        "valueMode": "color", "namePlacement": "left", "sizing": "auto", "minVizHeight": 14, "minVizWidth": 8}}


def table(pid, title, targets, x, y, w, h, exclude=()):
    hide = {k: True for k in ("Time", "__name__", "job", "instance", "host", "stack", "app", "Value") + tuple(exclude)}
    return {"id": pid, "type": "table", "title": title, "datasource": PROM, "targets": targets,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "fieldConfig": {"defaults": {}, "overrides": []},
            "transformations": [{"id": "labelsToFields", "options": {}}, {"id": "organize", "options": {"excludeByName": hide}}],
            "options": {"showHeader": True}}


def logs(pid, title, expr, x, y, w, h):
    return {"id": pid, "type": "logs", "title": title, "datasource": LOKI,
            "targets": [{"datasource": LOKI, "expr": expr, "refId": "A"}],
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                        "dedupStrategy": "none", "enableLogDetails": True, "prettifyLogMessage": False}}


def dashboard(uid, title, tags, panels):
    return {"annotations": {"list": []}, "editable": True, "graphTooltip": 1, "links": [], "panels": panels,
            "refresh": "30s", "schemaVersion": 39, "tags": tags, "templating": {"list": []},
            "time": {"from": "now-6h", "to": "now"}, "timezone": "browser", "title": title, "uid": uid, "version": 1}


def build():
    p, y = [], 0
    rate = 'sum(rate(opencloud_proxy_requests_total[5m]))'
    err = 'sum(rate(opencloud_proxy_errors_total[5m]))'
    p.append(row(1, "At a glance", y)); y += 1
    p.append(stat(2, "Ingress probe (drive.lab.gn.al)", [q(f"probe_success{{{PROBE}}}")], 0, y, 3, 4, mappings=UPDOWN, color_mode="background", thresholds=GREEN_ON_1))
    p.append(stat(3, "Probe latency", [q(f"probe_duration_seconds{{{PROBE}}}")], 3, y, 3, 4, unit="s", decimals=2,
                  thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 3}]))
    p.append(stat(4, "TLS days remaining", [q(f"(probe_ssl_earliest_cert_expiry{{{PROBE}}} - time()) / 86400")], 6, y, 3, 4, unit="d", decimals=0,
                  thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 14}, {"color": "green", "value": 30}]))
    p.append(stat(5, "Metrics scrape (proxy :9205)", [q('up{job="opencloud"}')], 9, y, 3, 4, mappings=UPDOWN, color_mode="background", thresholds=GREEN_ON_1))
    p.append(stat(6, "Requests / s", [q(rate)], 12, y, 3, 4, unit="reqps", decimals=2, graph="area"))
    p.append(stat(7, "Error ratio (5m)", [q(f"({err}) / clamp_min({rate}, 0.001) * 100")], 15, y, 3, 4, unit="percent", decimals=1,
                  thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 2}, {"color": "red", "value": 10}]))
    p.append(stat(8, "Active uploads", [q("reva_upload_active")], 18, y, 3, 4, decimals=0, graph="area"))
    p.append(stat(9, "Last backup (restic → NAS + S3)", [q("opencloud_backup_last_success_timestamp_seconds * 1000")], 21, y, 3, 4, unit="dateTimeFromNow"))
    y += 4
    p.append(row(10, "Traffic (proxy)", y)); y += 1
    p.append(ts(11, "Requests by method", [q("sum by (method) (rate(opencloud_proxy_requests_total[5m]))", "{{method}}")], 0, y, 8, 7, unit="reqps", min_=0, stack=True))
    p.append(ts(12, "Errors by method", [q("sum by (method) (rate(opencloud_proxy_errors_total[5m]))", "{{method}}")], 8, y, 8, 7, unit="reqps", min_=0))
    p.append(ts(13, "Latency p50 / p95", [q("histogram_quantile(0.5, sum by (le) (rate(opencloud_proxy_duration_seconds_bucket[5m])))", "p50"),
                                          q("histogram_quantile(0.95, sum by (le) (rate(opencloud_proxy_duration_seconds_bucket[5m])))", "p95", ref="B")], 16, y, 8, 7, unit="s", min_=0))
    y += 7
    p.append(row(20, "Uploads and post-processing (reva / TUS)", y)); y += 1
    p.append(ts(21, "Upload sessions / s", [q("rate(reva_upload_sessions_initiated[5m])", "initiated"), q("rate(reva_upload_sessions_finalized[5m])", "finalized", ref="B"),
                                            q("rate(reva_upload_sessions_aborted[5m])", "aborted", ref="C"), q("rate(reva_upload_sessions_restarted[5m])", "restarted", ref="D")], 0, y, 8, 7, min_=0))
    p.append(ts(22, "Upload throughput", [q("rate(reva_upload_sessions_bytes_received[5m])", "bytes/s")], 8, y, 8, 7, unit="Bps", min_=0))
    p.append(ts(23, "Post-processing / search backlog", [q("opencloud_postprocessing_events_unprocessed", "postprocessing unprocessed"),
                                                        q("opencloud_search_events_unprocessed", "search unprocessed", ref="B"),
                                                        q("reva_upload_processing", "uploads processing", ref="C")], 16, y, 8, 7, min_=0))
    y += 7
    p.append(ts(24, "Post-processing duration p95", [q("histogram_quantile(0.95, sum by (le) (rate(opencloud_postprocessing_duration_seconds_bucket[5m])))", "p95")], 0, y, 8, 6, unit="s", min_=0))
    p.append(ts(25, "Search indexing duration p95", [q("histogram_quantile(0.95, sum by (le) (rate(opencloud_search_index_duration_seconds_bucket[5m])))", "p95")], 8, y, 8, 6, unit="s", min_=0))
    p.append(ts(26, "Thumbnail generation p95", [q("histogram_quantile(0.95, sum by (le) (rate(opencloud_thumbnails_getthumbnail_duration_seconds_bucket[5m])))", "p95")], 16, y, 8, 6, unit="s", min_=0))
    y += 6
    p.append(row(30, "Backup and process", y)); y += 1
    p.append(stat(31, "Backup age", [q("time() - opencloud_backup_last_success_timestamp_seconds")], 0, y, 4, 4, unit="s", decimals=0,
                  thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 8 * 86400}, {"color": "red", "value": 15 * 86400}]))
    p.append(stat(32, "Last backup duration", [q("opencloud_backup_duration_seconds")], 4, y, 4, 4, unit="s", decimals=0))
    p.append(ts(33, "OpenCloud process memory (RSS)", [q('process_resident_memory_bytes{job="opencloud"}', "rss")], 8, y, 8, 4, unit="bytes", min_=0))
    p.append(ts(34, "Goroutines", [q('go_goroutines{job="opencloud"}', "goroutines")], 16, y, 8, 4, min_=0))
    y += 4
    p.append(ts(35, "Data volume used on kaiser (/, SSD — the PosixFS tree lives there)", [q('(1 - node_filesystem_avail_bytes{job="opencloud-node",mountpoint="/"} / node_filesystem_size_bytes{job="opencloud-node",mountpoint="/"}) * 100', "/ %")], 0, y, 12, 6, unit="percent", min_=0, max_=100))
    p.append(ts(36, "kaiser CPU (seen from the stack's node-exporter)", [q('(1 - avg(rate(node_cpu_seconds_total{job="opencloud-node",mode="idle"}[5m]))) * 100', "cpu %")], 12, y, 12, 6, unit="percent", min_=0, max_=100))
    y += 6
    p.append(row(40, "Logs (VPS Loki, stack=cn-opencloud)", y)); y += 1
    p.append(logs(41, "Errors / warnings / auth", '{stack="cn-opencloud"} |~ "(?i)\\"level\\":\\"(error|warn)\\"|autoprovision|authentication|backup"', 0, y, 24, 10))
    return dashboard("opencloud", "OpenCloud (cn-opencloud)", ["homelab", "cn-opencloud", "opencloud"], p)


def main():
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent.parent / "cn-root-docker"
    out = root / "tailnet" / "grafana" / "provisioning" / "dashboards"
    if not out.is_dir():
        sys.exit(f"cn-root-docker provisioning dir not found: {out}")
    d = build()
    ids = [x["id"] for x in d["panels"]]
    assert len(ids) == len(set(ids)), "duplicate panel ids"
    (out / "opencloud.json").write_text(json.dumps(d, indent=2) + "\n")
    print(f"wrote {out / 'opencloud.json'} ({len(ids)} panels)")


if __name__ == "__main__":
    main()
