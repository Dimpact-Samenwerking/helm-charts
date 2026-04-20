# Upgrade guide: PodiumD 4.6.2 → 4.6.4

## Required manual steps before upgrading

### Migrate Redis HA PVCs to `managed-csi-premiumv2`

The Redis HA storage class has been changed from `managed-csi` to `managed-csi-premiumv2` for
better I/O performance. The storage class on existing PVCs is immutable — the old PVCs must be
deleted so the operator can recreate them with the new storage class.

**Redis only stores cache data** (session state, Celery task results). All data will be
automatically rebuilt after the pods restart. No data export is needed.

#### Option A: Full migration (brief Redis outage)

```bash
# 1. Delete the Redis HA StatefulSet so the operator recreates it with the new storage class.
#    The operator manages the StatefulSet — it will recreate it after deletion.
kubectl delete statefulset redis-ha -n podiumd --context <cluster>

# 2. Delete the existing PVCs (cache data — safe to delete).
kubectl delete pvc \
  redis-ha-redis-ha-0 \
  redis-ha-redis-ha-1 \
  redis-ha-redis-ha-2 \
  -n podiumd --context <cluster>

# 3. Run helm upgrade as normal. The operator will create new PVCs on managed-csi-premiumv2.
```

> The applications (openzaak, openklant, etc.) may briefly return errors while Redis is
> unavailable during the migration. This resolves automatically once Redis recovers.

#### Option B: Rolling migration (no full Redis outage)

This migrates one replica at a time while Redis remains available as a replication group.
Since all data is cache, each replica rebuilds from the master after restart.

Run `helm upgrade` first — this updates the `RedisReplication` CRD. Then verify the StatefulSet
has the new `volumeClaimTemplate` (the operator recreates it automatically):

```bash
kubectl get statefulset redis-ha -n podiumd --context <cluster> \
  -o jsonpath='{.spec.volumeClaimTemplates[0].spec.storageClassName}'
# Expected: managed-csi-premiumv2
```

If it still shows `managed-csi`, the operator hasn't reconciled yet — wait a moment and recheck.

Then migrate each replica in turn (waiting for `Ready` before proceeding to the next):

```bash
for i in 0 1 2; do
  kubectl delete pvc redis-ha-redis-ha-$i -n podiumd --context <cluster>
  kubectl delete pod redis-ha-$i -n podiumd --context <cluster>
  kubectl wait pod/redis-ha-$i -n podiumd --context <cluster> --for=condition=Ready --timeout=120s
done
```

> Wait for each replica to reach `Ready` before proceeding to the next. The Redis master
> is always kept available — only one replica is down at a time.

---

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

### `redis-ha-label-master` — one-shot Job replaced by CronJob; image and nodeSelector updated

The `redis-ha-label-master` one-shot Job has been replaced with a CronJob that runs every
2 minutes. This closes a gap where label drift after the Job's 10-minute TTL left the
`redis-ha-master` Service with no endpoints, causing all Redis-dependent apps to hang on
first connection. See [docs/redis-ha.md](redis-ha.md) for full details.

The image has also been updated from the unofficial `lachlanevenson/k8s-kubectl` (K8s 1.25 EOL)
to `docker.io/alpine/k8s:1.33.10`.

The hardcoded `kubernetes.azure.com/mode: user` nodeSelector has been removed from the template.
The nodeSelector is now optional and must be set explicitly in environments that require it
(e.g. AKS-blue with dedicated user nodepools):

```yaml
redis-operator:
  redis-ha:
    labelMasterCronJob:
      nodeSelector:
        kubernetes.azure.com/mode: user
```

On clusters without a dedicated user nodepool, omit this key entirely.

**Values key renamed:** `redis-operator.redis-ha.labelMasterJob` → `redis-operator.redis-ha.labelMasterCronJob`

If any environment values file overrides `labelMasterJob` fields (e.g. `image.repository` for ACR), rename the key:

```yaml
# Before
redis-operator:
  redis-ha:
    labelMasterJob:
      image:
        repository: <acr>/k8s-kubectl

# After
redis-operator:
  redis-ha:
    labelMasterCronJob:
      image:
        repository: <acr>/k8s
```

No tag override is needed — the tag is set by the chart default (`1.33.10`).

For **test environments** that are suspended outside business hours, override the schedule so
the CronJob does not run when the cluster is idle:

