# Upgrade guide: PodiumD 4.6.2 → 4.6.3

## Required manual steps before upgrading

### Delete completed seeding and realm-import Jobs

The security hardening in this release changes the pod template of all custom Jobs (seeding jobs,
Keycloak import/ensure jobs, redis-ha label job) to add `readOnlyRootFilesystem: true`,
explicit `serviceAccountName`, and `runAsUser`. Kubernetes treats completed `Job` resources as
immutable — `helm upgrade` will fail with `spec.template: Invalid value` if these Jobs still exist.

Delete them before running `helm upgrade`:

```bash
kubectl delete jobs -n podiumd --context <cluster> \
  create-required-catalogi-job \
  create-required-objecttypen-job \
  ensure-keycloak-operator-sa \
  ensure-podiumd-admin-user \
  import-master-realm-job \
  import-podiumd-realm-job \
  objecten-config \
  objecttypen-config \
  openformulieren-config \
  openklant-config \
  opennotificaties-config \
  openzaak-config \
  podiumd-realm-import \
  redis-ha-label-master
```

> These are one-time idempotent seeding Jobs. Deleting them is safe — Helm will recreate them
> during the upgrade and they will re-run. The ZAC CronJobs (`zac-sig-del`, `zac-signaleren`)
> are managed by the ZAC subchart, are not affected by this change, and must **not** be deleted.

---

### Delete the ClamAV StatefulSet before enabling the exporter sidecar

If enabling `clamav.metrics.enabled: true` for the first time (e.g. via
`values-enable-observability.yaml`), delete the existing ClamAV StatefulSet before upgrading:

```bash
kubectl delete statefulset clamav -n podiumd --context <cluster>
```

Helm will recreate it with the exporter sidecar. The PVC is retained.

---

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
replaced with `docker.io/alpine/k8s:1.33.2` — an alpine-based image bundling the official
Kubernetes 1.33 kubectl binary with a full shell environment.

For **ACR-based environments**, update the repository override:

```yaml
redis-operator:
  redis-ha:
    labelMasterJob:
      image:
        repository: <acr>/k8s
```

No tag override is needed — the tag is set by the chart default (`1.33.2`).

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
# api-proxy (changed in 4.6.3 — was "nginx")
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

---

### ZAC: `pabc` renamed to `pabcApi` in values

The `zac.pabc` key has been renamed to `zac.pabcApi` to match the ZAC chart
schema. If your environment values file sets `zac.pabc`, rename the key:

```yaml
# Before
zac:
  pabc:
    apiUrl: "..."
    apiKey: REP_ZAC_PABC_API_KEY_REP

# After
zac:
  pabcApi:
    apiUrl: "..."
    apiKey: REP_ZAC_PABC_API_KEY_REP
```

---

### ZooKeeper and Solr PVCs — `reclaimPolicy: Retain`

ZooKeeper and Solr PVCs now use `reclaimPolicy: Retain` (previously `Delete`). This prevents
data loss during node rotation and operator scale-down events — a `Delete` policy caused a
ZooKeeper quorum deadlock when a node was replaced and the PVC was destroyed before the pod
restarted (`accp-dimp`).

**No action required** for existing deployments — the reclaimPolicy on existing PVCs is not
changed by `helm upgrade`. The change only takes effect for newly provisioned PVCs (fresh installs
or after manual PVC recreation).

---

### Keycloak Operator and ECK Operator — ServiceMonitor / PodMonitor RBAC

Two new RBAC templates are added:

- `keycloak-operator-servicemonitor-rbac.yaml` — grants the keycloak-operator SA permission to
  discover and manage `ServiceMonitor` resources. The ClusterRole (read) is always rendered when
  `keycloak-operator.enabled: true`; without it the operator receives HTTP 403 on the
  `monitoring.coreos.com` API group and aborts reconciliation entirely.
- `eck-operator-podmonitor-rbac.yaml` — grants the `elastic-operator` SA permission to create
  and manage `PodMonitor` resources for ECK-managed Elasticsearch/Kibana instances. Rendered when
  `kisselastic.enabled: true` and `kisselastic.eck-operator.podMonitor.enabled: true`.

**No action required.** Both templates are automatically included and activate based on existing
enabled/disabled flags.

---

### Redis HA — `redis_exporter` sidecar and PodMonitor

A new `redis_exporter` sidecar (port 9121) and a corresponding `PodMonitor` can now be enabled
per environment. Both are **disabled by default**.

To enable (typically via `values-enable-observability.yaml`):

