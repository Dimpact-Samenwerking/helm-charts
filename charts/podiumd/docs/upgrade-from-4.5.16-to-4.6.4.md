# Upgrade guide: PodiumD 4.5.16 → 4.6.4

## New features / additions

### openinwoner: Elasticsearch graceful shutdown (IN-1509)

To prevent data corruption during AKS node upgrades and restarts, the chart now sets a graceful shutdown configuration on the openinwoner Elasticsearch nodeSet by default:

- `terminationGracePeriodSeconds: 60` — gives the pod 60 seconds to flush and shut down cleanly.
- `PRE_STOP_ADDITIONAL_WAIT_SECONDS: "15"` — adds a pre-stop delay so the load balancer can drain connections before the process exits.

**No action needed** for environments that do not override `openinwoner.eck-elasticsearch.nodeSets` — the chart default applies automatically.

For environments that **do** define their own `nodeSets` (e.g. to set `nodeSelector`), add these settings to the existing nodeSet:

```yaml
openinwoner:
  eck-elasticsearch:
    nodeSets:
    - name: default
      # ... existing config ...
      podTemplate:
        spec:
          terminationGracePeriodSeconds: 60
          containers:
          - name: elasticsearch
            env:
            - name: PRE_STOP_ADDITIONAL_WAIT_SECONDS
              value: "15"
```

---

### openinwoner: Elasticsearch storage class (per-environment)

The `volumeClaimTemplates` for the openinwoner Elasticsearch nodeSet must be configured **per environment** (not in chart defaults), because the PVC spec is immutable and varies per cluster. Add the following to each environment's values file under the existing `openinwoner.eck-elasticsearch.nodeSets[0]` block:

```yaml
openinwoner:
  eck-elasticsearch:
    nodeSets:
    - name: default
      # ... existing config ...
      volumeClaimTemplates:
      - metadata:
          name: elasticsearch-data
        spec:
          accessModes:
          - ReadWriteOnce
          storageClassName: managed-csi
          resources:
            requests:
              storage: 8Gi
```

> **Note:** Changing `volumeClaimTemplates` on an existing StatefulSet is not allowed by Kubernetes. If the PVC already exists with a different storageClass, the StatefulSet must be deleted (ECK will recreate it) and the old PVC deleted manually.

---

### keycloak-operator: new jobs

Four new jobs are introduced under `keycloak-operator.jobs`:

| Job | Purpose |
|-----|---------|
| `ensurePodiumdAdminUser` | Provisions the PodiumD admin user in the Keycloak DB via PBKDF2 hash + psql |
| `ensureOperatorSa` | Provisions the `keycloak-operator` service-account client in Keycloak via curl |
| `importPodiumdRealm` | Imports the podiumd realm configuration |
| `importMasterRealm` | Imports the master realm configuration |

For ACR-based environments, override the job images (no tags needed):

```yaml
keycloak-operator:
  jobs:
    ensurePodiumdAdminUser:
      enabled: true
      initImage:
        registry: <acr>
        repository: python
      image:
        registry: <acr>
        repository: postgres
    ensureOperatorSa:
      enabled: true
      image:
        registry: <acr>
        repository: curl
      clientSecret: "REP_KEYCLOAK_OPERATOR_SA_CLIENT_SECRET_REP"
    importPodiumdRealm:
      enabled: true
    importMasterRealm:
      enabled: true
```

**Important:** `ensureOperatorSa.clientSecret` must be set to a known secret value.
Add a `REP_KEYCLOAK_OPERATOR_SA_CLIENT_SECRET_REP` replacement in the pipeline.

---

### keycloak image: new `registry` field

A `registry` field was added to `keycloak.image` and `keycloak.keycloakConfigCli.image`.
For ACR environments that embed the full path in `repository`, leave `registry` unset or set to `""`.

---

### openzaak: notificaties configuration flags enabled by default

Two new configuration flags default to `true` in 4.6.0:

```yaml
openzaak:
  configuration:
    notificatiesAuthorization:
      enabled: true
    notificaties:
      enabled: true
```

If these were previously set to `false` in environment values, update them to `true`.

---

### zac: initContainer enabled by default

`zac.initContainer.enabled` changed default from `false` to `true`.
Remove any explicit `initContainer.enabled: false` override if you want the new default behaviour.

---

