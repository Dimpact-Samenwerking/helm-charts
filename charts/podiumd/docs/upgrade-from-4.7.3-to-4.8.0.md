# Upgrade guide: PodiumD 4.7.3 → 4.8.0

> See the Confluence Releases page for the agreed application
> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Component versions

| Component   | App version | Helm chart |  |
|---|---|---|---|
| Open Inwoner        | 2.3.0 | 2.2.0 | optional action to enable ClamAv |
| Open Notificaties   | 1.16.0 | 2.0.0 | **action required** (RabbitMQ removed) |
| KISS                | 2.2.3 | 2.2.3 | no action required |
| _contact-sync_        | 0.3.3 | --    | -- |
| ITA (.web, .poller) | 3.2.0 | 3.2.0 | **action required** |
| brp-personen-mock   | 2.7.0-202606230850 | 1.2.9 | no action required |
| zaakbrug            | 1.26.14 | 2.3.27 | no action required |
| ZAC                 | 5.0.1 | 1.0.251 | **action required** |
| PABC                | 1.1.0 | 1.1.0 | **action required** (now enabled by default) |
| redis-operator      | v0.25.0 | -- | expect redis rolling restart |


## Changes

### Open Inwoner 2.1.2 → 2.3.0

PodiumD 4.8.0 bumps **Open Inwoner Platform (OIP)** from 2.1.2 to 2.3.0,
spanning two upstream releases (2.2.0 and 2.3.0).

- Helm chart `openinwoner` `2.1.3` → `2.2.0` (appVersion `2.3.0`) in
  `charts/podiumd/Chart.yaml`.
- Image tag pin `openinwoner.image.tag` `2.1.2` → `2.3.0` in
  `charts/podiumd/values.yaml`.

Image / digest: see [`docs/images/images-4.8.0.yaml`](images/images-4.8.0.yaml).
The ACR mirror name is `openinwoner` (no hyphen) — mirror the new `2.3.0`
tag and digest.

#### Django CMS v3 → v4 migration (2.2.0)

2.2.0 upgrades Django CMS from v3 to v4, which requires a one-time data
migration (`manage.py cms4_migration`). The chart runs this for us via an
init container, enabled by default:

```yaml
openinwoner:
  settings:
    cms4MigrationInitContainer: true
```

**Action required:** none for the upgrade itself — the migration runs
automatically on the first rollout to 2.3.0. Per upstream the migration
only needs to run once; to avoid re-running it on every pod restart, flip
this to `false` in a follow-up release once all environments have completed
the rollout. Tracked for 4.8.x.

Operational notes from upstream (admin/content workflow, not deploy-blocking):

- Static aliases are no longer editable via the page plugin menu — use the
  CMS toolbar instead.
- Page changes now require explicit publication ("Publish page changes").

#### ClamAV virus scanning (2.3.0) — opt-in

2.3.0 can scan uploaded files for viruses using ClamAV. PodiumD already
ships a ClamAV daemon (`clamav` dependency, service `clamav:3310`), and the
new Open Inwoner defaults line up with it out of the box
(`clamav_host: clamav`, `clamav_port: 3310`). Scanning is **off by default**
(`enable_virus_scan: false`), so the upgrade changes nothing until enabled.

**Action required (optional):** to turn scanning on, enable it in the Open
Inwoner admin under *Algemene configuratie* → **Virusscanner inschakelen**
(`enable_virus_scan`). The default host/port already point at the in-cluster
ClamAV service; no extra values or secrets are needed.

#### ZGW cache warmup + low-latency worker (2.3.0)

2.3.0 reworks ZGW zaken caching: the default cache timeout was raised from
60s to 300s upstream, and cache-seeding now runs on a dedicated low-latency
Celery worker. The chart creates this worker by default — PodiumD pins its
replica count and resources:

```yaml
openinwoner:
  settings:
    cacheZgwZakenTimeout: ""   # empty → app default (300s)
    cacheSeedingQueue: ""      # empty → low-latency worker queue
  lowLatencyWorker:
    replicaCount: 1
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
```

