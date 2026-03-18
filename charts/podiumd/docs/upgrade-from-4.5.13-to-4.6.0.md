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

## Pre-deploy steps

1. **Add `REP_KEYCLOAK_OPERATOR_SA_CLIENT_SECRET_REP`** to the pipeline secrets/replacements.

2. **Remove Infinispan** — Infinispan has been removed as a dependency in 4.6.0. It was previously used as the Keycloak session cache but is no longer needed with the Keycloak Operator.

   Run the cleanup script before or after the upgrade to remove the leftover Infinispan resources:
   ```shell
   scripts/cleanup-keycloak-and-infinispan.sh
   ```

   Or remove manually:
   ```shell
   kubectl delete statefulset -n podiumd -l app.kubernetes.io/name=infinispan
   kubectl delete service -n podiumd -l app.kubernetes.io/name=infinispan
   kubectl delete configmap -n podiumd -l app.kubernetes.io/name=infinispan
   kubectl delete secret -n podiumd infinispan-secret
   kubectl delete pvc -n podiumd -l app.kubernetes.io/name=infinispan
   ```

   Also remove any `infinispan.*` overrides from environment values files — the key no longer exists in `values.yaml`.

   Additionally, remove the `openshift` Helm repo if it was added solely for Infinispan:
   ```shell
   helm repo remove openshift
   ```
