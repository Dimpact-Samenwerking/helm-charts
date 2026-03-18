## Zaakbrug integration into podiumd (Phase 1)

This document describes the Phase 1 changes to integrate the `wearefrank/zaakbrug` Helm chart into the `podiumd` umbrella chart, assuming **manual** Keycloak and Zaakbrug console configuration as per `/Users/jim/src/Sunningdale-IT/zaakbrug/Instructions.md`.

---

## 1. Chart dependency

Zaakbrug is added as a subchart dependency of podiumd in `charts/podiumd/Chart.yaml`:

```yaml
dependencies:
  ...
  - name: pabc
    alias: pabc
    repository: "oci://ghcr.io/platform-autorisatie-beheer-component"
    version: 1.0.0
    condition: pabc.enabled
  - name: zaakbrug
    repository: "@wearefrank"
    version: 2.3.22
    condition: zaakbrug.enabled
```

Helm repo requirement:

- `helm repo add wearefrank https://wearefrank.github.io/charts`

---

## 2. Generic zaakbrug values in `charts/podiumd/values.yaml`

A new top-level `zaakbrug:` block is added to `charts/podiumd/values.yaml`. It is based on the standalone Zaakbrug `frankvalues.yaml`, but contains **no real secrets** and uses safe defaults:

- **Enable flag and identification**
  - `zaakbrug.enabled: false`
  - `zaakbrug.nameOverride`, `zaakbrug.fullnameOverride`

- **Image**
  - Defaults to the Frank!Framework Zaakbrug image:
    - `registry: wearefrank`
    - `repository: zaakbrug`
    - `tag: ""` (to use the chart default)

- **Frank! configuration (`zaakbrug.frank.*`)**
  - Memory (`minimum`, `maximum`, `percentage`).
  - DTAP stage/side.
  - Credentials (name of the secret and key for `credentials.properties`).
  - Instance, configurations, security (certificateStores, http, activeDirectory).
  - Server transaction manager.

- **Console OAuth2 (Frank! console)**
  - Under `zaakbrug.frank.environmentVariables` the following keys are defined:
    - `application.security.console.authentication.type: "OAUTH2"`
    - `application.security.console.authentication.provider: "custom"`
    - `application.security.console.authentication.clientId: "zaakbrug"`
    - `application.security.console.authentication.clientSecret: ""` (empty in shared values)
    - `application.security.console.authentication.issuerUri: "https://keycloak.example.nl/realms/podiumd"`
    - `application.security.console.authentication.authorizationUri`, `tokenUri`, `userInfoUri`, `jwkSetUri` pointing at `https://keycloak.example.nl/realms/podiumd/...`
    - `application.security.console.authentication.userNameAttributeName: "preferred_username"`
    - `application.security.console.authentication.scopes: "openid,profile,email,roles"`
    - `application.security.console.authentication.authoritiesClaimName: "roles"`

  These are **placeholders** and must be overridden per environment (see section 3).

- **JDBC connections (`zaakbrug.connections.*`)**
  - A single JDBC entry is defined with:
    - `type: postgresql`
    - Empty `host`, `password` and default `port: "5432"`, `database: zaakbrug`, `username: zaakbrug-admin`.
  - Real connection details are set in environment-specific values.

- **Zaakbrug-specific configuration (`zaakbrug.zaakbrug.*`)**
  - ZDS timezone and SOAP endpoints (`beantwoordVraag`, `ontvangAsynchroon`, `vrijeBerichten`, v2 variants).
  - ZGW settings:
    - Identification templates for zaak, document, besluit.
    - `zakenApi`, `catalogiApi`, `documentenApi`, `besluitenApi` blocks with:
      - `rootUrl: ""` (to be overridden per environment).
      - JWT authType/authAlias, timeouts, TLS flags, truststore placeholders.
  - Globals:
    - `organizations: []` in the generic file.
    - `rolMapping` for zaak roles.
  - Routing `profileDefaults` for common ZDS actions.

- **Staging (`zaakbrug.staging.*`)**
  - Disabled by default: `staging.enabled: false`.
  - Contains Open Zaak staging URLs, persistence, and API proxy settings, mirroring the upstream chart.

- **Operational settings**
  - Replica/probes/autoscaling/resources.
  - Node selectors, tolerations, affinity.
  - Service and ingress defaults.
  - ServiceAccount/pod labels/security context.
  - Persistence (disabled by default, with generic PVC settings).

---

## 3. Environment-specific wiring (Dimpact ontw)

The file:

- `/Users/jim/src/ExternalsPodiumD/applications/gemeenten/dimp/ontw/podiumd.yml`

is extended with a `zaakbrug:` section to enable and configure Zaakbrug for the **ontwikkelomgeving**.

### 3.1 Enabling zaakbrug and console OAuth2