```yaml
redis-operator:
  redis-ha:
    redisExporter:
      enabled: true
      podMonitor:
        enabled: true
        interval: 30s
        scrapeTimeout: 10s
```

For **ACR-based environments**, add the repository override for the exporter image:

```yaml
redis-operator:
  redis-ha:
    redisExporter:
      image:
        repository: <acr>/redis-exporter
```

No tag override needed — the tag is set by the chart default.

---

### ClamAV — `clamav_exporter` metrics sidecar and ServiceMonitor

The ClamAV chart (v3.7.1) now ships a built-in `clamav_exporter` sidecar and `ServiceMonitor`.
Both are **disabled by default**. Enable via `values-enable-observability.yaml`:

```yaml
clamav:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      interval: 30s
      scrapeTimeout: 10s
```

For **ACR-based environments**, add the repository override:

```yaml
clamav:
  metrics:
    image:
      repository: <acr>/clamav_exporter
```

No tag override needed — the tag is set by the chart default (`v2.1.2`).

> **Note:** Adding the sidecar changes the ClamAV pod spec. See [Required manual steps](#delete-the-clamav-statefulset-before-enabling-the-exporter-sidecar) at the top of this guide.

---

### Security hardening — container security contexts

All custom pod templates (api-proxy, adapter, Keycloak jobs, seeding jobs, redis-ha label job)
now have `readOnlyRootFilesystem: true` and explicit `runAsNonRoot: true` / `runAsUser` settings.
Writable paths (`/tmp`, `/var/cache/nginx`) are provided via `emptyDir` volumes where needed.

Keycloak job pods now explicitly reference the podiumd `ServiceAccount` name. The `ServiceAccount`
has `automountServiceAccountToken: false` set globally; the redis-ha label job opts back in
(`automountServiceAccountToken: true` on the pod spec) because it needs API server access.

**No action required.** These are template-only changes with no values impact.

---

### Security hardening — api-proxy TLS verification enabled

`apiproxy.locations.commonSettings.sslVerify` now defaults to `"on"` (previously `"off"`). The
CA certificate infrastructure was already wired (`nginxCertsSecret`) but was being silently ignored.

**Action required** if `nginxCertsSecret` is set: ensure `ca.crt` in the referenced secret contains
the CA chain that signed the upstream government API (BAG/BRP/KVK) server certificate. If the CA
is not available, explicitly override the default in your environment values:

```yaml
apiproxy:
  locations:
    commonSettings:
      sslVerify: "off"   # temporary — remove once CA cert is available
```

---

### Keycloak security — TOTP always required in master realm

`adminOtpEnabled` has been removed as a configurable flag. TOTP (OTP) is now unconditionally
required for all admin accounts in the master realm. The Keycloak admin UI will prompt for TOTP
setup on next login if it was not previously configured.

**No action required** for environments already using TOTP. For environments where TOTP was
disabled (`adminOtpEnabled: false`), admin accounts will be prompted to set up an authenticator
app on next login.

---

### Keycloak security — SSO session lifetime limits

Both realm configs now enforce SSO session limits:

| Setting | Value |
|---|---|
| `ssoSessionMaxLifespan` | 36000 s (10 h) |
| `ssoSessionIdleTimeout` | 1800 s (30 min) |

These limits apply to browser SSO sessions (not to individual access tokens, which are controlled
by `accessTokenLifespan`). Sessions that exceed these limits will require re-authentication.

**No action required.**

---

### ZGW Office Add-in - App Environment value

For production (default):
```yaml
zgw-office-addin:
  common:
    appEnv: "production"
```

For acceptance: 
```yaml
zgw-office-addin:
  common:
    appEnv: "acc"
```

For test: 
```yaml
zgw-office-addin:
  common:
    appEnv: "test"
```

There's a script that can be used to update the `appEnv` value in `podiumd.yml` files:
```bash
./set-zgw-office-addin-app-env
```

---

For the full list of new and changed images in this release see
[docs/images/images-4.6.3.yaml](images/images-4.6.3.yaml).

---

## Known issues

### OpenZaak startup failure: duplicate key on `admin_index_appgroup.slug`

After upgrading, `openzaak` pods may fail to become ready with:

```
django.db.utils.IntegrityError: duplicate key value violates unique constraint "admin_index_appgroup_slug_key"
```

This is caused by a psycopg3 transaction semantics issue in the `post_migrate` signal handler that resets the admin index fixture. See [openzaak-post-migrate-appgroup-duplicate-key.md](openzaak-post-migrate-appgroup-duplicate-key.md) for the full analysis, workaround, and proper fix.
