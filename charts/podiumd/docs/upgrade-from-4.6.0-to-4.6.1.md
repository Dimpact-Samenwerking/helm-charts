# Upgrade guide: PodiumD 4.6.0 → 4.6.1

## New features / additions

### Observability: new images via `values-enable-observability.yaml`

4.6.1 introduces `values-enable-observability.yaml`, an optional overlay that enables
OpenTelemetry metrics and Prometheus scraping across all supported components. When this
overlay is applied, the following **new images** are pulled:

| Image | Registry | Purpose |
|---|---|---|
| `clamav_exporter` | `docker.io/sergeymakinen/clamav_exporter:v2.1.2` | ClamAV metrics sidecar (ServiceMonitor on port 9906) |

For **ACR-based environments**, override the registry and repository in your environment
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

For the full list of new and changed images in this release see
[docs/images/images-4.6.1.yaml](images/images-4.6.1.yaml).

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
    repository: <acr>/referentielijsten

openbeheer:
  enabled: true
  image:
    repository: <acr>/openbeheer
```

---

### New component: OMC (NotifyNL)

`notifynl-omc-nodep` (aliased `omc`) is added as a new optional subchart dependency
(`worth-nl/notifynl-omc-nodep:0.14.0`). Disabled by default.

---

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.6.0 | 4.6.1 |
|---|---|---|
| clamav | 3.2.0 | 3.7.1 |
| openzaak | 1.13.0 | 1.13.1 |
| opennotificaties | 1.13.0 | 1.13.1 |
| objecten | 2.11.0 | 2.12.0 |
| objecttypen | 1.6.0 | 1.6.1 |
| openklant | 1.10.0 | 1.11.0 |
| openformulieren (openforms) | 1.11.6 | 1.12.0 |
| openinwoner | 2.1.0 | 2.1.3 |
| zac | 1.0.165 | 1.0.204 |
| zgw-office-addin | 0.0.65 | 0.0.73 |
| ita | 2.0.1 | 3.0.0 |
| kiss | 2.1.0 | 2.2.2 |
