# Upgrade guide: PodiumD 4.5.15 → 4.5.16

## Changes

### PABC updated to 1.1.0

The PABC sub-chart has been updated from 1.0.0 to 1.1.0. The application and migration images
have been updated to version `1.1.0`.

#### ACR image overrides

For **ACR-based environments**, update the repository overrides:

```yaml
pabc:
  image:
    repository: <acr>/pabc-api
  migrations:
    image:
      repository: <acr>/pabc-migrations
  initContainers:
    waitFor:
      image:
        repository: <acr>/k8s-wait-for
```

No tag overrides are needed — tags are set by the chart defaults (`1.1.0` and `v2.0`).

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

### Keycloak updated to 26.5.7

The Keycloak and Keycloak Operator images have been updated from `26.5.6` to `26.5.7`.

For **ACR-based environments**, update the repository overrides:

```yaml
keycloak:
  image:
    repository: <acr>/keycloak

keycloak-operator:
  operator:
    image:
      repository: <acr>/keycloak-operator
```

No tag overrides are needed — tags are set by the chart defaults (`26.5.7`).

---

For the full list of new and changed images in this release, see
[docs/images/images-4.5.16.yaml](images/images-4.5.16.yaml).