### Redis HA master label CronJob

A `redis-ha-label-master` CronJob runs every 2 minutes and fixes a known OT Redis Operator v0.24.0 bug: after a rolling restart of the Redis StatefulSet, pods lose their `redis-role=master/slave` labels, causing the `redis-ha-master` service to have no endpoints and all Celery workers to crash. See [docs/redis-ha.md](redis-ha.md) for full details.

It uses the `alpine/k8s` image. For **ACR-based environments**, override the repository:

```yaml
redis-operator:
  redis-ha:
    labelMasterCronJob:
      image:
        repository: <acr>/k8s
```

No tag override is needed — the tag is set by the chart default (`1.33.10`).

For **test environments** that are suspended outside business hours, override the schedule so the CronJob does not run when the cluster is idle:

```yaml
redis-operator:
  redis-ha:
    labelMasterCronJob:
      schedule: "* 7-18 * * 1-5"  # every minute, Mon–Fri 07:00–18:59 only
```

---

### Observability: new images via `values-enable-observability.yaml`

`values-enable-observability.yaml` is an optional overlay that enables OpenTelemetry metrics and Prometheus scraping across all supported components. When applied, the following **new images** are pulled:

| Image | Registry | Purpose |
|---|---|---|
| `clamav_exporter` | `docker.io/sergeymakinen/clamav_exporter:v2.1.2` | ClamAV metrics sidecar (ServiceMonitor on port 9906) |

For **ACR-based environments**, override the image repository in your environment values file so the image is pulled from the environment-specific ACR:

```yaml
clamav:
  metrics:
    image:
      repository: <acr>/clamav_exporter
```

No tag override is needed — the tag is set by the chart default (`v2.1.2`).

> This image is only used when `values-enable-observability.yaml` is applied. If you do not use that overlay, no action is needed.

---

### New components: referentielijsten and openbeheer

Two new optional components are added as subchart dependencies:

| Component | Chart | Condition |
|---|---|---|
| `referentielijsten` | `maykinmedia/referentielijsten:0.1.1` | `referentielijsten.enabled` |
| `openbeheer` | `maykinmedia/openbeheer:0.1.2` | `openbeheer.enabled` |

Both are **disabled by default** (`enabled: false`). No action needed if you do not use them.

For ACR-based environments that enable these components, add image repository overrides pointing to the ACR (no tags needed):

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

### Legacy Bitnami Keycloak explicitly disabled

`keycloak.enabled` is now explicitly set to `false` in the chart defaults. This has no functional impact — the legacy Bitnami Keycloak chart was already inactive in environments using the Keycloak Operator (`keycloak-operator.enabled: true`). No action needed.

---

## Environment values changes

### Configuration jobs for objecten and opennotificaties

The `objecten` and `opennotificaties` subcharts default to `job.enabled: false` in their own `values.yaml`. The `podiumd` parent chart overrides this to `true` — parent chart values always take precedence over subchart defaults in Helm. **No env-level override is needed** for `job.enabled`; the chart default handles it.

If `job.enabled` was already added to an environment's values file as a workaround, it can be left in place (it is harmless) or removed.

> **Note:** Although the job is enabled by default, the configuration job will still fail if the required OIDC and service configuration (`configuration.data`, `configuration.secrets`) is not provided. Without valid configuration data, the OIDC login will fail with `KeyError: 'groups_settings'` on first login because the `OIDCProvider`/`OIDCClient` database records are never populated.

---

### Enable Redis HA and remove per-service Redis subchart config

The per-service Redis subcharts (openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openinwoner) are replaced by a single shared Redis HA cluster.

1. **Add a `redis-operator:` block** to enable the operator and the shared cluster:

   ```yaml
   redis-operator:
     enabled: true
     nodeSelector:
       kubernetes.azure.com/mode: user
     redisOperator:
       imageName: myacr.azurecr.io/redis-operator   # ACR environments only
     redis-ha:
       enabled: true
       nodeSelector:
         kubernetes.azure.com/mode: user
       image:
         registry: myacr.azurecr.io                 # ACR environments only
         repository: redis
       redisExporter:
         image:
           registry: myacr.azurecr.io               # ACR environments only
           repository: redis-exporter
       initContainerImage:
         registry: myacr.azurecr.io                 # ACR environments only
         repository: busybox
   ```

   For non-ACR environments, omit the `redisOperator`, `image`, `redisExporter.image`, and `initContainerImage` overrides.

