# Upgrade guide: PodiumD 4.6.1 → 4.6.2

## Changes

### Required values — weak defaults removed

The following fields previously had insecure placeholder defaults (`"changeme"`, `"changemenow"`,
`"monitoring_secret"`, `"abc"`). These defaults have been blanked to force explicit configuration.
**Deployments will fail at template render time if these are not set.**

| Field | Previous default | Action required |
|-------|-----------------|-----------------|
| `keycloak.auth.adminPassword` | `"changemenow"` | Set to a strong password |
| `keycloak.config.clients.monitoring.secret` | `"monitoring_secret"` | Set to a random secret |
| `openarchiefbeheer.configuration.oidcSecret` | `"abc"` | Set to the OIDC client secret |
| `keycloak-operator.jobs.ensureOperatorSa.clientSecret` | `"changeme"` | Set to the Keycloak operator SA client secret |

These are typically sourced from the environment's Key Vault and injected at deploy time via
`--set-string`. They should **not** be committed in plaintext to values files — use the
`REP_xxx_REP` placeholder pattern so the pipeline substitutes them at deploy time.

---

### PABC updated to 1.1.0

The PABC sub-chart has been updated from 1.0.0 to 1.1.0.

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

### `redis-ha-label-master` kubectl image replaced

The `lachlanevenson/k8s-kubectl` image (unofficial Docker Hub maintainer, K8s 1.25 EOL) has been
replaced with `registry.k8s.io/kubectl:v1.33.0` — the official Kubernetes project image.

For **ACR-based environments**, update the repository override:

```yaml
redis-operator:
  redis-ha:
    labelMasterJob:
      image:
        repository: <acr>/kubectl
```

No tag override is needed — the tag is set by the chart default (`v1.33.0`).

---

### `redis-ha-label-master` job — hardcoded nodeSelector removed

The `redis-ha-label-master` Job previously had `kubernetes.azure.com/mode: user` hardcoded in
its template, causing it to be unschedulable on clusters with only system-mode nodes (e.g.
single-nodepool dev/test clusters).

The nodeSelector is now optional and must be set explicitly in environments that require it
(e.g. AKS-blue with dedicated user nodepools):

```yaml
redis-operator:
  redis-ha:
    labelMasterJob:
      nodeSelector:
        kubernetes.azure.com/mode: user
```

On clusters without a dedicated user nodepool, omit this key entirely.

---

### `api-proxy` and other components — `nginxinc/nginx-unprivileged` image

The api-proxy Deployment uses `runAsNonRoot: true`. The previous `nginx` image runs as root and
was incompatible with this constraint. The image has been switched to
`nginxinc/nginx-unprivileged:1.29.5` (uid 101).

The Maykin subcharts (openzaak, openklant, openformulieren, openinwoner, openarchiefbeheer) and
ZAC have always used `nginxinc/nginx-unprivileged` as their nginx sidecar — this is unchanged.

For **ACR-based environments**, the repository path must use `nginx-unprivileged` (not `nginx`)
for all of these components. Add or verify the following overrides:

```yaml
# api-proxy (changed in 4.6.2 — was "nginx")
apiproxy:
  image:
    repository: <acr>/nginx-unprivileged

# Maykin subcharts — verify these are set correctly in your environment values
openzaak:
  nginx:
    image:
      repository: <acr>/nginx-unprivileged

openklant:
  nginx:
    image:
      repository: <acr>/nginx-unprivileged

openformulieren:
  nginx:
    image:
      repository: <acr>/nginx-unprivileged

openinwoner:
  nginx:
    image:
      repository: <acr>/nginx-unprivileged

openarchiefbeheer:
  nginx:
    image:
      repository: <acr>/nginx-unprivileged

zac:
  nginx:
    image:
      repository: <acr>/nginx-unprivileged
```

No tag overrides are needed — tags are set by the chart defaults (`1.29.5`).

---

For the full list of new and changed images in this release see
[docs/images/images-4.6.2.yaml](images/images-4.6.2.yaml).
