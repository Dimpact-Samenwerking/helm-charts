# OMC (Output Management Component) — Basics

## Management summary

OMC is the notification engine of PodiumD. When something happens with a
citizen's case — it is created, updated or closed — OMC picks up that event and
makes sure the citizen automatically receives an email or SMS about it, via the
national NotifyNL messaging service. Municipalities control which case types
trigger notifications and what the messages look like (templates are managed by
the municipality in the NotifyNL portal). OMC needs no database or storage of
its own; it only needs API credentials for the surrounding PodiumD services and
a NotifyNL API key. Its footprint is a single small container (default limit
0.5 CPU / 512Mi memory). It is disabled by default and is only turned on for
municipalities that have completed NotifyNL onboarding.

## What it is

- Upstream project: [NotifyNL-OMC](https://github.com/Worth-NL/NotifyNL-OMC)
  by Worth-NL (a .NET "Events Handler" web API; container command
  `dotnet OMC.EventsHandler.dll`).
- Sub-chart: `notifynl-omc-nodep` `0.14.1` (aliased `omc`) from
  [Worth-NL/helm-charts](https://github.com/Worth-NL/helm-charts), condition
  `omc.enabled` (default **false**), `fullnameOverride: "omc"`.
- Image: `docker.io/worthnl/notifynl-omc:1.17.19` (sub-chart default
  repository; tag pinned in `values.yaml`; Dimpact environments override the
  repository to the ACR mirror `acrprodmgmt.azurecr.io/omc`).
- Role in the stack: subscribes to Open Notificaties events
  (`/Events/Listen`), evaluates them against a zaaktype whitelist, looks up the
  citizen's contact preferences in OpenKlant, sends email/SMS through the
  NotifyNL API, receives NotifyNL delivery callbacks (`/Notify/Confirm`), and
  registers the contact moment back in OpenKlant. PodiumD runs OMC workflow
  version 2 (`omc.settings.omc.feature.workflow.version: 2`, OpenKlant 2.x).
- Runtime components: one Deployment `omc` (single container, fixed
  `replicas: 1`, TCP probes on app port 5270), a ClusterIP Service `omc`
  (port 80 → 5270), plus a ConfigMap and Secret rendered by the sub-chart that
  feed all settings to the container as environment variables. No workers,
  beat, nginx sidecar or CRs.

## Required resources

### Database

None. OMC is stateless — the sub-chart renders no PostgreSQL configuration and
OMC is deliberately absent from the `mi:` export targets list. The usual
`<component>` Secret (`DB_PASSWORD`) / ConfigMap (`DB_HOST`/`DB_NAME`/`DB_USER`)
contract does not apply.

### Storage

None. The sub-chart has no PVC template; all state lives in the surrounding
services (Open Zaak, OpenKlant, Objecten) and in NotifyNL.

### Routing / exposure (NGINX Gateway Fabric)

Public: `https://<env>-omc.dimpact.nl` via HTTPRoute `hr-omc` (gateway
`public-gateway`, namespace `ingress-basic`), backend service `omc` on port 80.
The HTTPRoute is created by the per-gemeente environment deployment
(ADO `ExternalsPodiumD`), not by this chart. The public URL must exist because
two external parties call in:

- NotifyNL delivery callback: `https://<env>-omc.dimpact.nl/Notify/Confirm`
- Open Notificaties subscription (abonnement) callback:
  `https://<env>-omc.dimpact.nl/Events/Listen`

The sub-chart's own `ingress:` block stays disabled (`enabled: false`).

### Other dependencies

- **NotifyNL** (`https://api.notifynl.nl`): API key
  (`omc.settings.notify.api.key`, Key Vault item `notify-credentials-omc`,
  format `<prefix>-<UUID>-<UUID>` enforced by the chart schema) plus message
  template IDs (`omc.settings.notify.templateId.*` — email and SMS variants for
  zaakCreate/zaakUpdate/zaakClose; taskAssigned, messageReceived and
  decisionMade exist in the sub-chart but those scenarios are not yet supported
  in PodiumD). The NotifyNL account and templates are created by the
  municipality's Functioneel Beheer, delivered via Dimpact productbeheer.
- **Open Notificaties**: an abonnement pointing at `/Events/Listen`,
  authorised with a JWT signed with `omc.settings.omc.auth.jwt.secret`
  (Key Vault `omc-auth-secret`, schema-validated `minLength: 64`).
- **Open Zaak**: OMC registered as authorised application + ZGW client
  credentials (`client_id` `omc`, secret = `omc.settings.zgw.auth.jwt.secret`).
- **OpenKlant**: token auth entry (`omc.settings.zgw.auth.key.openklant`) and
  an "OMC-Notify" actor (UUID goes into `omc.settings.omc.actor.id`).
- **Objecten / Objecttypen**: token auth entries
  (`omc.settings.zgw.auth.key.objecten` / `.objectTypen`); Objecten needs
  read/write permissions on the contact object types. Dummy object-type UUIDs
  are pre-set in `omc.settings.zgw.variable.objectType.*`.
- **Service endpoints**: `omc.settings.zgw.endpoint.*` must point at the
  environment's Open Notificaties, Open Zaak (zaken + besluiten), OpenKlant,
  Objecten and Objecttypen API URLs.
- **No Keycloak OIDC** for its own authentication. (The sub-chart does have
  optional `settings.keycloak.*` client-credentials and `settings.brp.*` mTLS
  fields for BRP/Haal Centraal access, and optional `settings.kto.*` for a
  customer-satisfaction service — none are set in the PodiumD values.)
- **Redis / ClamAV / Elasticsearch / RabbitMQ / SMTP**: not used.
- Note: the sub-chart's default `settings.sentry.dsn` points at Worth-NL's
  Sentry instance; environments should override it (set `dsn: ""` to disable).

## CPU and memory

The podiumd `values.yaml` does **not** override the sub-chart resources (the
block is present but commented out); the sub-chart defaults apply, matching
`docs/resource-overview.md` ("OMC (NotifyNL)"):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| omc       | 250m        | 128Mi       | 500m      | 512Mi     |

Observed usage: none available — OMC was not running on either
aks-blue-ontw-dimp or aks-blue-accp-dimp at capture time (2026-07-10), although
the `hr-omc` HTTPRoute for `ontw-omc.dimpact.nl` already exists on ontw. The
figures above are chart defaults only. Given it is a single event-driven .NET
container, the defaults are a reasonable starting point; validate against real
traffic once a municipality goes live.

## Integrating OMC as a new app

OMC needs inputs that the platform team cannot generate itself — collect the
municipality's NotifyNL artefacts first.

1. **Receive inputs from Dimpact productbeheer** (originating from the
   municipality's Functioneel Beheer): NotifyNL API key, the email/SMS template
   IDs, the OpenKlant "OMC-Notify" actor UUID, and the zaaktype whitelist per
   scenario. Stop if any is missing.
2. **Create Key Vault secrets** per environment: `notify-credentials-omc`
   (delivered API key), `omc-auth-secret` (min 64 chars, e.g.
   `openssl rand -base64 48`), and SSC-generated
   `openzaak-credentials-omc-secret`, `openklant-credentials-omc-token`,
   `objecten-credentials-omc-token`, `objecttypen-credentials-omc-token`
   (`openssl rand -hex 32` each). Wire them as `REP_..._REP` substitutions in
   the deployment pipeline.
3. **Register the Worth-NL Helm repo** in the pipeline
   (`helm repo add worth-nl https://worth-nl.github.io/helm-charts`) — needed
   for `helm dependency build`.
4. **Enable and configure in the gemeente values file**: `omc.enabled: true`,
   `omc.image.repository` (ACR mirror), `omc.settings.notify.api.key` and
   `templateId.*`, `omc.settings.omc.actor.id`,
   `omc.settings.omc.auth.jwt.secret`, `omc.settings.zgw.auth.jwt.secret` +
   `issuer: "omc"`, `omc.settings.zgw.auth.key.*`,
   `omc.settings.zgw.endpoint.*` (environment API URLs) and
   `omc.settings.zgw.whitelist.*` (`"*"` for ontw/accp; explicit
   zaaktype-identificatie lists for prod; keep taskAssigned/decisionMade set to
   a non-existent id and `message.allowed: false` — not yet supported).
5. **Register OMC as a peer** in the ZGW services via their
   `configuration.data` blocks: Open Zaak (authorised application + credentials
   for client `omc`), OpenKlant / Objecten / Objecttypen (tokenauth entries;
   Objecten with read/write permissions on the contact object types).
6. **DNS + HTTPRoute**: expose service `omc` (port 80) as
   `<env>-omc.dimpact.nl` via an `hr-omc` HTTPRoute on `public-gateway`
   (environment deployment).
7. **Deploy** and confirm the `omc` pod reaches Ready; a crash-loop usually
   means a missed `REP_..._REP` substitution.
8. **Create the Open Notificaties abonnement** with callback
   `https://<env>-omc.dimpact.nl/Events/Listen` and an `Authorization: Bearer`
   JWT (HS256, signed with `omc-auth-secret`, claims `client_id`/`iss`/`aud` =
   `omc`, `user_id`/`user_representation` = `OMC (PodiumD)`).
9. **Hand off the NotifyNL callback URL**
   (`https://<env>-omc.dimpact.nl/Notify/Confirm`) to Dimpact productbeheer for
   registration in the municipality's NotifyNL admin.
10. **Smoke test**: set `statustype.informeren: true` on a zaaktype, create a
    zaak for a partij with a BSN and a working `voorkeursdigitaalAdres`
    (NotifyNL Gastenlijst on test environments), then verify the notification
    arrives and a Klantcontact appears in OpenKlant.

For the full per-step detail (pipeline snippets, exact `configuration.data`
blocks) see `docs/_UPGRADE_PATHS/4.6.4-to-4.6.8-upgrade.md`, section
"OMC (NotifyNL Output Management Component)".
