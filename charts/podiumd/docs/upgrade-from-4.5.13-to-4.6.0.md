# Upgrade guide: PodiumD 4.5.13 → 4.6.0

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

### keycloak image: new `registry` field
A `registry` field was added to `keycloak.image` and `keycloak.keycloakConfigCli.image`.
For ACR environments that embed the full path in `repository`, leave `registry` unset or set to `""`.

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

### zac: initContainer enabled by default
`zac.initContainer.enabled` changed default from `false` to `true`.
Remove any explicit `initContainer.enabled: false` override if you want the new default behaviour.

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.5.13 | 4.6.0 |
|-----------|--------|-------|
| keycloak-operator | 1.11.2 (26.5.4) | 1.11.2 (26.5.5) |
| openzaak | 1.13.0 → 1.13.1 | image: n/a (no tag in env) |
| opennotificaties | 1.13.0 → 1.13.1 | |
| objecten | 2.11.0 → 2.12.0 | image 3.5.0 → 3.6.0 |
| objecttypen | 1.6.0 → 1.6.1 | image 3.4.0 → 3.5.0 |
| openklant | 1.10.0 → 1.11.0 | image 2.14.0 → 2.15.0 |
| openformulieren | 1.11.6 → 1.12.0 | image 3.3.13 → 3.4.5 |
| openinwoner | 2.1.0 → 2.1.3 | image 2.0.3 → 2.1.0 |
| zac | 1.0.165 → 1.0.194 | image 4.0.12-1 → 4.3.61 |
| zgw-office-addin | 0.0.65 → 0.0.73 | frontend+backend v0.9.28 → v0.9.133 |

## Environment values changes

### Enable configuration jobs for objecten and opennotificaties

The `objecten` and `opennotificaties` subcharts default to `job.enabled: false` at the subchart level, which takes precedence over the parent `podiumd/values.yaml` default of `true`. Without an explicit override, the setup-configuration job does not run for these two components, leaving OIDC (and other configuration steps) unapplied in the database.

Add the following to each environment's values file:

```yaml
objecten:
  configuration:
    job:
      enabled: true
      backoffLimit: 6
      ttlSecondsAfterFinished: 600
      restartPolicy: OnFailure

opennotificaties:
  configuration:
    job:
      enabled: true
      backoffLimit: 6
      restartPolicy: OnFailure
```

Without this, the OIDC login will fail with `KeyError: 'groups_settings'` on first login attempt because the `OIDCProvider`/`OIDCClient` database records are never populated.

### Enable Redis HA and remove per-service Redis subchart config

The per-service Redis subcharts (openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openinwoner) are replaced by a single shared Redis HA cluster.

1. **Add a `redis-operator:` block** to enable the operator and the shared cluster:

   ```yaml
   redis-operator:
     enabled: true
     nodeSelector:
       kubernetes.azure.com/mode: user
     initContainerImage:                              # ACR environments only
       registry: myacr.azurecr.io
       repository: busybox
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

   For non-ACR environments, omit the `initContainerImage`, `redisOperator`, `image`, `redisExporter.image`, and `redis-ha.initContainerImage` overrides.

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

4. **Install the Redis Operator CRDs** — Helm does not upgrade CRDs automatically on `helm upgrade`. Run the provided script before deploying:
   ```shell
   ./charts/podiumd/scripts/install-redis-operator-crds.sh --context <kubectl-context>
   ```
   Always pass `--context` to pin the target cluster and avoid accidentally modifying the wrong cluster. To preview what will be applied without making changes:
   ```shell
   ./charts/podiumd/scripts/install-redis-operator-crds.sh --context <kubectl-context> --dry-run
   ```

5. **Allowlist ClamAV database update endpoints** — ClamAV 4.6.0 introduces a persistent volume and a working freshclam configuration. Ensure the following egress endpoints are reachable from the cluster:

   | Endpoint | Protocol/Port | Purpose |
   |---|---|---|
   | `current.cvd.clamav.net` | DNS TXT (UDP/TCP 53) | Version check before downloading updates |
   | `database.clamav.net` | HTTPS (TCP 443) | Virus database download (`daily.cvd`, `main.cvd`, `bytecode.cvd`) |

   Without access to these endpoints, freshclam will fail silently and the virus database will become stale.
   If an HTTP proxy is required, add `HTTPProxyServer` and `HTTPProxyPort` to the `clamav.freshclamConfig` override in the environment values file.

6. **Delete the ClamAV StatefulSet before upgrading** — the 4.6.0 chart adds a `volumeClaimTemplate` and `extraVolumeMounts` to the ClamAV StatefulSet. Kubernetes does not allow patching immutable StatefulSet fields, so `helm upgrade` will fail unless the existing StatefulSet is removed first. The pod will be recreated automatically by Helm during the upgrade.

   ```shell
   kubectl delete statefulset clamav -n podiumd --context <kubectl-context>
   ```

   > **Note:** Deleting the StatefulSet does not delete the PVC. If a `clamav-data-clamav-0` PVC already exists from a previous deploy it will be reused. On a fresh environment the PVC will be created by the StatefulSet's `volumeClaimTemplate` on first deploy and ClamAV will download the virus database on startup (allow ~2–3 minutes).