**Action required:** none — a new `openinwoner-low-latency-worker`
deployment appears after the upgrade (one extra pod). Budget for the small
additional resource request above.

#### BRP version (2.2.0)

The `BRP_VERSION` environment variable was replaced by an admin-configurable
field and is **auto-migrated** on upgrade. PodiumD's `settings.brpVersion`
override still works; no action required.

#### Elasticsearch (2.2.0)

2.2.0 adds optional HTTP basic auth for Elasticsearch and renames the chart
value `settings.elasticSearchHost` →
`settings.elasticsearch.{host,username,password}`. PodiumD uses the
in-chart Elasticsearch (`tags.elasticsearch: true`) and does **not** set
`elasticSearchHost`, so this rename does not affect PodiumD. No action
required.

**Action required (hosting / ACR mirror values):** if your environment
overrides `openinwoner.eck-elasticsearch.image` to pull from the ACR
mirror, it **must** include the explicit version tag, e.g.
`acrprodmgmt.azurecr.io/elasticsearch/elasticsearch:9.2.0` (matching
`eck-elasticsearch.version`). ECK does **not** append `:version` when
`spec.image` is set, so an untagged override resolves to `:latest`. The
mirror keeps two Elasticsearch majors in the **same** repository —
`:9.2.0` (Open Inwoner) and `:8.19.3` (Kiss) — and the 4.7+ image pipeline
no longer publishes `:latest`, so an untagged image relies on a stale,
non-deterministic tag that can resolve to ES 8.x and break Open Inwoner.
Pin the tag, and bump it together with `eck-elasticsearch.version` on
future Elasticsearch upgrades. Kiss needs no tag: it has no image override,
so the operator appends its `version` automatically.

The following environments were found with an **untagged**
`openinwoner.eck-elasticsearch.image` and must be pinned to `:9.2.0`
before upgrading (production environments first):

| Environment | Tier |
| ----------- | ---- |
| `bode/prod` | production |
| `gron/prod` | production |
| `zwol/prod` | production |
| `dim1/accp` | acceptance |
| `dimp/test` | test |
| `gene/test` | test |

All other environments already pin `:9.2.0`. After pinning, confirm the
running pod image with
`kubectl get pod <es-pod> -o jsonpath='{.spec.containers[*].image}'` — it
must read `…/elasticsearch/elasticsearch:9.2.0`, not `:latest`.


### Open Notificaties 1.13.1 → 2.0.0 (app 1.16.0) — RabbitMQ removed

Helm chart `opennotificaties` `1.13.1` → `2.0.0` (app `1.16.0`) in
`charts/podiumd/Chart.yaml`; image `opennotificaties.image.tag` `1.15.0` →
`1.16.0`. Mirror the new image (`docker.io/openzaak/open-notificaties:1.16.0`,
ACR name `openzaak/open-notificaties`) — see
[`docs/images/images-4.8.0.yaml`](images/images-4.8.0.yaml).

**The 2.0.0 chart removes the bundled RabbitMQ.** The Celery broker, result
backend and publish broker now all use the shared `redis-ha` cluster (db6):

```yaml
opennotificaties:
  settings:
    celery:
      brokerUrl: redis://redis-ha-master.podiumd.svc.cluster.local:6379/6
      publishBrokerUrl: redis://redis-ha-master.podiumd.svc.cluster.local:6379/6
    messageBroker:
      celeryResultBackend: redis://redis-ha-master.podiumd.svc.cluster.local:6379/6
```

(The chart defaults already set these; no gemeente override is needed.)

**Action required — RabbitMQ is destroyed on upgrade; undelivered tasks are
lost.** Sequence to avoid message loss and orphaned resources:

1. **Quiesce producers** (stop traffic that creates notifications) and let the
   Celery workers drain — confirm the RabbitMQ queues are empty **before**
   upgrading (the RabbitMQ StatefulSet is deleted by the 2.0.0 chart).
2. **Upgrade.** Workers reconnect to the Redis broker.
3. **Verify** the Celery workers are healthy on Redis (no
   `amqp://127.0.0.1:5672` connection attempts in the logs — that would mean a
   broker key is unset).
