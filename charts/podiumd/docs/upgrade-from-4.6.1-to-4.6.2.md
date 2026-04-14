# Upgrade guide: PodiumD 4.6.1 → 4.6.2

## New features / additions

### PABC updated to 1.1.0

> **Note:** These PABC changes were already included in the latest 4.5 patch release (podiumd 4.5.16). Environments that have already upgraded to 4.5.16 before migrating to 4.6.x have these images in their ACR and no new ACR imports are required.

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

For **ACR-based environments** that do not yet have this image in the ACR, add the override above
so the image is pulled from the environment-specific ACR.

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

| Component | 4.6.1 | 4.6.2 |
|---|---|---|
| pabc | 1.0.0 | 1.1.0 |

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.2.yaml](images/images-4.6.2.yaml).
