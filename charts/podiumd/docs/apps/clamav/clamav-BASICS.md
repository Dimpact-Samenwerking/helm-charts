# ClamAV — Basics

## Management summary

ClamAV is the virus scanner of the PodiumD stack. Files that residents upload — most notably attachments submitted through Open Formulieren web forms — are checked against a database of known malware before they enter the municipality's systems. It runs as a single always-on scanning service inside the cluster; other applications send files to it and get a clean/infected verdict back. To run it needs roughly 2–3 GiB of memory (the entire virus database is loaded into RAM), a small 2 GiB disk for the signature database, and outbound internet access to the official ClamAV update servers so the signatures stay current. It is not reachable from outside the cluster.

## What it is

- **Upstream:** [ClamAV](https://www.clamav.net/) — open-source antivirus engine (clamd daemon + freshclam signature updater).
- **Image:** `clamav/clamav:1.5.2` (tag pinned in `values.yaml`; repository default from subchart).
- **Chart:** wiremind `clamav` subchart **v3.7.1** (`@wiremind` in `Chart.yaml`), vendored as `charts/podiumd/charts/clamav-3.7.1.tgz`.
- **Role in PodiumD:** cluster-internal scan endpoint for file uploads. Open Formulieren is the primary consumer (virus scan of form attachments).
- **Runtime components:**
  - `clamav-0` — **StatefulSet, 1 replica**. One container running clamd (TCP 3310) with freshclam updating signatures in-place; config injected via `clamav.clamdConfig` and `clamav.freshclamConfig` in `values.yaml`.
  - ClusterIP Service `clamav` (`fullnameOverride: clamav`), port **3310/TCP** (`tcp-clamav`) — clamd's own protocol, not HTTP.
  - Optional metrics sidecar `docker.io/sergeymakinen/clamav_exporter:v2.1.8` + ServiceMonitor, off by default (`clamav.metrics.enabled` / `clamav.metrics.serviceMonitor.enabled`), enabled by the `values-enable-observability.yaml` overlay. ServiceMonitor requires the Prometheus Operator CRD.

Notable clamd settings from `values.yaml`: `ConcurrentDatabaseReload no` (reload database sequentially to avoid double memory usage, ~1.2 GiB vs ~2.4 GiB; scans block briefly during reload), `MaxScanSize 150M`, `MaxFileSize 100M`, `StreamMaxLength 100M` (upload-size ceiling for stream scans), `MaxThreads 10`.

## Required resources

### Database

No PostgreSQL. ClamAV has no relational database and no `DB_*` Secret/ConfigMap contract. Its "database" is the virus signature set (`main.cvd`, `daily.cvd`, `bytecode.cvd`) stored on the PVC and kept current by freshclam.

### Storage

Yes — one PVC for the signature database:

- `clamav.persistentVolume.enabled: true`, **size 2Gi**, **storageClass `managed-csi`** (Azure Disk).
- Note: this deviates from the usual `podiumd-standard` Azure Files convention; there is no `volumeAttributeShareName` — the volume is dynamically provisioned.
- The subchart hardcodes the mount at `/data`; the podiumd values add `extraVolumeMounts` to also mount the same volume at `/var/lib/clamav`, so the official image's entrypoint sees `/var/lib/clamav/main.cvd` and correctly runs freshclam synchronously on first boot with an empty volume (cold-start bootstrap).

### Routing / exposure (NGINX Gateway Fabric)

**Cluster-internal only.** No HTTPRoute, no public hostname. Consumers reach it at `clamav.podiumd.svc.cluster.local:3310` (clamd TCP protocol).

### Other dependencies

- **Outbound egress for signature updates** (must be allowlisted in any NetworkPolicy / egress firewall):
  - `current.cvd.clamav.net` — DNS TXT (UDP/TCP 53), version check.
  - `database.clamav.net` — HTTPS (TCP 443), CDN download mirror (`clamav.freshclamConfig` `DatabaseMirror database.clamav.net`).
  See [clamav-security-updates.md](clamav-security-updates.md) for details and proxy options.
- No Redis, no Keycloak client, no Open Zaak / Open Notificaties registration, no SMTP.
- Consumers: Open Formulieren (file-upload virus scanning — enable via
  `openformulieren.clamavConfigJob.enabled: true`, off by default, since
  upstream has no declarative config for it; see
  `docs/apps/openforms/openforms-BASICS.md` and
  `docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-gemeente-specific.md`); any other app
  that speaks the clamd protocol can use the same service.

## CPU and memory

Chart defaults (`clamav.resources` in `values.yaml`, confirmed in `docs/misc/resource-overview.md`):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| clamav | 250m | 2Gi | 1000m | 3Gi |

**Observed usage** (kubectl top, 2026-07-10): `clamav-0` at **1m / 1037Mi** on ontw and **1m / 1003Mi** on accp — CPU is near zero at idle (it spikes only while scanning), and memory sits around 1 GiB because the full virus database is resident in RAM. The 2Gi request / 3Gi limit is sized for database reloads: even with `ConcurrentDatabaseReload no` the reload briefly needs ~1.2 GiB (it would be ~2.4 GiB with concurrent reload). resource-overview.md considers the 2Gi request well-fitted; no change needed for production. **No PDB** — single replica; a PDB would block node drains.

Startup: cold start loads ~3.2M signatures from disk; the startup probe allows up to 5 minutes (`initialDelaySeconds: 60`, `periodSeconds: 30`, `failureThreshold: 9`). First boot on an empty PVC additionally downloads the full database before clamd starts.

## Integrating ClamAV as a new app

1. **Egress:** allowlist `current.cvd.clamav.net` (DNS TXT, port 53) and `database.clamav.net` (HTTPS 443) in NetworkPolicies / egress firewall. Behind an HTTP proxy, set `HTTPProxyServer` / `HTTPProxyPort` in `clamav.freshclamConfig`.
2. **Enable:** ClamAV is deployed by default — the chart defaults set no top-level `clamav.enabled` key, and Helm treats the Chart.yaml condition `clamav.enabled` as satisfied when the path is absent. Set `clamav.enabled: false` in gemeente values to opt out. Keep the image tag pinned (`clamav.image.tag`).
3. **Storage:** nothing to pre-provision — the 2Gi `managed-csi` PVC is created by the chart (`clamav.persistentVolume`).
4. **First boot:** expect a slow start on an empty volume — the entrypoint runs freshclam synchronously to download the full signature database before clamd starts, then signature loading takes minutes. Watch `kubectl logs -n podiumd clamav-0` for freshclam download progress and `clamd started`.
5. **Wire up consumers:** point the consuming application at host `clamav` (or `clamav.podiumd.svc.cluster.local`), port `3310`. For Open Formulieren, either configure this manually in the admin interface (virus-scan / ClamAV settings) or set `openformulieren.clamavConfigJob.enabled: true` to have a Job do it declaratively (see `docs/apps/openforms/openforms-BASICS.md`).
6. **Optional monitoring:** apply the `values-enable-observability.yaml` overlay (or set `clamav.metrics.enabled: true` and `clamav.metrics.serviceMonitor.enabled: true`) for the Prometheus exporter sidecar.
7. **Verify:**
   - `kubectl get pods -n podiumd clamav-0` — Running and Ready (startup probe passed).
   - `kubectl logs -n podiumd clamav-0` — freshclam reports the database up to date; no `WARNING: Can't download` errors (egress problem indicator).
   - Functional check: upload an [EICAR test file](https://www.eicar.org/download-anti-malware-testfile/) through a consuming app (e.g. an Open Formulieren form with file upload) and confirm it is rejected.

## Related documents

- [clamav-security-updates.md](clamav-security-updates.md) — log of security-relevant ClamAV updates and configuration fixes, plus the network/egress requirements for freshclam database updates.
