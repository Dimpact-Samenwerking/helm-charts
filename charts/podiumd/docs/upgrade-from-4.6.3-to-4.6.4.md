# Upgrade guide: PodiumD 4.6.3 → 4.6.4

## Required manual steps before upgrading

None.

---

## Changes

### ZAC helm chart updated to 1.0.223

The ZAC subchart has been updated from 1.0.208 to 1.0.223 (ZAC 4.7).

---

### ZAC liveness probe changed to `/health/ready` (fixes known issue)

This release resolves the known issue from 4.6.3 where ZAC did not recover automatically after extended OpenZaak/catalogus unavailability.

The ZAC liveness probe path has been changed from `/health/live` to `/health/ready` with `failureThreshold: 16` (16 × 30 s = 480 s). Kubernetes will now automatically restart ZAC after ~8 minutes of catalogus unavailability without manual intervention.

**Root cause:** The ZGW-API-Client MicroProfile REST client has no `connectTimeout` or `readTimeout` configured. When OpenZaak is unreachable, stale TCP connections accumulate in the pool and each liveness health check blocks until the OS-level TCP timeout fires. Using `/health/ready` as the liveness target causes Kubernetes to restart the pod before the connection pool reaches an unrecoverable state.

This is a workaround. The liveness probe should be reverted to `/health/live` with `failureThreshold: 3` once proper HTTP timeouts are configured in ZAC's `ZGW-API-Client`.

**No action required** — the override is set in `values.yaml` and takes effect automatically on upgrade.

---


### `redis-ha-label-master` kubectl image updated to 1.33.10

The `docker.io/alpine/k8s` image used by the `redis-ha-label-master` Job has been updated from `1.33.2` to `1.33.10`.

For **ACR-based environments**, no additional action is needed — the repository override is already set. No tag override is needed; the tag is set by the chart default (`1.33.10`).

---

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.6.3   | 4.6.4   |
|-----------|---------|---------|
| ZAC       | 1.0.208 | 1.0.222 |
| alpine/k8s (labelMasterJob) | 1.33.2 | 1.33.10 |
| nginx-unprivileged (api-proxy + Maykin/ZAC sidecars) | 1.29.5 | 1.29.8 |

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.4.yaml](images/images-4.6.4.yaml).
