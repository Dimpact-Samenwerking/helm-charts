# Upgrade guide: PodiumD 4.6.0 → 4.6.2

## New features / additions

### Redis HA master label job (always active)

4.6.1 adds a `redis-ha-label-master` Job that runs on every deployment and fixes a known
OT Redis Operator v0.24.0 bug: after a rolling restart of the Redis StatefulSet, pods lose
their `redis-role=master/slave` labels, causing the `redis-ha-master` service to have no
endpoints and all Celery workers to crash.

The job is idempotent — it exits immediately if labels are already present.

It uses the `lachlanevenson/k8s-kubectl` image (already in the chart via the
zookeeper-operator hooks). For **ACR-based environments**, override the repository:

```yaml
redis-operator:
  redis-ha:
    labelMasterJob:
      image:
        repository: <acr>/k8s-kubectl
```

No tag override is needed — the tag is set by the chart default (`v1.25.4`).

---

### Observability: new images via `values-enable-observability.yaml`

4.6.1 introduces `values-enable-observability.yaml`, an optional overlay that enables
OpenTelemetry metrics and Prometheus scraping across all supported components. When this
overlay is applied, the following **new images** are pulled:

| Image | Registry | Purpose |
|---|---|---|
| `clamav_exporter` | `docker.io/sergeymakinen/clamav_exporter:v2.1.2` | ClamAV metrics sidecar (ServiceMonitor on port 9906) |

For **ACR-based environments**, override the image repository in your environment
values file so the image is pulled from the environment-specific ACR:

```yaml
clamav:
  metrics:
    image:
      repository: <acr>/clamav_exporter
```

No tag override is needed — the tag is set by the chart default (`v2.1.2`).

> This image is only used when `values-enable-observability.yaml` is applied. If you do
> not use that overlay, no action is needed.

---

### New components: referentielijsten and openbeheer

Two new optional components are added as subchart dependencies:

| Component | Chart | Condition |
|---|---|---|
| `referentielijsten` | `maykinmedia/referentielijsten:0.1.1` | `referentielijsten.enabled` |
| `openbeheer` | `maykinmedia/openbeheer:0.1.2` | `openbeheer.enabled` |

Both are **disabled by default** (`enabled: false`). No action needed if you do not use them.

For ACR-based environments that enable these components, add image repository overrides
pointing to the ACR (no tags needed):

```yaml
referentielijsten:
  enabled: true
  image:
    repository: <acr>/referentielijsten-api

openbeheer:
  enabled: true
  image:
    repository: <acr>/open-beheer
```

---

### New component: OMC (NotifyNL)

`notifynl-omc-nodep` (aliased `omc`) is added as a new optional subchart dependency
(`worth-nl/notifynl-omc-nodep:0.14.0`). Disabled by default.

---

### PABC updated to 1.1.0

The PABC application and migration images have been updated from `1.0.0` to `1.1.0`.

#### ACR image overrides

For **ACR-based environments**, update the repository overrides:

```yaml
pabc:
  image:
    repository: <acr>/pabc
  migrations:
    image:
      repository: <acr>/pabc-migrations
  initContainers:
    waitFor:
      image:
        repository: <acr>/k8s-wait-for
```

No tag overrides are needed — tags are set by the chart defaults (`1.1.0` and `v2.0`).

#### New initContainer: k8s-wait-for

PABC 1.1.0 introduces an init container that waits for the migration job to complete before
the main application pod starts. The image (`ghcr.io/groundnuty/k8s-wait-for:v2.0`) is a
**new image** in this release.

#### NodeSelector for AKS environments

For environments that require a node selector (e.g. AKS-blue with
`kubernetes.azure.com/mode: user`), set the nodeSelector on both the deployment and the
migration job:

```yaml
pabc:
  nodeSelector:
    kubernetes.azure.com/mode: user
  migrations:
    nodeSelector:
      kubernetes.azure.com/mode: user
```

---

### Legacy Bitnami Keycloak explicitly disabled

`keycloak.enabled` is now explicitly set to `false` in the chart defaults. This has no
functional impact — the legacy Bitnami Keycloak chart was already inactive in environments
using the Keycloak Operator (`keycloak-operator.enabled: true`). No action needed.

---

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.6.0 | 4.6.2 |
|---|---|---|
| clamav | 3.2.0 | 3.7.1 |
| openzaak | 1.13.0 | 1.13.1 |
| opennotificaties | 1.13.0 | 1.13.1 |
| objecten | 2.11.0 | 2.12.0 |
| objecttypen | 1.6.0 | 1.6.1 |
| openklant | 1.10.0 | 1.11.0 |
| openformulieren (openforms) | 1.11.6 | 1.12.0 |
| openinwoner | 2.1.0 | 2.1.3 |
| zac | 1.0.165 | 1.0.208 |
| zgw-office-addin | 0.0.65 | 0.0.73 |
| ita | 2.0.1 | 3.0.0 |
| kiss | 2.1.0 | 2.2.2 |
| pabc | 1.0.0 | 1.1.0 |

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.2.yaml](images/images-4.6.2.yaml).
