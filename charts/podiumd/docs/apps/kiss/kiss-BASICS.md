# KISS (Klant Interactie Servicesysteem) — Basics

## Management summary

KISS is the front-office tool for the municipality's customer contact centre (KCC). Agents use it to look up citizens and companies, log every contact ("contactmoment"), route follow-up questions to the right department, and search the knowledge base while a caller is on the line. It is part of PodiumD so that phone and counter contacts land in the same customer-interaction registers (Open Klant) as the online channels. To run, it needs a PostgreSQL database, a Keycloak login, its own 3-node Elasticsearch cluster with Enterprise Search for the knowledge base, and connections to Open Klant, Objecten and the BRP/KvK lookups. The web frontend itself is light (two small pods), but the Elasticsearch/Enterprise Search side it depends on takes roughly 9 GB of memory.

## What it is

- Upstream: [Klantinteractie-Servicesysteem](https://github.com/Klantinteractie-Servicesysteem) (KISS), developed by ICATT for Dimpact.
- Image: `ghcr.io/klantinteractie-servicesysteem/kiss-frontend`, tag `2.2.4` (`kiss.image.tag`). Sync jobs use `ghcr.io/klantinteractie-servicesysteem/kiss-elastic-sync`, tag `0.3.3` (`kiss.settings.syncJobs.image.tag`).
- Sub-chart: vendored `kiss-chart-2.2.4.tgz`; `nameOverride`/`fullnameOverride` are `contact`, so workloads and the service are named `contact`.
- Runtime components:
  - `contact-web` — the KISS frontend/backend web deployment, 2 replicas, service `contact` (port 80 → container 8080).
  - CronJobs (kiss-elastic-sync) that index content into Elasticsearch: `kennisbank`, `smoelenboek` (medewerkers), `vac`, plus optional `website[]` and `sharepoint[]` crawls — all under `kiss.settings.syncJobs`, default schedule `*/59 * * * *`.
  - `podiumd-adapter` — rendered by the umbrella chart (`templates/adapter-*.yaml`, values under `kiss.adapter`), image `ghcr.io/icatt-menselijk-digitaal/podiumd-adapter` tag `0.6.6`, service `podiumd-adapter`. Translates e-Suite APIs to the ZGW-style APIs KISS expects (only needed for e-Suite registers).
  - Elastic stack (separate values block `kiss-eck`, managed by the ECK operator): Elasticsearch `kiss-es-default` x3 (v8.19.3), Kibana `kiss-kb`, Enterprise Search `kiss-ent`. Documented in [../elastic/elastic-BASICS.md](../elastic/elastic-BASICS.md).

## Required resources

### Database

PostgreSQL: yes — a `kiss` database. KISS is an exception to the standard `<component>` Secret/ConfigMap contract: the connection is configured directly in values under `kiss.settings.database` (`host`, `port` 5432, `name`, `username`, `password`); the kiss sub-chart renders these into its own ConfigMap/Secret (`POSTGRES_PASSWORD`). The database and user are provisioned by the per-gemeente environment deployment.

### Storage

None for KISS itself — the frontend is stateless; state lives in PostgreSQL and Elasticsearch. The Elasticsearch data PVCs come from the ECK `volumeClaimTemplates` under `kiss-eck.eck-elasticsearch.nodeSets` (immutable once created — see the elastic docs).

### Routing / exposure (NGINX Gateway Fabric)

Public at `<env>-contact.dimpact.nl` (e.g. `ontw-contact.dimpact.nl`). HTTPRoute `hr-contact-nginx` on Gateway `public-gateway` (namespace `ingress-basic`, gatewayClass `nginx`), created by the per-gemeente environment deployment (not this chart), targeting the `contact` ClusterIP service. Kibana, Enterprise Search and the adapter stay cluster-internal.

### Other dependencies

- **Keycloak** — agent SSO via OIDC: `kiss.settings.oidc` (`authority`, `clientId: kiss`, `clientSecret`, optional `pkceEnabled` for PKCE S256, `medewerkerIdentificatie.claim: samaccountname`). `kiss.configuration.oidcUrl`/`oidcSecret` feed the Keycloak realm configuration for the client.
- **Elasticsearch + Enterprise Search** (from `kiss-eck`) — `kiss.settings.elastic` (`baseUrl`, `username: elastic`, `password`) and `kiss.settings.enterpriseSearch` (`baseUrl`, `publicApiKey`, `privateApiKey`, `engine: kiss-engine`) for knowledge-base search and content crawling.
- **Open Klant / zaaksysteem** — `kiss.settings.registers[]`: klantinteractie (Open Klant v2 `baseUrl` + `token`) and zaaksysteem (Open Zaak ZGW APIs with `clientId`/`clientSecret`, or e-Suite via the `podiumd-adapter`).
- **Objecten** (the objecten/objecttypen-merged app) — object registrations for `afdelingen`, `groepen`, `logboek`, and the syncJobs' `kennisbank`/`medewerkers`/`vac` object types (each needs `baseUrl`, `objectTypeUrl`, `token`).
- **BRP / KvK via api-proxy** — `kiss.settings.haalCentraal` (BRP Personen) and `kiss.settings.kvk` (`baseUrl`, `apiKey`, optional custom headers for brokers like iConnect).
- **SMTP** — `kiss.settings.email` for the feedback mail (`kiss.settings.feedback.emailFrom`/`emailTo`).
- **Management information** — `kiss.settings.managementInformatie.apiKey` protects the MI export endpoint.
- No Redis and no ClamAV dependency.

## CPU and memory

Chart defaults (values.yaml / resource-overview.md):

| Container | CPU request | Mem request | CPU limit | Mem limit | Values key |
|-----------|-------------|-------------|-----------|-----------|------------|
| kiss (contact-web, x2) | 100m | 256Mi | not set (burstable) | not set (burstable) | `kiss.resources` |
| adapter (podiumd-adapter) | 10m | 100Mi | not set (burstable) | not set (burstable) | `kiss.adapter.resources` |
| syncJob: kennisbank | 50m | 128Mi | — | — | `kiss.settings.syncJobs.kennisbank.resources` |
| syncJob: smoelenboek (medewerkers) | 50m | 128Mi | — | — | `kiss.settings.syncJobs.medewerkers.resources` |
| syncJob: vac | 50m | 128Mi | — | — | `kiss.settings.syncJobs.vac.resources` |
| syncJob: website / sharepoint | — | — | — | — | `kiss.settings.syncJobs.website[*]` / `sharepoint[*]` `.resources` (default `{}`) |

The Elastic side (defaults set by the ECK operator: ES 2Gi/2Gi x3, Kibana 1Gi, Enterprise Search 4Gi; no CPU requests) is covered in [../elastic/elastic-BASICS.md](../elastic/elastic-BASICS.md) — resource-overview.md flags it "Increase for production" (ES `500m/4Gi` request=limit, Kibana `200m/1Gi`, Enterprise Search `500m/4Gi`).

**Observed usage** (kubectl top, 2026-07-10): `contact-web` x2 uses ~1m CPU and 105–182Mi (ontw) / 111–113Mi (accp) per pod — the 256Mi request is adequate. `podiumd-adapter` idles at 1m / 79Mi (ontw) and 131Mi (accp). The heavy consumers are the Elastic components: `kiss-es-default` x3 at ~1.7Gi each, `kiss-ent` ~3.5Gi, `kiss-kb` ~0.6Gi. Sizing: keep the frontend defaults; budget ~9Gi across nodes for the KISS Elastic stack and apply the production request/limit recommendations above. Add a PDB with `minAvailable: 1` for `contact-web` (ECK manages the ES PDB, `kiss-es-default` `minAvailable: 1`).

## Integrating KISS as a new app

1. **Provision the database**: create the `kiss` PostgreSQL database and user on the environment's PostgreSQL Flexible Server, and set `kiss.settings.database.host/name/username/password` in the environment values (secret value via the environment's secret injection, not plaintext in git).
2. **Enable the Elastic stack**: ensure `eck-operator.enabled: true` and `kiss-eck.enabled: true` (Elasticsearch x3, Kibana, Enterprise Search, all v8.19.3). Follow [../elastic/elastic-BASICS.md](../elastic/elastic-BASICS.md); note `volumeClaimTemplates` is immutable after creation.
3. **Enable KISS**: `kiss.enabled: true`, pin `kiss.image.tag`, and fill `kiss.settings.elastic` (baseUrl + `elastic` user password from the ECK-generated secret) and `kiss.settings.enterpriseSearch` (baseUrl + API keys generated in Enterprise Search, engine `kiss-engine`).
4. **Keycloak client**: create/confirm the `kiss` client in the `podiumd` realm; set `kiss.settings.oidc.authority`, `clientSecret` and, if the client enforces PKCE, `pkceEnabled: true`. Set `kiss.configuration.oidcUrl` to the public URL (`https://<env>-contact.dimpact.nl`) and `oidcSecret` to the same client secret. Map the `samaccountname` claim for `medewerkerIdentificatie`.
5. **Registers**: configure `kiss.settings.registers[]` — for the PodiumD stack: Open Klant klantinteracties `baseUrl` + token and Open Zaak `catalogi`/`zaken`/`documenten` base URLs with a `kiss` client id/secret registered in Open Zaak's Autorisaties admin. For e-Suite, deploy the adapter instead: fill `kiss.adapter` (`baseUrl`, `clientId: kiss_intern`, `secret`, `esuite.*`, `objecten.*` UUIDs — collapsed from the former separate `objecten.*`/`objecttypen.*` groups, see `docs/apps/objecten/openobject-migration.md` H.7) and point the register URLs at `http://podiumd-adapter.<namespace>.svc.cluster.local`.
6. **Objecten registrations**: create the object types (afdeling, groep, kennisartikel, medewerker, vac, logboek) and grant a token in Objecten (local objecttypes since the objecten/objecttypen merge — no separate Objecttypen component), and fill `kiss.settings.afdelingen/groepen/logboek` and the `syncJobs.kennisbank/medewerkers/vac` blocks (`baseUrl`, `objectTypeUrl`, `token`).
7. **External lookups**: set `kiss.settings.haalCentraal` (BRP) and `kiss.settings.kvk` `baseUrl`/`apiKey` — in Dimpact environments these point at the cluster-internal api-proxy.
8. **SMTP / feedback**: set `kiss.settings.email.*` and `kiss.settings.feedback.emailFrom/emailTo`.
9. **DNS + HTTPRoute**: add `<env>-contact.dimpact.nl` DNS and have the environment deployment (ADO `ExternalsPodiumD`) create HTTPRoute `hr-contact-nginx` on `public-gateway` targeting service `contact`.
10. **Verify**: log in at `https://<env>-contact.dimpact.nl` via Keycloak; search a (test) citizen via BRP and a company via KvK; log a contactmoment and confirm it appears in Open Klant; check the sync CronJobs completed (`kubectl get jobs -n podiumd | grep -E 'kennisbank|smoelenboek|vac'`) and that knowledge-base search returns results; review `kubectl logs -n podiumd deploy/contact-web` for errors.

## Related documents

- [migrating-to-kiss-2.md](migrating-to-kiss-2.md) — migrating per-gemeente values to the strict KISS 2.x chart schema (PodiumD 4.5+), including the `scripts/migrate-kiss-schema.py` helper.
- [../elastic/elastic-BASICS.md](../elastic/elastic-BASICS.md) — the ECK-managed Elasticsearch / Kibana / Enterprise Search stack KISS depends on.
- [../elastic/migrating-to-eck-stack.md](../elastic/migrating-to-eck-stack.md) — migration from the legacy kiss-elastic chart to the ECK-managed stack.
