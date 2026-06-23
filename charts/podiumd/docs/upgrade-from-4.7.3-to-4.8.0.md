# Upgrade guide: PodiumD 4.7.3 → 4.8.0

> See the Confluence Releases page for the agreed application
> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Component versions

| Component   | App version | Helm chart |  |
|---|---|---|---|
| Open Inwoner        | 2.3.1 | 2.2.1 | optional action to enable ClamAv |
| KISS                | 2.2.3 | 2.2.3 | no action required |
| _contact-sync_        | 0.3.3 | --    | -- |
| ITA (.web, .poller) | 3.2.0 | 3.2.0 | **action required** |
| ClamAV (daemon)     | 1.5.2 | 3.7.1 | no action required |

> **`feature/podiumd-4.8.0-ontw-mayk-test-updates` overlay.** On top of the
> 4.8.0 targets above this branch carries two newer Maykin/upstream images for
> testing on the *ontwikkel* environment: Open Inwoner **2.3.0 → 2.3.1** (chart
> `2.2.0 → 2.2.1`) and the ClamAV daemon **1.4.4 → 1.5.2** (chart stays
> `3.7.1`). Both are detailed below.


## Changes

### Open Inwoner 2.1.2 → 2.3.1

PodiumD 4.8.0 bumps **Open Inwoner Platform (OIP)** from 2.1.2 to 2.3.0,
spanning two upstream releases (2.2.0 and 2.3.0). The
`feature/podiumd-4.8.0-ontw-mayk-test-updates` branch carries this one step
further to **2.3.1** (chart `2.2.1`).

- Helm chart `openinwoner` `2.1.3` → `2.2.1` (appVersion `2.3.1`) in
  `charts/podiumd/Chart.yaml`.
- Image tag pin `openinwoner.image.tag` `2.1.2` → `2.3.1` in
  `charts/podiumd/values.yaml`.

Image / digest: see [`docs/images/images-4.8.0.yaml`](images/images-4.8.0.yaml).
The ACR mirror name is `openinwoner` (no hyphen) — mirror the new `2.3.1`
tag and digest.

#### 2.3.0 → 2.3.1 (bug-fix patch)

2.3.1 (2026-06-11) is a **pure bug-fix patch** over 2.3.0 — no new settings, no
schema/migration changes, no security fixes, and no breaking changes. Chart
`openinwoner` `2.2.0` → `2.2.1` is itself only the appVersion bump to `2.3.1`
(no template changes). Notable fixes: logout-confirm page for users with
incomplete required fields, guarding against ZGW API errors during per-zaaktype
related-type imports, phone-number constraint handling when syncing users from
the Klanten API, SSD exception/template fixes, ensuring the `Site` exists before
uWSGI starts on fresh deployments, missing-`PartijIdentificator` handling in
`OpenKlant2Service`, and a CSP fix for an HTMX swap. **Action required: none.**

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

### ClamAV 1.4.4 → 1.5.2 (daemon, `ontw-mayk-test-updates` overlay)

The `feature/podiumd-4.8.0-ontw-mayk-test-updates` branch bumps the ClamAV
daemon image from `1.4.4` to `1.5.2` (image-tag override in
`charts/podiumd/values.yaml` under `clamav.image.tag`). The wiremind `clamav`
chart dependency **stays `3.7.1`** — that is already the latest published
version (its default `appVersion` is `1.4.3`, which PodiumD overrides via the
image tag), so no chart bump is available or needed.

1.5.x is an upstream **feature release**; 1.5.2 (the version pinned here) also
carries security fixes:

- **CVE-2026-20031** — HTML-parser error-handling bug that could cause a
  denial of service; fixed in 1.5.2.
- Crash fixes (invalid pointer alignment; JPEG infinite-loop; Windows
  `LeaveTemporaryFiles`/`TemporaryDirectory`), and `RUSTSEC-2026-0007`.

Compatibility notes for the 1.4 → 1.5 jump:

- **No breaking `clamd.conf` changes.** All options PodiumD sets in
  `clamav.clamdConfig` remain valid in 1.5.x; 1.5 only *adds* options
  (`JsonStoreHTMLURIs`, `JsonStorePDFURIs`, `FIPSCryptoHashLimits`,
  `CVDCertsDirectory`, and the `Enable*Command` clamd controls). Existing
  configs keep working unchanged.
- The clean-file scan cache moved from MD5 to **SHA2-256**. This is internal and
  rebuilt at runtime — irrelevant for the container, which starts with an empty
  cache.
- Virus signature databases (CVD) remain compatible; freshclam re-fetches on
  first start as usual.

#### Action required

**None.** On `helm upgrade` the `clamav` pod rolls onto `1.5.2`; freshclam
re-syncs the signature DB on startup (the PVC mount at `/var/lib/clamav` keeps
the bootstrap behaviour). Confirm the daemon comes up and answers on
`clamav:3310`. Open Inwoner virus scanning (if enabled, see above) keeps using
the same in-cluster `clamav` service — no client-side change.
