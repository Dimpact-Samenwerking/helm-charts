# ClamAV Security Updates

This document logs all security-relevant updates and configuration fixes for ClamAV as managed by this chart.
Each entry records: what changed, why it matters, what was discovered, and how it is implemented.

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

### Issue 2 — Wrong `DatabaseDirectory`: `/var/lib/clamav` instead of `/data`

| Field | Detail |
|---|---|
| **Severity** | 🟠 High — database updates not persisted |
| **Affected versions** | All prior releases |

**What happened:** Both `clamdConfig` and `freshclamConfig` set `DatabaseDirectory /var/lib/clamav`, but
the Helm chart mounts the data volume at `/data`. Even if freshclam had run successfully, it would have
written virus database updates to ephemeral container storage (`/var/lib/clamav`), not to the persistent
volume at `/data`. Database updates would be lost on every pod restart.

**Fix:** Changed `DatabaseDirectory` to `/data` in both `clamdConfig` and `freshclamConfig` to align with
the volume mount path used by the chart.

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
- Virus database is persisted to a 500Mi PVC and only incrementally updated on restart
- All three CVEs are patched in the running image
- The chart is current

### Files changed

| File | Change |
|---|---|
| `Chart.yaml` | `clamav` dependency `3.2.0` → `3.7.1` |
| `values.yaml` | `image.tag` `1.4.2` → `1.4.4`; `DatabaseDirectory` `/var/lib/clamav` → `/data`; removed `UpdateLogFile /dev/stdout`; `persistentVolume.enabled: true`, `size: 2Gi`, `storageClass: managed-csi`; CPU request `1000m` → `250m`; memory request `4Gi` → `2Gi`; added memory limit `4Gi` |

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