4. **Clean up orphaned resources.** Helm never deletes PVCs, and the RabbitMQ
   secret (guest/guest + erlang cookie) lingers:

   ```bash
   kubectl -n podiumd delete pvc  -l app.kubernetes.io/name=rabbitmq,app.kubernetes.io/instance=opennotificaties
   kubectl -n podiumd delete secret opennotificaties-rabbitmq
   ```

   Adjust names to match your release (`kubectl -n podiumd get pvc,secret | grep -i rabbitmq`).

### ITA 3.1.0 → 3.2.0

Helm chart `ita` (`internetaakafhandeling`) `3.1.0` → `3.2.0` in
`charts/podiumd/Chart.yaml`; `ita.web.image.tag` and `ita.poller.image.tag`
`3.1.0` → `3.2.0` in `charts/podiumd/values.yaml`.

#### Adds configuration for Medewerker-objecttype

ITA 3.2.0 introduces the **Medewerker-objecttype**, configured via a new
required `ita.medewerker` block. The chart ships a placeholder default
(`REP_CONTACT_MEDEWERKER_UUID_REP`), and `templates/validations.yaml` fails
the render if `ita.medewerker.type` is left blank while ITA is enabled.

**Action required:** every gemeente `podiumd.yml` must set the
environment-specific Medewerker objecttype URL:

```yaml
ita:
  ...
  medewerker:
    type: "https://<env>-objecttypen.<gemeente>.nl/api/v2/objecttypes/REP_CONTACT_MEDEWERKER_UUID_REP"
    # -- Version of the medewerker objecttype that is used, most likely: 1
    typeVersion: 1
```

### ZAC 4.7.2 → 5.0.1

PodiumD 4.8.0 (info.nl) bumps the **Zaakafhandelcomponent (ZAC)** from 4.7.2
to 5.0.1, a major-version jump.

- Helm chart `zaakafhandelcomponent` `1.0.228` → `1.0.251` (appVersion
  `5.0.1`) in `charts/podiumd/Chart.yaml`.
- Sub-image bumps in `charts/podiumd/values.yaml`:
  - `zac.nginx.image.tag` and all other `nginx-unprivileged` pins `1.30.2` → `1.31.1`
  - `zac.office_converter.image.tag` `8.31.0` → `8.33.0` (Gotenberg)
  - `zac.opa.image.tag` `1.15.2-static` → `1.17.1-static` (Open Policy Agent)
  - `zac.solr.busyBoxImage.tag` `1.37.0-glibc` → `1.38.0-glibc`

#### Breaking change: `brpApi.apiKey` restructured

`zac.brpApi.apiKey` changed from a plain string to an object with `header`
and `value` fields.

**Action required:** if your gemeente `podiumd.yml` overrides
`zac.brpApi.apiKey`, replace the string form:

```yaml
# before (4.7.x)
zac:
  brpApi:
    apiKey: "your-api-key"
```

with the new object form:

```yaml
# after (5.0.1)
zac:
  brpApi:
    apiKey:
      header: "x-api-key"
      value: "your-api-key"
```

If `zac.brpApi.apiKey` is not overridden in your gemeente file, no action
is required — the chart default already uses the new structure.

#### Breaking change: `featureFlags.pabcIntegration` removed

The `zac.featureFlags.pabcIntegration` key was removed in ZAC 5.x.

**Action required:** if your gemeente `podiumd.yml` sets
`zac.featureFlags.pabcIntegration: true` or `false`, remove that line. The
PABC integration is now controlled separately (see PABC chart values).

#### Breaking change: `protocollering` restructured

The BRP protocollering block was completely redesigned in ZAC 5.0.1. The
single `aanbieder` selector and implicit vendor defaults are replaced by an
explicit, field-per-dimension structure.

**Key renames and removals:**

| Old key (4.7.x) | New key (5.0.1) |
|---|---|
| `protocollering.aanbieder: "iConnect"` | `protocollering.enabled: true` + explicit fields |
| `protocollering.aanbieder: ""` | `protocollering.enabled: false` |
| `protocollering.verwerkingsregister` | `protocollering.verwerking.register` |