2. **Remove the `redis:` subchart block** from each of the migrated services. These blocks (image, master.nodeSelector, master.persistence.storageClass) are no longer used — the subcharts are disabled globally. Example of what to remove:

   ```yaml
   openzaak:
     # remove this block:
     redis:
       image:
         repository: redis
       master:
         pdb:
           create: false
         nodeSelector:
           kubernetes.azure.com/mode: user
         persistence:
           storageClass: managed-csi
   ```

   Remove the `redis:` subchart block from **all services that had it**: openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openinwoner, and openarchiefbeheer.

---

### opennotificaties: RabbitMQ image ACR override

`opennotificaties` includes an embedded RabbitMQ subchart. For ACR environments, override its image registry so the image is pulled from ACR instead of Docker Hub:

```yaml
opennotificaties:
  rabbitmq:
    image:
      registry: myacr.azurecr.io
      repository: rabbitmq
```

For non-ACR environments, the default `docker.io/bitnamilegacy/rabbitmq` is used and no override is needed.

---

### OIDC configuration: migrate to new options format

The `mozilla-django-oidc-db` library used by all Django-based components has moved its per-item OIDC fields into a nested `options` block. Any environment values file that still uses the old flat format must be updated before deploying 4.6.0.

**Affected components:** openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren.
**Not affected:** openinwoner (chart 2.1.3) and openarchiefbeheer (chart 1.5.3) — both still use the old flat schema.

Old format (no longer recognised):

```yaml
- identifier: admin-oidc
  claim_mapping:
    email: [email]
    first_name: [given_name]
    last_name: [family_name]
  username_claim: [preferred_username]
  groups_claim: [groups]
  sync_groups: true
  sync_groups_glob_pattern: "*"
  make_users_staff: true
  superuser_group_names: [administrators]
  endpoint_config:
    oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
```

New format required for 4.6.0:

```yaml
oidc_db_config_admin_auth:
  providers:
  - identifier: admin-oidc-provider
    endpoint_config:
      oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
  items:
  - identifier: admin-oidc
    oidc_provider_identifier: admin-oidc-provider
    userinfo_claims_source: id_token
    options:
      user_settings:
        claim_mappings:
          email: [email]
          first_name: [given_name]
          last_name: [family_name]
          username: [preferred_username]
      groups_settings:
        claim_mapping: [groups]
        sync: true
        sync_pattern: "*"
        default_groups: []
        make_users_staff: true
        superuser_group_names: [administrators]
```

Key changes:
- `claim_mapping` (dict) + `username_claim` → `options.user_settings.claim_mappings` (with `username` key added)
- `groups_claim` → `options.groups_settings.claim_mapping`
- `sync_groups` → `options.groups_settings.sync`
- `sync_groups_glob_pattern` → `options.groups_settings.sync_pattern`
- `make_users_staff` + `superuser_group_names` → moved into `options.groups_settings`
- `endpoint_config` (was inline on the item) → promoted to a top-level `providers` entry; item gains `oidc_provider_identifier` reference

**Automated migration:** use the provided script to convert any environment values file in one step:

```shell
# Dry-run (preview changes without writing):
python charts/podiumd/scripts/fix-oidc-config.py path/to/env-values.yaml --dry-run

# Migrate in-place:
python charts/podiumd/scripts/fix-oidc-config.py path/to/env-values.yaml

# Write to a new file:
python charts/podiumd/scripts/fix-oidc-config.py path/to/env-values.yaml -o env-values-migrated.yaml
```

The script is idempotent: running it on a file that is already fully migrated produces no changes. It also handles partially-migrated files (where some items use the new format and others still use the old one).

Requires: `pip install ruamel.yaml` (falls back to PyYAML if unavailable, but comments and formatting will be lost).

---

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

For **ACR-based environments**, add or update the repository overrides:

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

For environments that require a node selector (e.g. AKS-blue with `kubernetes.azure.com/mode: user`), set the nodeSelector on both the deployment and the migration job:

```yaml
pabc:
  nodeSelector:
    kubernetes.azure.com/mode: user
  migrations:
    nodeSelector:
      kubernetes.azure.com/mode: user
```

---

### `api-proxy` — `nginxinc/nginx-unprivileged` image

