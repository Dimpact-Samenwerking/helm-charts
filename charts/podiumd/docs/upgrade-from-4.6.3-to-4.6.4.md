# Upgrade guide: PodiumD 4.6.3 → 4.6.4

## Required manual steps before upgrading

None.

---

## Changes

### ZAC helm chart updated to 1.0.222

The ZAC subchart has been updated from 1.0.208 to 1.0.222 (ZAC 4.7).

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
