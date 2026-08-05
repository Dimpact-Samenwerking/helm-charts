# ITA (Interne Taak Afhandeling) — Basics

## Management summary

ITA — Interne Taak Afhandeling ("internal task handling") — is the screen where
municipal employees pick up and complete internal tasks, such as "call this
citizen back", that are created during customer contact (for example via KISS)
and stored as *internetaken* in the customer-interaction registers. Employees
log in with their normal organisation account, see the tasks assigned to them
or their department/group, handle them, and the outcome is logged. A background
job runs every 15 minutes and sends e-mail reminders for tasks that have been
open too long. ITA needs a small PostgreSQL database, a Keycloak login client,
API connections to Open Klant, Objecten and Open Zaak, and an SMTP relay. Its
footprint is tiny: one small web pod plus a 15-minute cron job.

## What it is

- Upstream project: [Interne-Taak-Afhandeling](https://github.com/interne-taak-afhandeling)
  (Helm chart `internetaakafhandeling`, pulled from
  `oci://ghcr.io/interne-taak-afhandeling`, version **3.2.0**, aliased `ita`
  in `charts/podiumd/Chart.yaml`; vendored as
  `charts/podiumd/charts/internetaakafhandeling-3.2.0.tgz`).
- Images (tag `3.2.0`):
  - `ghcr.io/interne-taak-afhandeling/internetaakafhandeling.web`
  - `ghcr.io/interne-taak-afhandeling/internetaakafhandeling.poller`
- ASP.NET Core application (configuration via `ConnectionStrings__…` /
  `OIDC_…` environment variables from a chart-rendered ConfigMap + Secret).
- Role in PodiumD: task-handling front end on top of the Open Klant
  *klantinteracties* API (internetaken), the Objecten API (Afdeling / Groep /
  Medewerker / Activiteitenlog objects) and Open Zaak.
- Runtime components:
  - `ita-web` — Deployment, **replicas hardcoded to 1 in the subchart
    template** (upstream comment: OIDC data-protection keys are not persisted
    yet, so >1 replica breaks login). `ita.replicaCount` has no effect.
  - `ita-web-svc` — ClusterIP Service, port 80 → container port 8080.
    Health probes on `/healthz`.
  - `ita-poller` — CronJob, default schedule `*/15 * * * *`
    (`ita.poller.schedule`); sends reminder notifications for internetaken
    older than `poller.notification.hourThreshold` (default `-24` hours).
  - ConfigMap `ita-config`, Secret `ita-secrets`, appsettings ConfigMap —
    rendered by the subchart.
  - The subchart bundles a Bitnami PostgreSQL dependency; it is **disabled**
    (`ita.postgresql.enabled: false`) and must stay disabled — PodiumD uses an
    external database and Bitnami images are not allowed.

## Required resources

### Database

- **PostgreSQL: yes** — external (Azure Database for PostgreSQL Flexible
  Server in Dimpact environments). Database `ita`, user `ita`, port 5432.
- ITA does **not** use the usual `<component>` Secret (`DB_PASSWORD`) +
  ConfigMap (`DB_HOST`/`DB_NAME`/`DB_USER`) contract. Instead the connection
  details are plain chart values, filled per gemeente by the replacement
  scripts (`REP_…_REP` placeholders):

  ```yaml
  ita:
    database:
      host: "REP_ITA_DATABASE_HOST_REP"
      port: "5432"
      name: "ita"
      username: "ita"
      password: "REP_ITA_DATABASE_PASSWORD_REP"
  ```

  The subchart renders these into a full connection string in Secret
  `ita-secrets`, key `ConnectionStrings__DefaultConnection`.

### Storage

None. No PVC is rendered for ITA (the only PVC in the subchart belongs to the
disabled bundled PostgreSQL).

### Routing / exposure (NGINX Gateway Fabric)

- Public hostname: `<env>-ita.dimpact.nl` (e.g. `ontw-ita.dimpact.nl`).
- HTTPRoute `hr-ita-web-svc` (namespace `ingress-basic`, Gateway
  `public-gateway`) targets Service `ita-web-svc`. The HTTPRoute is created by
  the per-gemeente environment deployment, not by this chart.
- The subchart's own Kubernetes Ingress is disabled (`ita.ingress.enabled: false`).

### Other dependencies

- **Keycloak** — OIDC client `ita` ("Interne Taak Afhandeling") in the
  `podiumd` realm, provisioned by
  `templates/keycloak-podiumd-realm-config.yaml` with client roles
  `ITA_Gebruiker` and `ITA_Functioneel_Beheerder` and mappers for the `roles`
  and `samaccountname` claims. Values: `ita.web.oidc.authority`,
  `frontendUrl`, `clientId: ita`, `clientSecret`
  (`REP_ITA_OIDC_CLIENT_SECRET_REP`, must match the realm secret
  `KC_SECRET_ITA`), optional PKCE via `ita.web.oidc.pkceEnabled` (default
  `false`).
- **Open Klant** — klantinteracties API token:
  `ita.apiConnections.openKlant.baseUrl` + `apiKey`
  (`REP_OPENKLANT_CREDENTIALS_ITA_TOKEN_REP`).
- **Objecten** — API v2 token: `ita.apiConnections.object.baseUrl` + `apiKey`
  (`REP_OBJECTEN_CREDENTIALS_ITA_TOKEN_REP`).
- **Open Zaak** — client `ita` + secret:
  `ita.apiConnections.zaakSysteem.{baseUrl,clientId,key}`
  (`REP_OPENZAAK_CREDENTIALS_ITA_SECRET_REP`).
- **Objecttypes** — since the objecten/objecttypen merge, objecttypes are local
  data inside Objecten itself (no longer a separate Objecttypen API/component —
  see `docs/apps/objecten/openobject-migration.md`). Four objecttypes must exist and be
  referenced by URL + UUID (per-gemeente UUIDs come from the replacement
  scripts; the `create-required-objecttypen` job creates the types):
  - `ita.logboek` (Activiteitenlog), `ita.afdeling`, `ita.groep`,
    `ita.medewerker`.
  - `ita.medewerker` is **new and required since ITA 3.2.0** —
    `templates/validations.yaml` fails the render if `ita.medewerker.type`
    is empty while ITA is enabled.
- **SMTP** — `ita.smtp.{host,port,username,password,fromEmail,enableSsl}` for
  reminder mails; `ita.ita.baseUrl` is the public ITA URL used in e-mail
  deeplinks.
- No Redis, no ClamAV, no Elasticsearch, no RabbitMQ.
- **MI exports** — `ita` is in the default `mi.targets` list
  (`charts/podiumd/values.yaml`, `mi:` block): when `mi.enabled: true`, a
  weekly CronJob dumps the ITA database and uploads it via SFTP. The export
  job expects the per-app credential convention (Secret + ConfigMap named
  `ita` with `DB_PASSWORD` / `DB_HOST`/`DB_NAME`/`DB_USER`), which must be
  provided by the environment deployment since the subchart itself uses plain
  chart values for its DB connection.

## CPU and memory

Chart defaults (`charts/podiumd/values.yaml`):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| ita-web (`ita.web.resources`) | 100m | 128Mi | 200m | 256Mi |
| ita-poller CronJob (`ita.poller.resources`) | 50m | 128Mi | 100m | 256Mi |

Note: `docs/misc/resource-overview.md` still lists ITA resources as "—" with a
"chart limitation" warning saying `web.resources` cannot be set. That note
predates ITA 3.2.0: in the vendored 3.2.0 subchart, `web.resources` and
`poller.resources` are rendered straight into the container specs (branding
moved to its own `web.styling` block), and the podiumd values above set them.

Observed usage (2026-07-10): `ita-web` ~1m CPU / 97Mi on ontw and ~1m / 69Mi
on accp — comfortably within the defaults. The defaults are adequate for
production; no increase flagged.

## Integrating ITA as a new app

1. **Database** — create database `ita` and user `ita` on the environment's
   PostgreSQL server; set `ita.database.host` and `ita.database.password`
   (via the gemeente `REP_ITA_DATABASE_*_REP` replacements). Keep
   `ita.postgresql.enabled: false`.
2. **Enable and configure the chart** — `ita.enabled: true`; pin
   `ita.web.image.tag` / `ita.poller.image.tag` (chart default `3.2.0`); set
   `ita.ita.baseUrl` to the public URL (`https://<env>-ita.<domain>`).
3. **Keycloak** — set `ita.web.oidc.authority` to the realm URL,
   `frontendUrl` to the public ITA URL, and `clientSecret` to the value of the
   realm secret `KC_SECRET_ITA` (auto-generated by the chart if not supplied).
   Assign users the `ITA_Gebruiker` (and, for admins,
   `ITA_Functioneel_Beheerder`) client roles.
4. **API credentials** — create a token for ITA in Open Klant and Objecten,
   and an Autorisaties client `ita` + secret in Open Zaak; fill
   `ita.apiConnections.*`.
5. **Objecttypes** — make sure the Activiteitenlog, Afdeling, Groep and
   Medewerker objecttypes exist in Objecten (local data since the
   objecten/objecttypen merge; the `create-required-objecttypen` job creates
   them) and set the four
   `ita.{logboek,afdeling,groep,medewerker}` blocks with the
   environment-specific objecttype URLs/UUIDs. `ita.medewerker.type` is
   mandatory — the render fails without it.
6. **SMTP** — configure `ita.smtp.*` so reminder mails can be sent.
7. **DNS + HTTPRoute** — add `<env>-ita.<domain>` DNS and create HTTPRoute
   `hr-ita-web-svc` → Service `ita-web-svc` in the environment deployment.
8. **Verify** — log in via Keycloak at the public URL, check
   `GET /healthz` on the web pod, and confirm the `ita-poller` CronJob
   completes (`kubectl -n podiumd get cronjob,job | grep ita`).

## Related documents

None — this folder has only the BASICS file; no deep-dive documents exist yet
for this component.
