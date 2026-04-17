# Upgrade guide: PodiumD 4.6.3 → 4.6.4

## Required manual steps before upgrading

### `zgw-office-addin` — breaking values schema change

The `zgw-office-addin` subchart restructured its values. Any environment values file that sets the following keys must be updated before upgrading:

| Old key | New key |
|---|---|
| `zgw-office-addin.frontend.frontendUrl` | `zgw-office-addin.common.frontendUrl` |
| `zgw-office-addin.backend.apiBaseUrl` | `zgw-office-addin.backend.zgwApis.url` |
| `zgw-office-addin.backend.jwtSecret` | `zgw-office-addin.backend.zgwApis.secret` |

```yaml
# Before
zgw-office-addin:
  frontend:
    frontendUrl: https://office-addin.example.nl
  backend:
    apiBaseUrl: "https://openzaak.example.nl"
    jwtSecret: "secret"

# After
zgw-office-addin:
  common:
    frontendUrl: https://office-addin.example.nl
  backend:
    zgwApis:
      url: "https://openzaak.example.nl"
      secret: "secret"
```

The Helm upgrade will fail with a schema validation error if these keys are not renamed.

---

## Changes

### ZAC helm chart updated to 1.0.224

The ZAC subchart has been updated from 1.0.208 to 1.0.224 (ZAC 4.7).

---

### ZAC liveness probe changed to `/health/ready` (fixes known issue)

This release resolves the known issue from 4.6.3 where ZAC did not recover automatically after extended OpenZaak/catalogus unavailability.

The ZAC liveness probe path has been changed from `/health/live` to `/health/ready` with `failureThreshold: 16` (16 × 30 s = 480 s). Kubernetes will now automatically restart ZAC after ~8 minutes of catalogus unavailability without manual intervention.

**Root cause:** The ZGW-API-Client MicroProfile REST client has no `connectTimeout` or `readTimeout` configured. When OpenZaak is unreachable, stale TCP connections accumulate in the pool and each liveness health check blocks until the OS-level TCP timeout fires. Using `/health/ready` as the liveness target causes Kubernetes to restart the pod before the connection pool reaches an unrecoverable state.

This is a workaround. The liveness probe should be reverted to `/health/live` with `failureThreshold: 3` once proper HTTP timeouts are configured in ZAC's `ZGW-API-Client`.

**No action required** — the override is set in `values.yaml` and takes effect automatically on upgrade.

---


### ZAC office-converter — `kontextwork-converter` image explicitly pinned, port configurable

The `office_converter` image is explicitly pinned to `ghcr.io/eugenmayer/kontextwork-converter:1.8.2` and `containerPort` is set to `8080` (kontextwork-converter's default). ZAC 1.0.224 makes `office_converter.containerPort` configurable; the chart default remains `3000` (Gotenberg) so the override in `values.yaml` is required.

For **ACR-based environments**, add the repository override:

```yaml
zac:
  office_converter:
    image:
      repository: <acr>/kontextwork-converter
```

No tag override needed — the tag is set by the chart default (`1.8.2`).

---

### `redis-ha-label-master` — one-shot Job replaced by CronJob

The `redis-ha-label-master` one-shot Job has been replaced with a CronJob that runs every 5 minutes. This closes a gap where label drift after the Job's 10-minute TTL left the `redis-ha-master` Service with no endpoints, causing all Redis-dependent apps to hang on first connection.

**Root cause:** `redis-operator` 0.24.0 has a known bug ([PR #1720](https://github.com/OT-CONTAINER-KIT/redis-operator/pull/1720), not yet released) where simultaneous pod restarts cause the operator to pass an empty pod name to `getRedisServerIP()`, looping with `"resource name may not be empty"` and never applying `redis-role` labels. The CronJob reconciles labels from `RedisReplication.status.masterNode` every 5 minutes as a mitigation until a fixed operator release is available. See [docs/redis-ha.md](redis-ha.md) for full details.

**Values key renamed:** `redis-operator.redis-ha.labelMasterJob` → `redis-operator.redis-ha.labelMasterCronJob`

If any environment values file overrides `labelMasterJob` fields (e.g. `image.repository` for ACR), rename the key:

```yaml
# Before
redis-operator:
  redis-ha:
    labelMasterJob:
      image:
        repository: <acr>/alpine/k8s

# After
redis-operator:
  redis-ha:
    labelMasterCronJob:
      image:
        repository: <acr>/alpine/k8s
```

For **test environments** that are suspended outside business hours, override the schedule so the CronJob does not run when the cluster is idle:

```yaml
redis-operator:
  redis-ha:
    labelMasterCronJob:
      schedule: "*/5 7-18 * * 1-5"  # Mon–Fri 07:00–18:55 only
```

The `docker.io/alpine/k8s` image tag has also been updated from `1.33.2` to `1.33.10`.

---

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.6.3   | 4.6.4   |
|-----------|---------|---------|
| ZAC       | 1.0.208 | 1.0.224 |
| alpine/k8s (labelMasterCronJob) | 1.33.2 | 1.33.10 |
| nginx-unprivileged (api-proxy + Maykin/ZAC sidecars) | 1.29.5 | 1.29.8 |

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.4.yaml](images/images-4.6.4.yaml).
