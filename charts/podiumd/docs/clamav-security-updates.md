# ClamAV Security Updates

This document logs all security-relevant updates and configuration fixes for ClamAV as managed by this chart.
Each entry records: what changed, why it matters, what was discovered, and how it is implemented.

## Network requirements — ClamAV database update endpoints

Freshclam requires outbound access to the following endpoints. These must be allowlisted in any network
policy or egress firewall rules for ClamAV to keep its virus database current.

| Endpoint | Protocol/Port | Purpose |
|---|---|---|
| `current.cvd.clamav.net` | DNS TXT query (UDP/TCP 53) | Version check — freshclam first queries this DNS TXT record to determine whether a database update is available before downloading anything |
| `database.clamav.net` | HTTPS (TCP 443) | Primary download mirror — resolves to a CDN, actual files downloaded are `daily.cvd`, `main.cvd`, `bytecode.cvd` |

**How it works:**
1. Freshclam resolves `current.cvd.clamav.net` as a DNS TXT record to get the current version numbers
2. If a newer version is available, it downloads the updated `.cvd` (or `.cdiff` patch) files from `https://database.clamav.net/`
3. Each downloaded file is tested before replacing the live database
4. If DNS TXT is unavailable, freshclam falls back to full HTTP download (wastes bandwidth)

> If the cluster uses an HTTP proxy, set `HTTPProxyServer` and `HTTPProxyPort` in `freshclamConfig`.
> If DNS TXT records are blocked, add `--enable-dns-fix` or accept that freshclam will always do a full
> download instead of a version check first.

---

## 2026-03-27 — ClamAV update to 1.4.4 + chart 3.7.1 + config fixes

### Summary

A security review of the running ClamAV instance on `aks-blue-ontw-info` revealed that **freshclam was not
running and the virus database had never been updated** since the image was built (June 16, 2025 — 9+ months
stale). Three separate issues contributed to this. All were fixed as part of upgrading to ClamAV 1.4.4 and
Helm chart 3.7.1.

---

### Issue 1 — Freshclam crash: `UpdateLogFile /dev/stdout` symlink loop

| Field | Detail |
|---|---|
| **Severity** | 🔴 Critical — freshclam never starts |
| **Affected versions** | All prior releases |
| **Symptom** | `ERROR: Failed to open log file /dev/stdout: Symbolic link loop` / `ERROR: initialize: libfreshclam init failed` |

**What happened:** The `freshclamConfig` in `values.yaml` contained `UpdateLogFile /dev/stdout`. In the
official `clamav/clamav` Docker image, `/dev/stdout` is a symlink that creates a circular reference when
freshclam attempts to open it as a log file. Freshclam crashes at initialisation on every pod start.

**Fix:** Removed `UpdateLogFile /dev/stdout` from `freshclamConfig`. Freshclam will log to the standard
output of the container process via its default behaviour without an explicit `UpdateLogFile` directive.

---

### Issue 2 — Database not persisted: data volume mounted at `/data`, not `/var/lib/clamav`

| Field | Detail |
|---|---|
| **Severity** | 🟠 High — database updates not persisted |
| **Affected versions** | All prior releases |

**What happened:** The older chart values mounted the ClamAV data volume at `/data`. Even if freshclam had
run successfully, it would have written virus database updates to ephemeral container storage at
`/var/lib/clamav`, not to the persistent volume, so database updates would be lost on every pod restart.

**Fix:** Standardised on `DatabaseDirectory /var/lib/clamav` and updated the chart values to mount the
persistent volume at `/var/lib/clamav` (via `extraVolumeMounts`) so that both `clamd` and `freshclam`
read and write their database files on persistent storage. The official `clamav/clamav` entrypoint also
uses `/var/lib/clamav` to detect whether a cold-start DB download is needed before starting clamd.

---

### Issue 3 — No persistent volume: `clamav-data` was an `emptyDir`

| Field | Detail |
|---|---|
| **Severity** | 🟠 High — database lost on every restart |
| **Affected versions** | All prior releases |

**What happened:** `persistentVolume.enabled` was `false` (chart default). The `clamav-data` volume was
an `emptyDir`, meaning the virus database is discarded on every pod restart and freshclam must re-download
the full database (~235 MB) from scratch each time.

**Fix:** Set `persistentVolume.enabled: true` with `size: 2Gi` and `storageClass: managed-csi`. The virus database is now persisted
across pod restarts, and freshclam only downloads incremental updates (`ScriptedUpdates yes`).

---

### Issue 4 — ClamAV image 1.4.2 — three unpatched CVEs

| CVE | Severity | Fixed in | Description |
|---|---|---|---|
| [CVE-2025-20260](https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2025-20260) | 🔴 Critical | 1.4.3 | PDF parser buffer overflow — DoS or potential remote code execution |
| [CVE-2025-20234](https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2025-20234) | 🔴 Critical | 1.4.3 | UDF parser buffer overflow — information disclosure or DoS |
| [CVE-2026-20031](https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2026-20031) | 🔴 Critical | 1.4.4 | HTML parser error handling bug — DoS condition (present since 1.1.0) |

Additional fixes in 1.4.3 and 1.4.4:
- Fixed use-after-free in Xz/lzma decompression module
- Fixed crash when scanning TIFF files
- Fixed crash on invalid pointer alignment on some platforms
- Upgraded Rust `bytes` dependency (resolves RUSTSEC-2026-0007)

**Fix:** Updated `image.tag` from `1.4.2` to `1.4.4`.

---

### Issue 5 — Helm chart 3.2.0 outdated

| Field | Detail |
|---|---|
| **Previous version** | 3.2.0 (appVersion 1.4.1) |
| **New version** | 3.7.1 (appVersion 1.4.3) |