```yaml
redis-operator:
  redis-ha:
    labelMasterCronJob:
      schedule: "* 7-18 * * 1-5"  # every minute, Mon–Fri 07:00–18:59 only
```

---

### `api-proxy` and other components — `nginxinc/nginx-unprivileged` image

The api-proxy Deployment uses `runAsNonRoot: true`. The previous `nginx` image runs as root and
was incompatible with this constraint. The image has been switched to
`nginxinc/nginx-unprivileged` (uid 101).

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

No tag overrides are needed — tags are set by the chart defaults (`1.29.8`).

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
```
```yaml
# After
zac:
  pabcApi:
    apiUrl: "..."
    apiKey: REP_ZAC_PABC_API_KEY_REP
```

---

### ZAC helm chart updated to 1.0.224

The ZAC subchart has been updated from 1.0.208 to 1.0.224 (ZAC 4.7).

---

### ZAC liveness probe changed to `/health/ready`

The ZAC liveness probe path has been changed from `/health/live` to `/health/ready` with
`failureThreshold: 16` (16 × 30 s = 480 s). Kubernetes will now automatically restart ZAC
after ~8 minutes of OpenZaak/catalogus unavailability without manual intervention.

**Root cause:** The ZGW-API-Client MicroProfile REST client has no `connectTimeout` or
`readTimeout` configured. When OpenZaak is unreachable, stale TCP connections accumulate in
the pool and each liveness health check blocks until the OS-level TCP timeout fires. Using
`/health/ready` as the liveness target causes Kubernetes to restart the pod before the
connection pool reaches an unrecoverable state.

This is a workaround. The liveness probe should be reverted to `/health/live` with
`failureThreshold: 3` once proper HTTP timeouts are configured in ZAC's `ZGW-API-Client`.

**No action required** — the override is set in `values.yaml` and takes effect automatically on upgrade.

---

### ZAC office-converter — `kontextwork-converter` image explicitly pinned, port configurable

The `office_converter` image is explicitly pinned to `ghcr.io/eugenmayer/kontextwork-converter:1.8.2`
and `containerPort` is set to `8080` (kontextwork-converter's default). ZAC 1.0.224 makes
`office_converter.containerPort` configurable; the chart default remains `3000` (Gotenberg) so
the override in `values.yaml` is required.

For **ACR-based environments**, add the repository override:

```yaml
zac:
  office_converter:
    image:
      repository: <acr>/kontextwork-converter
```

No additional tag override needed — the tag is already pinned to `1.8.2` in PodiumD's `values.yaml`.

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

All custom pod templates (api-proxy, adapter, Keycloak jobs, seeding jobs, redis-ha label CronJob)
now have `readOnlyRootFilesystem: true` and explicit `runAsNonRoot: true` / `runAsUser` settings.
Writable paths (`/tmp`, `/var/cache/nginx`) are provided via `emptyDir` volumes where needed.

Keycloak job pods now explicitly reference the podiumd `ServiceAccount` name. The `ServiceAccount`
has `automountServiceAccountToken: false` set globally; the redis-ha label CronJob opts back in
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

### ZGW Office Add-in — App Environment value

A new `common.appEnv` value controls the application environment label shown in the add-in UI.

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

## Known issues

### OpenZaak startup failure: duplicate key on `admin_index_appgroup.slug`

After upgrading, `openzaak` pods may fail to become ready with:

```
django.db.utils.IntegrityError: duplicate key value violates unique constraint "admin_index_appgroup_slug_key"
```

This is caused by a psycopg3 transaction semantics issue in the `post_migrate` signal handler that resets the admin index fixture. See [openzaak-post-migrate-appgroup-duplicate-key.md](openzaak-post-migrate-appgroup-duplicate-key.md) for the full analysis, workaround, and proper fix.

---

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.6.2 | 4.6.4 |
|---|---|---|
| ZAC | 1.0.208 | 1.0.224 |
| ZGW Office Add-in | 0.9.133 | 0.9.251 |
| alpine/k8s (labelMasterCronJob) | 1.33.2 | 1.33.10 |
| nginx-unprivileged (api-proxy + Maykin/ZAC sidecars) | 1.29.5 | 1.29.8 |

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.4.yaml](images/images-4.6.4.yaml).