The api-proxy Deployment uses `runAsNonRoot: true`. The previous `nginx` image runs as root and was incompatible with this constraint. The image has been switched to `nginxinc/nginx-unprivileged`.

The Maykin subcharts (openzaak, openklant, openformulieren, openinwoner, openarchiefbeheer) and ZAC have always used `nginxinc/nginx-unprivileged` as their nginx sidecar — this is unchanged.

For **ACR-based environments**, the repository path must use `nginx-unprivileged` (not `nginx`) for all of these components. Add or verify the following overrides:

```yaml
# api-proxy
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

The `zac.pabc` key has been renamed to `zac.pabcApi` to match the ZAC chart schema. If your environment values file sets `zac.pabc`, rename the key:

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

### ZAC office-converter — `kontextwork-converter` image explicitly pinned, port configurable

The `office_converter` image is explicitly pinned to `ghcr.io/eugenmayer/kontextwork-converter:1.8.2` and `containerPort` is set to `8080` (kontextwork-converter's default). ZAC 1.0.224 makes `office_converter.containerPort` configurable; the chart default remains `3000` (Gotenberg) so the override in `values.yaml` is required.

For **ACR-based environments**, add the repository override:

```yaml
zac:
  office_converter:
    image:
      repository: <acr>/kontextwork-converter
```

No additional tag override needed — the tag is already pinned to `1.8.2` in PodiumD's `values.yaml`.

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

### ZooKeeper and Solr PVCs — `reclaimPolicy: Retain`

ZooKeeper and Solr PVCs now use `reclaimPolicy: Retain` (previously `Delete`). This prevents data loss during node rotation and operator scale-down events.

**No action required** for existing deployments — the reclaimPolicy on existing PVCs is not changed by `helm upgrade`. The change only takes effect for newly provisioned PVCs (fresh installs or after manual PVC recreation).

---

### Keycloak Operator and ECK Operator — ServiceMonitor / PodMonitor RBAC

Two new RBAC templates are added:

- `keycloak-operator-servicemonitor-rbac.yaml` — grants the keycloak-operator SA permission to discover and manage `ServiceMonitor` resources. The ClusterRole (read) is always rendered when `keycloak-operator.enabled: true`; without it the operator receives HTTP 403 on the `monitoring.coreos.com` API group and aborts reconciliation entirely.
- `eck-operator-podmonitor-rbac.yaml` — grants the `elastic-operator` SA permission to create and manage `PodMonitor` resources for ECK-managed Elasticsearch/Kibana instances. Rendered when `kisselastic.enabled: true` and `kisselastic.eck-operator.podMonitor.enabled: true`.

**No action required.** Both templates are automatically included and activate based on existing enabled/disabled flags.

---

### Redis HA — `redis_exporter` sidecar and PodMonitor

A new `redis_exporter` sidecar (port 9121) and a corresponding `PodMonitor` can now be enabled per environment. Both are **disabled by default**.

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

The ClamAV chart (v3.7.1) ships a built-in `clamav_exporter` sidecar and `ServiceMonitor`. Both are **disabled by default**. Enable via `values-enable-observability.yaml`:

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

> **Note:** Adding the sidecar changes the ClamAV pod spec. See [Pre-deploy steps](#pre-deploy-steps) below.

---

### Security hardening — container security contexts

All custom pod templates (api-proxy, adapter, Keycloak jobs, seeding jobs, redis-ha label CronJob) now have `readOnlyRootFilesystem: true` and explicit `runAsNonRoot: true` / `runAsUser` settings. Writable paths (`/tmp`, `/var/cache/nginx`) are provided via `emptyDir` volumes where needed.

Keycloak job pods now explicitly reference the podiumd `ServiceAccount` name. The `ServiceAccount` has `automountServiceAccountToken: false` set globally; the redis-ha label CronJob opts back in (`automountServiceAccountToken: true` on the pod spec) because it needs API server access.

**No action required.** These are template-only changes with no values impact.

---

### Security hardening — api-proxy TLS verification enabled

`apiproxy.locations.commonSettings.sslVerify` now defaults to `"on"` (previously `"off"`). The CA certificate infrastructure was already wired (`nginxCertsSecret`) but was being silently ignored.

**Action required** if `nginxCertsSecret` is set: ensure `ca.crt` in the referenced secret contains the CA chain that signed the upstream government API (BAG/BRP/KVK) server certificate. If the CA is not available, explicitly override the default in your environment values:

```yaml
apiproxy:
  locations:
    commonSettings:
      sslVerify: "off"   # temporary — remove once CA cert is available