Notable chart changes between 3.2.0 and 3.7.1:
- Workload now supports `kind: StatefulSet / Deployment / DaemonSet` (was always StatefulSet)
- Added `topologySpreadConstraints`, `updateStrategy`, `extraArgs`
- Added optional Prometheus metrics sidecar (`metrics.enabled`)
- `clamdConfig` / `freshclamConfig` plain-text format remains supported alongside new `clamdConfigDict` YAML format

**Fix:** Updated chart dependency from `3.2.0` to `3.7.1` in `Chart.yaml`.

---

### Net result

After this update:
- Freshclam starts correctly on pod initialisation and downloads current virus definitions
- Virus database is persisted to a 2Gi PVC and only incrementally updated on restart
- All three CVEs are patched in the running image
- The chart is current

### Known open item — `DisableCertCheck yes`

The current `clamdConfig` contains `DisableCertCheck yes`, which disables ClamAV's Authenticode PE
certificate validation. This is intentional: users of PodiumD regularly upload documents signed by
internal Dutch government PKI certificates (e.g. PKIoverheid) that are not in the public certificate
store available to ClamAV. Enabling certificate checks would cause false positives on legitimately
signed government documents. This setting should remain `yes` unless ClamAV can be configured with
the relevant government CA certificates.

---

### Known limitation — `TCPAddr` cannot be restricted to localhost

ClamAV exposes its scan socket on TCP port 3310 via the `clamav` ClusterIP service. Other pods in the
cluster (e.g., Open Formulieren) connect to `clamav.podiumd.svc.cluster.local:3310`. Setting
`TCPAddr localhost` causes clamd to bind only to the loopback interface, which makes the ClusterIP service
unreachable and breaks all network-based scanning. The socket is therefore bound to all interfaces
(`INADDR_ANY`) by default, which is required for in-cluster use. Access control should be enforced at
the network policy level rather than at the socket level.

---

### Known limitation — `EnableShutdownCommand` not supported

`EnableShutdownCommand no` (which prevents remote shutdown via the clamd socket) was investigated but
is **not a valid option** in ClamAV 1.4.4 — clamd rejects the config file with a parse error if it is
present. It is not listed in `clamd.conf.sample` for this version. It has been omitted from the config.

---

### Files changed

| File | Change |
|---|---|
| `Chart.yaml` | `clamav` dependency `3.2.0` → `3.7.1` |
| `values.yaml` | `image.tag` `1.4.2` → `1.4.4`; removed `UpdateLogFile /dev/stdout`; `DatabaseDirectory` kept at `/var/lib/clamav`; `persistentVolume.enabled: true`, `size: 2Gi`, `storageClass: managed-csi`; added `extraVolumeMounts` to mount PVC at `/var/lib/clamav`; CPU request `1000m` → `250m`; memory request `4Gi` → `2Gi`; added memory limit `3Gi` |

---

## PodDisruptionBudget (PDB) configuration

The ClamAV chart supports a PodDisruptionBudget via `podDisruptionBudget` in values. It is disabled by
default (`podDisruptionBudget.enabled: false`). This section explains when and how to configure it.

### Background

ClamAV runs as a `StatefulSet` with `replicaCount: 1` by default (HPA can scale it up to 5 replicas).
A PDB controls how many pods may be unavailable during voluntary disruptions such as node drains, upgrades,
or cluster maintenance.

A PDB only protects against **voluntary disruptions** (node drain, rolling upgrade, eviction). It does not
protect against node failures or OOM kills.

### When to enable a PDB

| Scenario | Recommendation |
|---|---|
| `replicaCount: 1` (default) | Use `maxUnavailable: 1` — allows maintenance, accepts brief unavailability |
| `replicaCount: 2+` | Use `minAvailable: 1` — keeps at least one instance available during drain |
| Strict availability SLA | Use `minAvailable: 1` with `replicaCount: 2+` to avoid any scanning downtime |

> ⚠️ **Never set `minAvailable: 1` with `replicaCount: 1`** — this blocks all node drains and will
> prevent cluster upgrades from completing.

### Configuration

#### Single replica (default) — allow maintenance, accept brief unavailability

```yaml
clamav:
  replicaCount: 1
  podDisruptionBudget:
    enabled: true
    maxUnavailable: 1
```

This is the recommended default for most environments. Node drains proceed normally; ClamAV may be briefly
unavailable during the drain window.

#### Multiple replicas — always keep one available

```yaml
clamav:
  replicaCount: 2  # or higher
  hpa:
    enabled: false  # disable HPA if using fixed replicaCount
  podDisruptionBudget:
    enabled: true
    minAvailable: 1
```

Use this when ClamAV availability must be maintained during cluster maintenance (e.g., production
environments with strict SLAs on virus scanning).

#### With HPA (auto-scaling)

When HPA is enabled (`hpa.enabled: true`, the default), the replica count is managed automatically.
A percentage-based approach avoids conflicts with HPA scaling:

```yaml
clamav:
  podDisruptionBudget:
    enabled: true
    minAvailable: 1  # always keep at least 1 available
```

HPA will scale between 1 and 5 replicas based on CPU. The PDB ensures at least 1 replica is always
available as long as more than 1 is running.

### Important notes

- The PDB is a **cluster-scoped protection** for voluntary disruptions only. It does not affect pod
  scheduling, resource requests, or node affinity.
- On **aks-blue clusters**, node pool upgrades (via pipeline) honour PDBs — ensure `maxUnavailable: 1`
  is set if `replicaCount: 1` to prevent upgrade deadlocks.
- The PDB setting lives in environment-specific values files (e.g. `temp-ontw-dim1.yaml`) if different
  environments require different availability guarantees. The base `values.yaml` leaves it disabled.