**New fields with no 4.7.x equivalent:** `logLevel` (at `brpApi` level),
`protocollering.systemUser`, `protocollering.originOin`, `protocollering.doelbinding.perZaaktype`,
`protocollering.doelbinding.header`, `protocollering.verwerking.header`,
`protocollering.gebruiker`, `protocollering.toepassing`.

**Action required:** if your gemeente `podiumd.yml` overrides any
`zac.brpApi.protocollering.*` keys, replace the old block with the
vendor-specific configuration from
[`docs/zac-brp-protocollering.md`](zac-brp-protocollering.md).

If protocollering was disabled (`aanbieder: ""`), set `enabled: false` and
remove the old keys — no further action is needed.

**Additional action required for iConnect environments:** disable the
`apiproxy.brp.toepassingHeaderName` injection — ZAC 5.0.1 now sends the
toepassing header directly via protocollering, so the api-proxy should no
longer own this header. Set `toepassingHeaderName: ""` in your gemeente file:

```yaml
apiproxy:
  locations:
    brp:
      toepassingHeaderName: ""
```

See [`docs/zac-brp-protocollering.md`](zac-brp-protocollering.md) for details.

### PABC now enabled by default

The chart default `pabc.enabled` flipped `false` → `true`, so the PABC
(PodiumD Autorisatie Beheer Component) subchart now deploys unless you opt out.
The bundled PostgreSQL stays **off** (`pabc.postgresql.enabled: false`), so PABC
needs an **external database**.

**Action required:** provision a database and set its credentials, or opt out.

```yaml
pabc:
  enabled: true            # chart default
  settings:
    database:
      host: "<pabc-db-host>"
      name: "pabc"
      username: "pabc"
      password: "<pabc-db-password>"
```

To keep the 4.7.x behaviour (PABC not deployed), set `pabc.enabled: false`.
Leaving PABC enabled without a reachable DB → PABC pods crashloop. (There is
no render-time guard for this — it surfaces at runtime.)

### Redis (redis-ha + operator)

4.8.0 bumps the Open Notificaties redis-operator `v0.24.0` → `v0.25.0` and adds
`app`/`service_name` labels to the `redis-ha` `RedisReplication` resource (Loki
attribution). Both change the pod template, so **expect a rolling restart of the
3-node redis-ha cluster** on upgrade, with a brief sentinel failover during the
rollout. No action required; schedule the upgrade accordingly.

### Open Beheer ↔ Objecttypen API token (IN-2345)

Open Beheer authenticates to the **Objecttypen API** with an API token.
Configure it on **both sides with the exact same secret**,
`REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP` (Key Vault `objecttypen-openbeheer-token`,
pipeline var `OBJECTTYPEN_OPENBEHEER_TOKEN`):

- **Objecttypen** — a `tokenauth` item granting Open Beheer the token
  (`token: {value_from: {env: objecttypen_openbeheer_token}}`).
- **Open Beheer** — the `zgw_consumers` `objecttypen-service` header:
  `header_value: "Token REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"`. The `Token `
  prefix is **required**.

IN-2345 fixed two recurring mistakes — **do not repeat**:

- **missing `Token ` prefix** on the Open Beheer header;
- **mismatched secret name** (`OPENBEHEER_CREDENTIALS_OBJECTTYPEN_TOKEN` vs
  `OBJECTTYPEN_OPENBEHEER_TOKEN`) — standardise on `OBJECTTYPEN_OPENBEHEER_TOKEN`.

**Action required:** only enable the objecttypen `openbeheer` tokenauth entry
when Open Beheer is **enabled and the secret is provisioned** — the
`objecttypen-config` Job validates the token strictly and **fails on an
unsubstituted `REP_..._REP` placeholder**. The chart `values.yaml` example
(objecttypen `tokenauth` + openbeheer `zgw_consumers`) already shows the correct
form; see also `openbeheer.md`.