```

---

### Keycloak security — TOTP always required in master realm

`adminOtpEnabled` has been removed as a configurable flag. TOTP (OTP) is now unconditionally required for all admin accounts in the master realm. The Keycloak admin UI will prompt for TOTP setup on next login if it was not previously configured.

**No action required** for environments already using TOTP. For environments where TOTP was disabled (`adminOtpEnabled: false`), admin accounts will be prompted to set up an authenticator app on next login.

---

### Keycloak security — SSO session lifetime limits

Both realm configs now enforce SSO session limits:

| Setting | Value |
|---|---|
| `ssoSessionMaxLifespan` | 36000 s (10 h) |
| `ssoSessionIdleTimeout` | 1800 s (30 min) |

These limits apply to browser SSO sessions (not to individual access tokens, which are controlled by `accessTokenLifespan`). Sessions that exceed these limits will require re-authentication.

**No action required.**

---

### `zgw-office-addin` — breaking values schema change

The `zgw-office-addin` subchart restructured its values. Any environment values file that sets the following keys must be updated:

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

## Pre-deploy steps

1. **Add `REP_KEYCLOAK_OPERATOR_SA_CLIENT_SECRET_REP`** to the pipeline secrets/replacements.

2. **Remove Infinispan** — Infinispan has been removed as a dependency in 4.6.0. Remove the `openshift` Helm repo if it was added solely for Infinispan:
   ```shell
   helm repo remove openshift
   ```

3. **Remove the `solr` Helm repo** — the Solr operator chart is fully bundled inside the ZAC chart tgz and does not need to be resolvable at deploy time. Keeping the repo entry causes spurious failures when `https://solr.apache.org/charts` is unavailable:
   ```shell
   helm repo remove solr apache-solr
   ```
   If only one of the two aliases exists, remove only that one. `helm dependency build` and `helm template` will continue to work without it.

4. **Add the `opstree` Helm repo** — the `redis-operator` dependency (OT Container Kit) requires a new repo entry:
   ```shell
   helm repo add opstree https://ot-container-kit.github.io/helm-charts/
   helm repo update opstree
   ```

5. **Install the Redis Operator CRDs** — Helm does not upgrade CRDs automatically on `helm upgrade`. Run the provided script before deploying:
   ```shell
   ./charts/podiumd/scripts/install-redis-operator-crds.sh --context <kubectl-context>
   ```
   Always pass `--context` to pin the target cluster and avoid accidentally modifying the wrong cluster. To preview what will be applied without making changes:
   ```shell
   ./charts/podiumd/scripts/install-redis-operator-crds.sh --context <kubectl-context> --dry-run
   ```

6. **Allowlist ClamAV database update endpoints** — ClamAV 4.6.0 introduces a persistent volume and a working freshclam configuration. Ensure the following egress endpoints are reachable from the cluster:

   | Endpoint | Protocol/Port | Purpose |
   |---|---|---|
   | `current.cvd.clamav.net` | DNS TXT (UDP/TCP 53) | Version check before downloading updates |
   | `database.clamav.net` | HTTPS (TCP 443) | Virus database download (`daily.cvd`, `main.cvd`, `bytecode.cvd`) |

   Without access to these endpoints, freshclam will fail silently and the virus database will become stale. If an HTTP proxy is required, add `HTTPProxyServer` and `HTTPProxyPort` to the `clamav.freshclamConfig` override in the environment values file.

7. **Delete the ClamAV StatefulSet before upgrading** — the chart adds a `volumeClaimTemplate` and `extraVolumeMounts` to the ClamAV StatefulSet. Kubernetes does not allow patching immutable StatefulSet fields, so `helm upgrade` will fail unless the existing StatefulSet is removed first. The pod will be recreated automatically by Helm during the upgrade. Also required if enabling `clamav.metrics.enabled: true` for the first time.

   ```shell
   kubectl delete statefulset clamav -n podiumd --context <kubectl-context>
   ```

   > **Note:** Deleting the StatefulSet does not delete the PVC. If a `clamav-data-clamav-0` PVC already exists from a previous deploy it will be reused. On a fresh environment the PVC will be created by the StatefulSet's `volumeClaimTemplate` on first deploy and ClamAV will download the virus database on startup (allow ~2–3 minutes).

