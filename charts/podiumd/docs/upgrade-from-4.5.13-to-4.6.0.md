# Upgrade guide: PodiumD 4.5.13 → 4.6.0

## Breaking changes

### Bitnami Keycloak subchart removed
The deprecated `keycloak` (Bitnami) subchart has been removed from `Chart.yaml`.

- Remove `keycloak.enabled: false` from environment values — the key no longer exists.
- Remove any remaining Bitnami-specific fields if still present:
  `cache`, `customCaExistingSecret`, `extraEnvVars`, `extraEnvVarsCM`, `extraStartupArgs`,
  `replicaCount`, `networkPolicy`, `podSecurity`, `keycloakConfigCli.nodeSelector`.
- Remove `keycloak.ingress.hostnameStrict` — no longer supported by the operator CR.

### Infinispan subchart removed
The deprecated `infinispan` subchart has been removed from `Chart.yaml`.

- Remove or keep `infinispan.enabled: false` — the key is now ignored (subchart gone).
  Best practice: remove the entire `infinispan:` block from environment values.

### keycloak-config-cli image updated
The image moved from `quay.io/adorsys/keycloak-config-cli:6.4.0-28.5.0` to
`adorsys/keycloak-config-cli:6.4.1-26`. Update the repository override in environment values:

```yaml
keycloak:
  keycloakConfigCli:
    image:
      repository: <acr>/keycloak-config-cli   # was keycloak-config-cli (old tag 6.4.0-28.5.0)
```

### rabbitmq image renamed (bitnami → bitnamilegacy)
Bitnami renamed their RabbitMQ image to `bitnamilegacy/rabbitmq`. The chart now sets
`registry: docker.io` and `repository: bitnamilegacy/rabbitmq` as defaults.

For ACR-based environments, override to pull from ACR:

```yaml
opennotificaties:
  rabbitmq:
    image:
      registry: <acr>
      repository: bitnamilegacy/rabbitmq
```

## New features / additions

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

### keycloak-operator version bump: 26.5.4 → 26.5.5
The operator image tag changed. For ACR environments: no tag override needed (chart default applies).

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

1. **Install Keycloak CRDs** (if not already done for 4.5.x):
   ```bash
   ./scripts/install-keycloak-operator-crds.sh
   ```
   CRDs must have the Helm management annotations for the `podiumd` release:
   - `meta.helm.sh/release-name: podiumd`
   - `meta.helm.sh/release-namespace: podiumd`
   - `app.kubernetes.io/managed-by: Helm`

2. **Run the KISS schema migration** (if upgrading from 4.4.x, not needed from 4.5.x):
   ```bash
   pip install ruamel.yaml
   python scripts/migrate-kiss-schema.py <env-values.yaml>
   ```

3. **Add `REP_KEYCLOAK_OPERATOR_SA_CLIENT_SECRET_REP`** to the pipeline secrets/replacements.