```yaml
zaakbrug:
  enabled: true

  frank:
    ...
    environmentVariables:
      application.security.console.authentication.type: "OAUTH2"
      application.security.console.authentication.provider: "custom"
      application.security.console.authentication.clientId: "zaakbrug"
      application.security.console.authentication.clientSecret: "REP_ZAAKBRUG_OIDC_SECRET_REP"
      application.security.console.authentication.issuerUri: "https://ontw-keycloak.dimpact.nl/realms/podiumd"
      application.security.console.authentication.authorizationUri: "https://ontw-keycloak.dimpact.nl/realms/podiumd/protocol/openid-connect/auth"
      application.security.console.authentication.tokenUri: "https://ontw-keycloak.dimpact.nl/realms/podiumd/protocol/openid-connect/token"
      application.security.console.authentication.userInfoUri: "https://ontw-keycloak.dimpact.nl/realms/podiumd/protocol/openid-connect/userinfo"
      application.security.console.authentication.jwkSetUri: "https://ontw-keycloak.dimpact.nl/realms/podiumd/protocol/openid-connect/certs"
      application.security.console.authentication.userNameAttributeName: "preferred_username"
      application.security.console.authentication.scopes: "openid,profile,email,roles"
      application.security.console.authentication.authoritiesClaimName: "roles"
```

- `REP_ZAAKBRUG_OIDC_SECRET_REP` is a placeholder for the confidential client secret from the Keycloak `zaakbrug` client.
- The URLs match the `ontw` Keycloak realm `pdm podiumd` and follow the working standalone configuration from `frankvalues.yaml` and `Instructions.md`.

### 3.2 Database connection

```yaml
  connections:
    create: true
    jdbc:
      - name: ""
        type: postgresql
        host: psql-ontw-dimp.postgres.database.azure.com
        port: "5432"
        database: zaakbrug
        username: zaakbrug-admin
        password: "REP_ZAAKBRUG_DATABASE_PASSWORD_REP"
        ssl: true
    jms: []
```

- Uses the same Azure Postgres host as other podiumd components in this environment.
- `REP_ZAAKBRUG_DATABASE_PASSWORD_REP` is a placeholder for the actual DB password.

### 3.3 ZGW endpoints and globals

```yaml
  zaakbrug:
    zds:
      timezone: Etc/UTC
    soap:
      ...
    zgw:
      zakenApi:
        rootUrl: "https://ontw-openzaak.dimpact.nl/zaken/api/v1/"
        ...
      catalogiApi:
        rootUrl: "https://ontw-openzaak.dimpact.nl/catalogi/api/v1/"
        ...
      documentenApi:
        rootUrl: "https://ontw-openzaak.dimpact.nl/documenten/api/v1/"
        ...
      besluitenApi:
        rootUrl: "https://ontw-openzaak.dimpact.nl/besluiten/api/v1/"
        ...
    globals:
      organizations:
        - gemeenteNaam: "Súdwest-Fryslân"
          gemeenteCode: "1900"
          RSIN: "823288444"
        - gemeenteNaam: "Haarlem"
          gemeenteCode: "0392"
          RSIN: "001005650"
        - gemeenteNaam: "Zeevang"
          gemeenteCode: "0478"
          RSIN: "001509962"
        - gemeenteNaam: "Eindhoven"
          gemeenteCode: "0772"
          RSIN: "548746485"
      rolMapping:
        heeftBetrekkingOp: "BetrekkingOp"
        heeftAlsBelanghebbende: "Belanghebbende"
        heeftAlsInitiator: "Initiator"
        heeftAlsUitvoerende: "Uitvoerende"
        heeftAlsVerantwoordelijke: "Verantwoordelijke"
        heeftAlsGemachtigde: "Gemachtigde"
        heeftAlsOverigBetrokkene: "OverigeBetrokkene"
    routing:
      profileDefaults:
        ...
```

- The ZGW URLs are aligned with other podiumd components in the same environment (Open Zaak under `ontw-openzaak.dimpact.nl`).
- Organizations and role mapping match the standalone Zaakbrug configuration.

---

## 4. Phase 1 vs Phase 2 responsibilities

**Phase 1 (implemented now):**

- Podiumd:
  - Pulls the `wearefrank/zaakbrug` subchart as a dependency.
  - Exposes a `zaakbrug` values block for generic configuration.
  - Provides environment-specific overrides (ontw) for:
    - Keycloak OAuth2 env vars (URLs + clientId, with placeholder for clientSecret).
    - JDBC connection to Azure Postgres.
    - ZGW endpoints, organizations, and routing defaults.
- Keycloak + Zaakbrug console:
  - Still configured **manually**, following `/Users/jim/src/Sunningdale-IT/zaakbrug/Instructions.md`:
    - Create `zaakbrug` client, roles, mappers.
    - Create the `zaakbrug-oauth-role-mapping` ConfigMap.
    - Use post-renderer scripts if needed (outside podiumd).

**Phase 2 (future work):**

- Consider declarative Keycloak automation via the existing `keycloak-operator` integration in podiumd:
  - Manage the `zaakbrug` client, roles, and `User Client Role` mapper as code.
  - Optionally move the role-mapping ConfigMap and volumeMount into the podiumd chart itself.
  - Keep secrets (client secret, DB passwords) in the same pattern used by other components.

---

## 5. How to test

1. Ensure Helm repos are configured:
   - `helm repo add wearefrank https://wearefrank.github.io/charts`
   - `helm repo update`
2. Render podiumd with Zaakbrug enabled using the ontw values to confirm:
   - Zaakbrug subchart templates are included.
   - The rendered Zaakbrug Deployment has the expected console OAuth2 env vars and JDBC connection.
3. Deploy podiumd into a test namespace with the updated values.
4. Manually complete Keycloak + role-mapping setup as per `Instructions.md`.
5. Verify:
   - Zaakbrug pod is healthy and has DB and Open Zaak connectivity.
   - Console login is redirected to Keycloak and back successfully.