8. **Migrate Redis HA PVCs to `managed-csi-premiumv2`** *(only if you previously deployed a 4.6.x intermediate release)* — the Redis HA storage class has been changed from `managed-csi` to `managed-csi-premiumv2` for better I/O performance. **Redis only stores cache data** — all data will be automatically rebuilt after restart. No data export is needed.

   **Option A: Full migration (brief Redis outage)**

   ```bash
   # 1. Delete the Redis HA StatefulSet so the operator recreates it with the new storage class.
   kubectl delete statefulset redis-ha -n podiumd --context <cluster>

   # 2. Delete the existing PVCs (cache data — safe to delete).
   kubectl delete pvc \
     redis-ha-redis-ha-0 \
     redis-ha-redis-ha-1 \
     redis-ha-redis-ha-2 \
     -n podiumd --context <cluster>

   # 3. Run helm upgrade as normal. The operator will create new PVCs on managed-csi-premiumv2.
   ```

   > The applications (openzaak, openklant, etc.) may briefly return errors while Redis is unavailable during the migration. This resolves automatically once Redis recovers.

   **Option B: Rolling migration (no full Redis outage)**

   Run `helm upgrade` first — this updates the `RedisReplication` CRD. Then verify the StatefulSet has the new `volumeClaimTemplate`:

   ```bash
   kubectl get statefulset redis-ha -n podiumd --context <cluster> \
     -o jsonpath='{.spec.volumeClaimTemplates[0].spec.storageClassName}'
   # Expected: managed-csi-premiumv2
   ```

   Then migrate each replica in turn (waiting for `Ready` before proceeding to the next):

   ```bash
   for i in 0 1 2; do
     kubectl delete pvc redis-ha-redis-ha-$i -n podiumd --context <cluster>
     kubectl delete pod redis-ha-$i -n podiumd --context <cluster>
     kubectl wait pod/redis-ha-$i -n podiumd --context <cluster> --for=condition=Ready --timeout=120s
   done
   ```

9. **Delete completed seeding and realm-import Jobs** *(only if you previously deployed a 4.6.x intermediate release)* — security hardening changes the pod template of all custom Jobs to add `readOnlyRootFilesystem: true`, explicit `serviceAccountName`, and `runAsUser`. Kubernetes treats completed `Job` resources as immutable — `helm upgrade` will fail with `spec.template: Invalid value` if these Jobs still exist.

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

   > These are one-time idempotent seeding Jobs. Deleting them is safe — Helm will recreate them during the upgrade and they will re-run. The ZAC CronJobs (`zac-sig-del`, `zac-signaleren`) are managed by the ZAC subchart, are not affected by this change, and must **not** be deleted.

10. **Update `zgw-office-addin` values schema** — see [zgw-office-addin breaking values schema change](#zgw-office-addin--breaking-values-schema-change) above. The Helm upgrade will fail with a schema validation error if these keys are not renamed before upgrading.

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

| Component | 4.5.16 | 4.6.4 |
|---|---|---|
| keycloak-operator | 1.11.2 (26.5.7) | 1.11.2 (26.5.7) |
| clamav | 3.2.0 | 3.7.1 |
| openzaak | 1.13.0 | 1.13.1 |
| opennotificaties | 1.13.0 | 1.13.1 |
| objecten | 2.11.0 | 2.12.0 |
| objecttypen | 1.6.0 | 1.6.1 |
| openklant | 1.10.0 | 1.11.0 |
| openformulieren (openforms) | 1.11.6 | 1.12.0 |
| openinwoner | 2.1.0 | 2.1.3 |
| zac | 1.0.165 | 1.0.224 |
| zgw-office-addin | 0.0.65 | 0.9.251 |
| ita | 2.0.1 | 3.0.0 |
| kiss | 2.1.0 | 2.2.2 |
| pabc | 1.1.0 | 1.1.0 |
| alpine/k8s (labelMasterCronJob) | — | 1.33.10 |
| nginx-unprivileged (api-proxy + Maykin/ZAC sidecars) | — | 1.29.8 |

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.4.yaml](images/images-4.6.4.yaml).
