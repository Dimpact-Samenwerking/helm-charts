# Upgrade guide: PodiumD 4.7.3 → 4.8.0

> See the Confluence Releases page for the agreed application
> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Component versions

| Component   | App version | Helm chart |  |
|---|---|---|---|
| Open Inwoner        | 2.3.0 | 2.2.0 | optional action to enable ClamAv |
| KISS                | 2.2.3 | 2.2.3 | no action required |
| _contact-sync_        | 0.3.3 | --    | -- |
| ITA (.web, .poller) | 3.2.0 | 3.2.0 | **action required** |
| brp-personen-mock   | 2.7.0-202606230850 | 1.2.9 | no action required |
| zaakbrug            | 1.26.14 | 2.3.27 | no action required |
| ZAC                 | 5.0.1 | 1.0.251 | **action required** |


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


### ITA 3.1.0 > 3.2.1

#### Adds configuration for Medewerker-objecttype

**Action required:** 

ITA 3.2.1 introduces two new, required helm values, for the Medewerker-object. 
This means all gemeentelijke podium.yml-files must be changed to include the below:

```yaml
ita:
  ...
  medewerker:
    # -- Version of the medewerker objecttype that is used, most likely: 1 
    type: "https://<env>-objecttypen.<gemeente>.nl/api/v2/objecttypes/REP_CONTACT_MEDEWERKER_UUID_REP"
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
