# `openobject` chart — inspection & migration notes

Inspected `maykinmedia/openobject` chart version **1.1.1** (appVersion **4.1.0**,
the latest chart tagged with an app-version 4.x), pulled via
`helm pull maykinmedia/openobject --version 1.1.1`.

## What it is

As of **Open Object 4.0**, Maykin merged the **Objecttypes API** and
**Objects API** into a single application. The `openobject` chart is the
successor to the `objecten` chart (and effectively replaces `objecttypen` as
a separate chart too) — see section C below for the values old-key → new-key
mapping between the two former subcharts, and
`charts/podiumd/docs/apps/objecten/objecten-BASICS.md` for the post-migration
app shape. **Design decision**: `objecten` replaces `objecttypen`, not the
other way around — every values key, Kubernetes object name, DNS name, and
the public hostname keep the name `objecten`; nothing user-facing is renamed
to `openobject`. `docs/apps/openobject/openobject-BASICS.md` was not created;
`objecten-BASICS.md` was updated in place instead.

From the chart's own README:

> This chart is only compatible with **Open Object 4.0.0 and higher**.
> If you are running an older version, use the `objecten` chart instead.

Jumping straight from an older `objects-api` to `openobject` is **not**
supported — see section A below for the concrete precondition sequence.

### Where PodiumD currently stands

| Chart (in `charts/podiumd/Chart.yaml`) | Pinned chart version | App version |
|---|---|---|
| `objecten` | 2.12.1 | **3.6.2** |
| `objecttypen` | 1.6.1 | 3.4.0 |

**The A.1 precondition bump has already happened** (to chart 2.12.1,
appVersion 3.6.2 — one patch further than the 3.6.1 minimum) — including
the `resultBackendl`→`resultBackend` key rename already being correctly in
place in `values.yaml`. That's a *code* fact, verifiable from this
checkout. **A.2 (running `import_objecttypes` per environment) and A.3
(confirming the gate) are runtime actions against live deployments — their
status is unknown here and must be verified per environment separately; a
code checkout cannot confirm them.** Don't treat A.1's completion as
implying A.2/A.3 are also done. `objecttypen` has no further role once the
merge happens; its object-type data moves in via the import migration
described in A.6 below.

The `openobject` chart itself is at the latest available version, **1.1.1**
(appVersion 4.1.0), as of this check.

## Chart structure

Same Bitnami-based skeleton as today's `objecten` chart:

- Dependencies: `common` (2.31.4) and `redis` (22.0.1), both from
  `https://charts.bitnami.com/bitnami` — the bundled `redis` subchart's own
  image moved from Bitnami's to the official `docker.io/redis` (pinned
  `8.0`); irrelevant to PodiumD either way since `tags.redis: false` keeps
  using the shared `redis-ha` cluster instead (see C).
- Templates: `deployment.yaml`, `configmap.yaml`/`configmap-celery.yaml`,
  `configuration-data.yaml`/`configuration-secrets.yaml` (django-setup-configuration
  pattern), `job-config.yaml`, `azurekeyvaultsecrets.yaml`, `hpa.yaml`, `pdb.yaml`,
  `pvc.yaml`, `ingress.yaml`, `secret.yaml`, `service.yaml`, `serviceaccount.yaml`.
- Worker/flower support for Celery, same as `objecten` today.
- Image: **`maykinmedia/open-object`** (the old chart uses `maykinmedia/objects-api`).

## Chart version history (from `CHANGELOG.md`)

| Chart version | Date | Notes |
|---|---|---|
| 1.1.1 | 2026-06-26 | Fixed inconsistent naming of configuration secret |
| 1.1.0 | 2026-06-24 | Fixed the `existingConfigurationSecret` value name |
| 1.0.0 | 2026-06-19 | Bumped app version to 4.1.0; `siteDomain` now required; fixed duplicate volumes (#402); added missing `django_setup_configuration` values, removed `sites_config` and the `objecttypes-api` zgw_consumers entry (#404); added deprecation warning to the `objecten` chart (#405) |
| 0.1.0 | 2026-05-28 | First chart release of Open Object 4.0, combining Objecttypes API and Objects API into a single application |

## Migration checklist: `objecten` + `objecttypen` → `openobject` 1.1.1

Verified against the actual current content of `charts/podiumd` (not just the
chart's own docs).

### A. Precondition / data-migration steps (must happen first, per environment)

1. Bump the `objecten` dependency in `charts/podiumd/Chart.yaml` from
   `2.12.0` → `2.12.1` (appVersion `3.6.0` → `3.6.1`) as a **separate prior
   release/PR**. Update `objecten.image.tag` in `values.yaml` accordingly.
   **This bump is not just a version/tag change** — diffing the two chart
   versions directly (`helm pull maykinmedia/objecten --version 2.12.0` vs.
   `2.12.1`) shows `templates/configmap.yaml` itself changed: it now reads
   `.Values.settings.celery.resultBackend` instead of the old
   `.Values.settings.celery.resultBackendl` (typo fix, one release earlier
   than expected — previously this doc only flagged this rename as part of
   the later `openobject` swap in section C). This PR must rename it to
   `resultBackend` in the same change, or `CELERY_RESULT_BACKEND` silently
   reverts to empty for `objecten` as soon as chart 2.12.1 renders, before
   `openobject` is ever touched. No other file differs between the two
   chart versions (`Chart.yaml` and `README.md` differ only in version
   metadata).

   **Status in this checkout**: already done — chart 2.12.1/appVersion
   **3.6.2** (one patch past the 3.6.1 minimum), with `resultBackend`
   already correctly named in `values.yaml`. Skip straight to A.2.

   **Important: "done" above means only this step (A.1, the chart-version
   bump) — it says nothing about A.2/A.3.** A.1 is a *code* change,
   verifiable from a git checkout (chart version + key name in
   `values.yaml`). A.2 (actually running `import_objecttypes` against each
   live gemeente environment) and A.3 (confirming
   `check_for_external_objecttypes` prints `OK` there) are *runtime*
   actions against live deployments/databases — nothing in this repo can
   confirm whether they've happened for any given environment. Having the
   right chart version pinned is a **prerequisite** for running A.2, not
   evidence that A.2/A.3 have been done. Treat A.2/A.3 as **unknown, must
   be verified per environment separately**, regardless of which branch or
   checkout you're looking at — same "outside this repo" caveat as the
   per-gemeente config audit and running-appVersion-check TODO items below.
2. Run the concrete objecttypen-import precondition sequence per
   environment before touching `openobject` at all — see A.6 for the exact
   steps and the gating command.
3. Only after **all** environments have completed A.6's sequence does the
   `openobject` swap (steps B–E below) get rolled out.
4. **Resolved** (see A.6): `openobject` reuses the existing `objecten`
   Postgres database — the objecttype-import command is an API-driven copy
   into `objecten`'s own tables, not a Postgres-level schema merge, so no
   fresh database provisioning or export/import is needed. **`objecttypen`
   (the running service, not just its database) must stay live and serving
   requests until the actual `openobject` cutover** — per the official
   migration guide, `objecten` 3.6.1 still depends on it for live objecttype
   resolution even after the import completes; only decommission it once
   the `openobject` swap itself has happened, not right after A.6's import
   step.
5. Plan PVC/media continuity: set `persistence.existingClaim` to the
   existing Azure Files claim (e.g. `objecten`) so file storage carries over
   instead of the new deployment starting with empty media.
6. Upstream objecttypen data-migration mechanics — pulled the actual source
   of the two Django management commands involved, from
   `maykinmedia/open-object` (`src/objects/core/management/commands/`):

   **`import_objecttypes <service_slug>`** — ships in `objects-api`/`objecten`
   **3.6.0+**:
   - Takes one required arg: `service_slug` — the `zgw_consumers` `Service`
     identifier/slug already configured to point at the external Objecttypen
     API (exactly the commented `objecttypes-api` entry already present in
     `objecten.configuration.data` in `values.yaml`).
   - Requires the target Objecttypes API to report version `>= 2.2.2` via a
     response header — the code comment notes objecttypes-api **app**
     version 3.4.0 is what added that header. PodiumD's pinned `objecttypen`
     chart is already appVersion 3.4.0, so **no bump needed on the
     objecttypen side**.
   - Fetches every objecttype and its versions over HTTP and **bulk-upserts
     them into the calling app's own `ObjectType`/`ObjectTypeVersion`
     tables**, matching on `uuid` (`unique_fields=["uuid"]`), marking each
     row `is_imported=True`. Runs inside one `@transaction.atomic` block.
   - **This is an API-driven copy, not a database dump/restore or schema
     merge.** It runs against the `objecten` app (already upgraded to 3.6.1)
     while `objecttypen` is still live, pulling data in over the
     already-configured `zgw_consumers` service.

   **`check_for_external_objecttypes`** (pre-flight gate) — scans the local
   `ObjectType` table for any row where `is_imported` is not `True`;
   hard-fails (`CommandError`, listing offending UUIDs) if any exist. Open
   Object 4.0 "only allows local objecttypes" (per the upstream changelog),
   so running this until it prints `OK` is the concrete signal that
   migration is complete and it's safe to cut over.

   **Concrete precondition sequence**: (1) ensure a `zgw_consumers`
   `Service` pointing at `objecttypen` exists in `objecten`'s config — its
   identifier/slug is visible in the Django admin under
   *Configuration > Services* if not already known from `values.yaml`, (2)
   run `import_objecttypes <that-service-slug>` on the upgraded (3.6.1)
   `objecten` app per environment, (3) run `check_for_external_objecttypes`
   and confirm `OK` output, (4) only then proceed to the `openobject` chart
   swap. Upstream's own example invocation (`docs/manual/migration.rst`):
   `src/manage.py import_objecttypes objecttypes-api` — worth noting the
   example service identifier there, `objecttypes-api`, is the exact same
   identifier already named in PodiumD's own commented `zgw_consumers`
   example in `values.yaml`, confirming the intended slug to use.

   **Found the actual dedicated migration guide** (`docs/manual/migration.rst`
   on `maykinmedia/open-object` — distinct from, and more detailed than, the
   changelog entries quoted above) and it adds several operationally
   important details not previously captured here:

   - **The 4.0.0 container itself enforces this at startup, not just an
     optional pre-flight check**: "if there are remaining external
     objecttypes the container will fail during startup (and block any
     database schema changes introduced in 4.0.0) and you will need to roll
     back to 3.6.1." So skipping/incompletely running the precondition
     sequence isn't a soft risk caught by a manual check — it's a hard
     startup failure on the `openobject` cutover itself, and recovering
     means **rolling the release back to `objecten` 3.6.1**, fixing the
     remaining unimported objecttypes, and retrying the cutover. Add this
     rollback path to the actual rollout runbook, not just the precondition
     checklist.
   - **Stale/deleted upstream objecttypes are a real edge case**: "Objecttypen
     references that exist in the Objects API but have been removed from
     the external Objecttypes API should be removed since they cannot be
     imported." If `check_for_external_objecttypes` still lists offending
     UUIDs after running `import_objecttypes`, check whether those
     objecttypes still exist in the live `objecttypen` instance — if they've
     already been deleted there, `import_objecttypes` can never resolve
     them, and the stale `ObjectType` rows must be removed manually from
     `objecten`'s own database instead.
   - **`objecttypen` must stay live through the entire window, not just
     until the import completes**: "after running this import command, the
     objecttypes API is still being used in Objects API version <4.0.0, the
     command only fetches and imports the data to prepare for the 4.0
     upgrade." This **revises** the earlier "decommission `objecttypen`'s
     database as-is after import" framing below — the `objecttypen`
     *service* (not just its database) must keep running and serving
     requests normally until the moment of the actual `openobject` chart
     swap, since `objecten` 3.6.1 still depends on it for live objecttype
     resolution in the interim. Only decommission it after cutover, not
     right after the import step.
   - Minor, low-priority nuance not applicable to PodiumD: the guide notes
     that instances tracking the Docker `latest` tag (rather than a pinned
     version) can jump straight to 4.0.0 without the startup check
     triggering, fixable by running `import_objecttypes` in 4.0.0 itself.
     Irrelevant here since PodiumD pins exact image tags/digests, never
     `latest`.

   **Consequences**: existing `Object` records do not need rewriting — the
   migration guide confirms Open Object 4.0 "ignores the domain used in
   objecttype URLs and only checks if an objecttype exists for that UUID,"
   so Objects referencing the old `objecttypen.<domain>/...` URLs keep
   resolving once the UUID is imported.

7. Upstream objecten (Objects API) own data-migration mechanics — unlike
   objecttypen's data (an API-driven copy, see A.6), Objecten's own data
   moves via **ordinary Django schema migrations bundled into each app
   release** — no separate command to run. Pulled from `CHANGELOG.rst` on
   `maykinmedia/open-object`, versions 3.2.0 through 4.1.0 (the span
   PodiumD needs to cross):

   | Version | Date | Migration-relevant change |
   |---|---|---|
   | 3.2.0 | 2025-09-16 | Adds a GIN index on `ObjectRecord.data` (`data_attrs`) — created concurrently, upstream warns it "might take some time (several minutes)" and can occasionally slow writes |
   | 3.3.0 | 2025-10-06 | Adds `created_on`/`modified_on` to `Object`/`ObjectRecord` — lightweight |
   | **3.4.0** | 2025-10-28 | **Heavy migration** — denormalizes `object_type` onto `ObjectRecord` (adds `_object_type`) to avoid JOINs. Upstream's own benchmark: **3.8 million `ObjectRecord`s → ~45 minutes**; official guidance is "40 minutes to 1.5 hours." Handles concurrently-created records if the API stays up during migration, but flags potential issues under constant write load |
   | 3.5.0 | 2025-12-01 | `mozilla-django-oidc-db` bumped to 1.1.1 — OIDC config data format splits into separate `OIDCProvider`/`OIDCClient` records |
   | 3.6.0 | 2026-02-06 | Adds `ObjectType`/`ObjectTypeVersion` models + `import_objecttypes` command (A.6); adds a `references` field on `ObjectRecord` linking objects to zaken; removes `linkable_to_zaken` from `ObjectType` |
   | **4.0.0** | 2026-04-13 | **Major release, breaking changes** (see below) |
   | 4.0.1 / 4.0.2 / 4.1.0 | 2026-05-22 / 2026-07-16 / 2026-06-17 | Minor fixes/security patch; no further data migrations of note |

   **PodiumD's current pin is appVersion 3.6.0** — meaning the
   3.2.0/3.4.0/3.5.0 migrations above have *already run* for any environment
   that has kept the chart current. Worth explicitly confirming
   per-gemeente: that production is actually running ≥3.4.0 (not just that
   the chart is pinned there), since that's the one genuinely slow
   migration in the list.

   **4.0.0 breaking changes** (the app-level cutover itself, not the
   objecttypen import), from `CHANGELOG.rst`:
   - Combines Objects API + Objecttypes API into Open Object, **local
     objecttypes only** (the change this whole migration is about).
   - Removes `SitesConfigurationStep`; removes the `sites_config` namespace
     from `setup_configuration` data (reflected in section C).
   - **Removes the `service_identifier` attribute from
     `ObjectTypesConfigurationStep`** entirely — objecttypes are local now,
     no service reference possible (reflected in section C).
   - **Removes `fields`/`use_fields` from `TokenAuthConfigurationStep`**
     (reflected in section C) — check any per-gemeente override using
     these before the swap.
   - Env var renames: `ENABLE_STRUCTLOG_REQUESTS`→`LOG_REQUESTS`,
     `LOG_REQUESTS`→`LOG_OUTGOING_REQUESTS`.
   - **Bug fix with real behavioral consequences**: `CELERY_BROKER_URL` is
     now actually used for the Celery broker — previously the app
     **incorrectly wired the broker-url setting to
     `CELERY_RESULT_BACKEND`**. Chart values may look unchanged across the
     upgrade but the runtime Celery wiring changes; smoke-test task
     processing after cutover, don't assume a values diff alone tells the
     whole story.
   - Removes `django.contrib.sites` entirely; `SITE_DOMAIN` now required
     (reflected in section C).
   - Removes deprecated API schema URL redirects.
   - Error response format changes to `application/problem+json` — any
     downstream client parsing error response bodies (zac/kiss/ita/omc)
     should be checked against this, not just happy-path requests.
   - New feature: import-export for Objecttypes **with optional UUID
     retention** — an alternative/complementary path to
     `import_objecttypes`, worth knowing about if the API-driven copy
     proves impractical for any environment.
   - Bugfix: 500 error on duplicate UUID when creating objects.

   **Consequences**: Objecten's own upgrade path is standard
   Django-migration risk (mostly already absorbed at the current 3.6.0
   pin), **not** a second data-copy operation — the real per-environment
   risk is entirely in the 4.0.0 breaking-changes list above. Add an
   explicit Celery smoke test to the rollout plan (the broker/result-backend
   wiring bug fix above, not to be confused with the uwsgi tuning question
   in H.6), and an explicit check of any per-gemeente `configuration.data`
   overrides for
   `objecttypes.items[].service_identifier` and
   `tokenauth.items[].{fields,use_fields}` before the swap — these will be
   silently ignored/rejected post-upgrade, not just deprecated.

### B. `Chart.yaml` change

Replace:
```yaml
  - name: objecten
    version: 2.12.0
    repository: "@maykinmedia"
    condition: objecten.enabled
  - name: objecttypen
    version: 1.6.1
    repository: "@maykinmedia"
    condition: objecttypen.enabled
```
with a single entry, **aliased per the H.1 resolution** so the values key
stays `objecten:`:
```yaml
  - name: openobject
    version: 1.1.1
    repository: "@maykinmedia"
    condition: objecten.enabled
    alias: objecten
```
Run `/helm-deps` afterward to refresh `Chart.lock`/`charts/podiumd/charts/`.
Note the `condition` also moves to `objecten.enabled` — Helm evaluates
dependency conditions against the aliased key, not the chart's own name.

### C. `values.yaml` restructuring

Delete the `objecttypen:` block; keep the `objecten:` block (now backed by
the `openobject` chart via the alias in B) and restructure its contents.
**Must also set both `objecten.nameOverride: objecten` and
`objecten.fullnameOverride: objecten`** explicitly (see H.1) — neither is
the chart's default, and `fullnameOverride` alone leaves the config Job and
every pod's `app.kubernetes.io/name` label reading `openobject`. Key
mapping / gotchas:

| Old key | New key | Notes |
|---|---|---|
| `objecten.configuration.*` | `configuration.*` | 1:1 shape, but merge in objecttypen's tokenauth items too (openformulieren/openbeheer/ITA object-type tokens) — it's one app's config data now |
| `objecttypen.configuration.token` (plain admin bearer token) | *(no direct equivalent)* | Must become a `tokenauth` item in `configuration.data`/`.secrets` instead |
| `objecten.settings.allowedHosts` / `objecttypen.settings.allowedHosts` | `settings.allowedHosts` (single) | **H.2 resolved**: keeps objecten's existing hostname |
| `objecten.settings.cache.*` (redis DB1) + `objecttypen.settings.cache.*` (redis DB0) | `settings.cache.*` (single set) | **Two DB indices collapse into one** — pick one, free the other, update `docs/apps/redis/redis-ha-databases.md` |
| `objecten.settings.celery.resultBackendl` (typo) | `settings.celery.resultBackend` | Key name changes, not just value — **and** upstream 4.0.0 fixes a bug where `CELERY_BROKER_URL` was actually wired to `CELERY_RESULT_BACKEND`; runtime Celery behavior changes on upgrade even if values are otherwise unchanged, smoke-test after cutover |
| `objecten.settings.logRequests` (was `ENABLE_STRUCTLOG_REQUESTS`) / `objecten.settings.logOutgoingRequests` (was `LOG_REQUESTS`) | `settings.logRequests` / `settings.logOutgoingRequests` | Upstream 4.0.0 renames both env vars (`ENABLE_STRUCTLOG_REQUESTS`→`LOG_REQUESTS`, `LOG_REQUESTS`→`LOG_OUTGOING_REQUESTS`) — the two chart-level values keys already exist under this name in `openobject`'s `values.yaml`, but confirm the *old* `objecten` chart's `settings.logRequests`/`logOutgoingRequests` (if set) actually map to the pre-rename env vars correctly before assuming a straight carryover |
| `objecttypen.configuration.data` → `objecttypes_config` → `objecttypes.items[].service_identifier` | *(field removed)* | Upstream 4.0.0 removes the `service_identifier` attribute from `ObjectTypesConfigurationStep` entirely — objecttypes are local now, no service reference possible; drop this field, don't just repoint it |
| `configuration.data` → `tokenauth.items[].fields` / `.use_fields` | *(fields removed)* | Upstream 4.0.0 removes `fields`/`use_fields` from `TokenAuthConfigurationStep` — check any per-gemeente override using these before the swap |
| `objecten.otel.disabled` (top-level) | `settings.otel.disabled` (nested) | **Correction**: not actually a merge-driven change — the chart's `configmap.yaml` (both 2.12.1 and openobject) has always read `settings.otel.disabled`; base `values.yaml`'s top-level `objecten.otel.*` was already dead/inert pre-migration. Fixed as a side effect of this diff; already correctly targeted by `values-enable-observability.yaml`, which needed no change |
| `objecten.persistence.{size,existingClaim,storageClassName}` | `persistence.*` | Set `existingClaim` to reuse the existing PVC (see A.5); also new `mediaMountSubpath` defaults to `openobject/media` (was `objecten/media`) — override to avoid moving the media path unintentionally |
| `objecten.persistentVolume.volumeAttributeShareName`/`storageClassName` | unchanged, still `objecten.persistentVolume.*` | Podiumd-only keys consumed by `templates/objecten-storage.yaml` — no rename needed thanks to the H.1 alias decision |
| `objecten.image` / `objecttypen.image` (`objects-api`/`objecttypes-api`) | `image.repository: maykinmedia/open-object`, `image.tag` | New image entirely; pin digest via `/verify-image-digests` |
| `objecten.resources` / `objecttypen.resources` | `resources` | Two budgets collapse into one Deployment's resources |
| `objecten.worker.*` | `worker.*` | 1:1 plus new `concurrency` field; objecttypen never had a worker so nothing lost there |
| `objecten.nameOverride`/`fullnameOverride: objecten`, `objecttypen.nameOverride`/`fullnameOverride: objecttypen` | **both** `nameOverride: objecten` **and** `fullnameOverride: objecten` | **Resolved, H.1** — both must be set explicitly (neither is the chart's default); `fullnameOverride` alone is not enough, see H.1 for the config-job/selector-label gotcha |
| `objecten.flower.enabled: false` | `flower.enabled` (chart default `true`) | Must explicitly set `false` to match current behavior |
| `objecten.tags.redis: false` / `objecttypen.tags.redis: false` | `tags.redis: false` | Confirmed same override pattern still works to keep using the shared `redis-ha` cluster instead of openobject's bundled redis subchart |
| `objecttypen.settings.database.*` vs `objecten`'s external Secret/ConfigMap convention | `settings.database.*` (single) | Two different provisioning conventions collapse into one — confirmed the merged chart follows `objecttypen`'s convention (renders its own ConfigMap/Secret from values), not `objecten`'s current external-Secret convention — see `objecten-BASICS.md` |
| `objecttypen.create_required_objecttypen_job.*` | *(no subchart equivalent)* | Podiumd-owned, stays as a custom key unrelated to the subchart schema |
| — | `settings.siteDomain` | **New, required** — chart won't be correctly configured without it (was optional/absent before) |
| — | `settings.database.db_pool.*`, `notificationsSource`, `adminSearchDisabled`, `useXForwardedHost`, `enableCloudEvents` | New knobs, no forced change but worth reviewing defaults |

### D. Template changes, file-by-file

| File | Change |
|---|---|
| `templates/objecten-storage.yaml` | **No values-path change needed** (thanks to the H.1 alias) — `.Values.objecten.persistence*` keeps working as-is. Still needs its `fullnameOverride`-dependent PV/PVC naming double-checked against the newly-required `objecten.fullnameOverride: objecten` value |
| `templates/create-required-objecttypen.yaml` | Edit: repoint `.Values.objecttypen.*` refs to `.Values.objecten.*`; helper names **stay** `objecttypen.labels` → `openobject.labels` literally (not `objecten.labels` — see H.1's caveat: the subchart's named templates are fixed to its own chart name regardless of alias); token source moves to the new tokenauth mechanism (`is_superuser: true`, see H.5); `OBJECTTYPES_URL` now derives from `objecten.configuration.oidcUrl` |
| `templates/create-required-catalogi.yaml` | Edit: one incidental `.Values.objecttypen.image` reference (borrowed only as a Python-capable image) → repoint to `.Values.objecten.image` |
| `templates/keycloak-podiumd-realm-config.yaml` | **Merge the two OIDC clients into one** — delete the `objecttypen` clientId block, keep the `objecten` one as-is (resolved clientId name, H.1); merge the two group/role-mapping blocks |
| `templates/keycloak-podiumd-realm-secrets.yaml` | Collapse the two secret-list entries into one |
| `templates/keycloak-import-podiumd-realm-job.yaml` | Remove `objecttypen` from the component iteration list and its `KC_SECRET_OBJECTTYPEN` env var |
| `templates/adapter-config.yaml` / `adapter-secret.yaml` (kiss) | Two default hostnames collapse to one merged-service hostname |
| `templates/validations.yaml` | No change — only validates a plain URL string (`ita.medewerker.type`), not an `objecten`/`objecttypen` values reference |
| `values-enable-observability.yaml` | Merge the two OTEL blocks into one `objecten.settings.otel` block |
| `ci/lint-values.yaml` | Merge the two placeholder blocks into one `objecten` block |

No vendored `.tgz` exists for either chart under `charts/podiumd/charts/` —
nothing to remove there; `helm dependency update` manages it dynamically.

### E. Keycloak realm client

Becomes **one client**: one Django app, one admin login, one OIDC surface.
Cascades into the secrets template (one secret instead of two), the realm
import job (one `KC_SECRET_*` env var), and the two group/role-mapping
blocks. ClientId name is **resolved to `objecten`** (H.1) — no Keycloak
redirect-URI/client-name churn for existing gemeente realms.

### F. Downstream consumer config changes

- **zac** (`zac.objectenApi.*`, `zac.objecttypenApi.*`) — repoint both to the
  same merged host; no podiumd template change (ZAC is an external subchart).
- **ita** (`ita.apiConnections.object.baseUrl`, `ita.{logboek,afdeling,groep,medewerker}.type`)
  — repoint the `-objecttypen` hostname in all four `type` URLs to the merged host.
- **kiss** (`kiss.adapter.objecten.*`, `kiss.adapter.objecttypen.*`, various
  `objectTypeUrl`/`objectTypeVersion` keys) — collapse to one host; template
  changes covered in D, remaining changes are per-environment value updates.
- **omc** (`omc.settings.zgw.variable.objectType.*`) — **no change needed**;
  these are UUID references into the object-types catalogue, not host/token
  fields, and should resolve unchanged post-migration.
- **openformulieren**, **openarchiefbeheer**, **openbeheer** (commented
  `zgw_consumers` examples referencing `objecten-api`/`objecttypen-api`/
  `objecttypen-service`) — update the example `api_root` host to the merged
  app; consider whether identifier names should be renamed for clarity
  (non-functional). Preserve the `IN-2345` token-matching comment currently
  in `objecttypen.configuration.secrets` wherever the merged tokenauth item
  for openbeheer ends up living.

### G. Docs updates needed

- ✅ Done (**design decision**: `objecten` replaces `objecttypen`, not a new
  `openobject`-named doc): `docs/apps/objecten/objecten-BASICS.md` updated in
  place to describe the merged app — folding in the relevant content from
  `objecttypen-BASICS.md` (runtime components, dependencies, integration
  steps) and noting throughout that Objecten now also handles what used to
  be Objecttypen's job (local objecttypes) — as
  `patches/09-docs-objecten-basics-merged-update.patch`.
- ✅ Done: `docs/apps/objecttypen/objecttypen-BASICS.md` (plus its `.gitkeep`
  placeholder) is deleted, as `patches/15-docs-objecttypen-basics-delete.patch`
  — the component itself is being removed by this same patch set, and its
  content has been folded into `objecten-BASICS.md` above rather than left to
  go stale.
- `docs/apps/redis/redis-ha-databases.md` — collapse the two DB rows into one
  `objecten` row; document the freed DB index.
- `docs/misc/resource-overview.md` — merge the two components' resource rows.
- `README.md` — regenerate the values-reference section for `openobject`,
  add a manual upgrade-history row, update the `global.settings.databaseHost`
  description (currently lists "objecten, objecttypen, ...").
- Add a new `docs/_UPGRADE_PATHS/<from>-to-<to>-upgrade.md` (per the
  `upgrade-notes` skill convention) documenting the precondition steps,
  Keycloak client merge, Redis DB-index change, and PVC/media continuity
  requirement.
- `docs/misc/mi-exports.md` — optional wording cleanup only (illustrative
  path mentions `objecten`, no functional mi-export template actually
  references `objecten`/`objecttypen`).

### H. Open design decisions

1. ~~**Service/dependency naming**~~ — **RESOLVED: keep the name `objecten`,
   via the alias approach.** Verified the exact Helm mechanics from the
   subchart's own `templates/_helpers.tpl` before settling on this — it's a
   **two-part mechanism**, not just the alias alone:

   - **`alias: objecten` in `Chart.yaml`** (section B) — controls only the
     *values.yaml key path*. With this set, PodiumD's own values.yaml,
     `ci/lint-values.yaml`, `values-enable-observability.yaml`, and every
     podiumd-owned template continue to read/write `.Values.objecten.*`
     instead of `.Values.openobject.*` — minimizing the values.yaml/template
     diff versus today.
   - **`objecten.fullnameOverride: objecten`** (i.e. `fullnameOverride` set
     *inside* that aliased values block) — controls the rendered names of
     the main Deployment, Service, ConfigMap, Secret, PVC and
     ServiceAccount, plus (since `workerFullname`/`flowerFullname` are both
     built as `<fullname>-worker`/`<fullname>-flower`) the worker and flower
     Deployments too. It is **required in addition to the alias**, not
     implied by it: the subchart's `openobject.fullname` helper falls back
     to `<release-name>-<chart-name>` (i.e. `.Chart.Name`, the subchart's
     own name from *its* `Chart.yaml` — "openobject" — regardless of any
     alias the parent uses) when `fullnameOverride` is unset. Without this
     override, resources would render as `podiumd-openobject` even with the
     alias in place. Setting it to `objecten` reproduces today's exact
     object names, DNS (`objecten.podiumd.svc.cluster.local`), Azure Files
     share reference, and every downstream consumer's existing default
     hostname (e.g. KISS adapter's fallback
     `http://objecten.<namespace>.svc.cluster.local`) with zero changes
     needed there.
   - **`objecten.nameOverride: objecten` — also required, and easy to miss.**
     Checked every template in the subchart: the `app.kubernetes.io/name`
     selector label (`openobject.selectorLabels`, used identically for pod
     `matchLabels`/pod template labels on the **main, worker, and flower**
     Deployments) and the **config Job's name itself**
     (`openobject.configName`) are both built from `openobject.name` —
     which resolves `nameOverride` (falling back to `.Chart.Name`, i.e.
     "openobject"), **not** `fullnameOverride`. This is an inconsistency
     inside the chart's own `_helpers.tpl` (`workerFullname`/`flowerFullname`
     use `.fullname`, but `configName` uses `.name`) — with only
     `fullnameOverride: objecten` set, the config Job would render as
     `openobject-config` (not `objecten-config`), and **every** pod's
     `app.kubernetes.io/name` label would read `openobject` even though its
     resource name reads `objecten`. Checked this repo's own templates and
     `docs/misc/observability.md`/`network-policy-analysis.md`: nothing here
     currently selects on that label, so it isn't a functional break today —
     but it's a real, easily-missed operational inconsistency (breaks
     `kubectl get pods -l app.kubernetes.io/name=objecten`, and leaves
     "openobject" leaking into every pod's labels and the config job's name)
     that a future ServiceMonitor/NetworkPolicy/alert rule could quietly
     depend on the wrong value for. Set both overrides together.
   - **Caveat that does *not* need any action**: the subchart's own internal
     named templates (`openobject.labels`, `openobject.fullname`,
     `openobject.configName`, etc., in its `_helpers.tpl`) stay hardcoded to
     the literal string `openobject` no matter what alias or
     `fullnameOverride` is used — Helm's named-template namespace is global
     across the whole chart tree, keyed by the string baked into the
     `{{- define "openobject.xxx" -}}` calls in the subchart's own source,
     not by the parent's alias. Any podiumd template that needs to call
     these (e.g. `create-required-objecttypen.yaml`'s label helper, section
     D) must reference `openobject.labels` etc. literally — this is
     internal/invisible to users and does not affect any rendered object
     name, so it needs no further decision, just correct authoring.

   This resolution changes sections B–G below: the target values.yaml block
   is `objecten:` (not `openobject:`), and the Keycloak client name (E) is
   `objecten`.
2. ~~**Which public hostname survives**~~ — **RESOLVED**: the existing
   `<env>-objecten...` hostname survives unchanged (consistent with H.1: the
   merge keeps the `objecten` identity everywhere, including externally);
   `<env>-objecttypen...` is retired and needs a redirect/deprecation notice
   for any external bookmarks or integrations. `settings.siteDomain` (now
   required) is set to the surviving `objecten` hostname. **Checked upstream
   for guidance — there is none** (confirmed against `docs/manual/migration.rst`,
   `docs/installation/config.rst`, and
   `docs/installation/deployment/kubernetes.rst`) — this was purely a
   PodiumD/team decision, made in favor of `objecten` for consistency with H.1.
3. ~~**Redis DB index**~~ — **RESOLVED**: keep `objecten`'s existing indices
   (DB 1 cache, DB 2 celery); `objecttypen`'s old DB 0 is freed — consistent
   with H.1/H.2 (`objecten` survives everywhere). No functional difference
   either way, purely a consistency/docs call. **Checked upstream — there is
   none.** `docs/manual/migration.rst` (the authoritative migration guide)
   has exactly four sections (intro, version flow, importing objecttype
   data, setup-configuration changes) and mentions nothing about Redis,
   cache, or Celery broker/backend selection. Purely a PodiumD decision.
   Already implemented in `values.yaml` (`objecten.settings.cache.*` on
   `/1`, `objecten.settings.celery.*` on `/2`) and documented in
   `docs/apps/redis/redis-ha-databases.md`.
4. ~~**DB/data-migration mechanics**~~ — **RESOLVED**, see A.6/A.7 above.
5. ~~**`create-required-objecttypen` job's admin token mechanism**~~ —
   **RESOLVED**: `TokenAuthConfigurationStep` (`src/objects/setup_configuration/steps/token_auth.py`)
   supports an `is_superuser` field on `tokenauth.items[]`. A superuser token
   bypasses per-object-type `permissions` scoping entirely (no per-type
   `Permission` rows needed) — set `is_superuser: true` on the tokenauth
   item that replaces the old plain `objecttypen.configuration.token`, and
   the `create-required-objecttypen` job's unrestricted admin access carries
   over unchanged. **Cross-checked against `docs/manual/migration.rst`'s
   TokenAuth section** — it lists only the `use_fields`/`fields` removals
   (already reflected in section C), no mention of `is_superuser`; that
   detail only exists in the actual `token_auth.py` source, not this guide.
6. ~~**uwsgi worker tuning**~~ — **substantially de-risked**: the image
   itself (`bin/docker_start.sh`) defaults to `--processes 4 --threads 4`
   when `UWSGI_PROCESSES`/`UWSGI_THREADS` are unset. `objecten` today sets
   neither (already running at this default); `objecttypen` overrides down
   to 2×2 (per `objecttypen-BASICS.md`). So the "merge" isn't an unknown
   tuning problem — leave `objecten.settings.uwsgi` unset for the initial
   rollout (keeps the more generous of the two current configurations,
   rather than carrying over objecttypen's tighter override) and tune from
   observed traffic post-cutover, same as any other capacity question.
   **Also checked `docs/manual/migration.rst` directly for anything
   further — nothing.** No uwsgi/worker/performance content there at all;
   the `docker_start.sh` finding above is the complete upstream picture.
7. ~~**KISS adapter value-key split**~~ — **RESOLVED**: collapse
   `kiss.adapter.objecten.*`/`kiss.adapter.objecttypen.*` into one
   `kiss.adapter.objecten.*` block (consistent with H.1/H.2: `objecten` is
   the surviving name everywhere, not `openobject`). Implemented in
   `patches/04-kiss-adapter-collapse.patch` (values.yaml + both adapter
   templates). No upstream guidance exists either way — KISS is a
   Dimpact/PodiumD-specific integration, not part of the upstream
   `open-object` project — so this was purely a PodiumD/team decision.

## TODO

Status as of 2026-08-05. **Patches applied**: the full Chart.yaml/
values.yaml/template/docs diff was drafted as reviewable patch files under
`patches/` at the repo root (one patch per logical change — see that
directory's contents) and has since been applied to `charts/podiumd/`'s
working tree with `git apply`. Nothing is committed yet; only
`openobject-migration.md` itself is staged (`git add`), the rest of the diff
is unstaged in the working tree pending review/commit.

### Still open — need a team decision, not more research

All H.1–H.7 design decisions are now resolved; nothing left in this category.

- [x] ~~H.2 — Which public hostname survives~~ — **RESOLVED**: the existing
      `<env>-objecten...` hostname survives; `<env>-objecttypen...` is
      retired. Implemented in `patches/02-values-yaml.patch`
      (`settings.siteDomain`).
- [x] ~~H.3 — Which Redis DB index to keep~~ — **RESOLVED**: keep objecten's
      (DB 1 cache / DB 2 celery), freeing objecttypen's old DB 0. Implemented
      in `patches/02-values-yaml.patch` and `patches/10-docs-redis-ha-databases.patch`.
- [x] ~~H.7 — KISS adapter value-key split~~ — **RESOLVED**: collapsed into
      `kiss.adapter.objecten.*` (not `openobject.*` — `objecten` is the
      surviving name everywhere). Implemented in
      `patches/04-kiss-adapter-collapse.patch`.
- [x] ~~H.1 — Naming~~ — **RESOLVED**: keep `objecten`, via
      `alias: objecten` in `Chart.yaml` **plus both**
      `objecten.nameOverride: objecten` **and**
      `objecten.fullnameOverride: objecten` (the alias alone does not
      rename k8s objects, and `fullnameOverride` alone misses the config
      Job's name and every pod's `app.kubernetes.io/name` label — see H.1
      for the full mechanism and why both are needed).
- [x] ~~H.6 — uwsgi worker retuning~~ — de-risked, see A.7/H.6: leave
      `objecten.settings.uwsgi` unset for the initial rollout.

### Not yet started — concrete execution work

- [x] ~~Open the precondition PR: bump `objecten` chart `2.12.0`→`2.12.1`
      (appVersion `3.6.0`→`3.6.1`)~~ — **already satisfied in this
      checkout**: `values.yaml` already pins `objecten` at chart 2.12.1/
      appVersion 3.6.2, with `resultBackend` already correctly named (no
      `resultBackendl` typo).
- [x] ~~Draft the actual `Chart.yaml`/`values.yaml`/template diff for the
      `openobject` swap (sections B–D)~~ — **drafted and applied**: the
      reviewable patch files under `patches/` at the repo root (Chart.yaml,
      values.yaml core restructure, downstream-consumer values, KISS collapse,
      template patches, Keycloak template merge, observability/lint-values,
      and docs patches) were each generated by editing the file, capturing
      `git diff`, then reverting, so the diffs stayed visible as standalone
      files for review before anything was staged. All have since been
      applied to `charts/podiumd/`'s working tree via `git apply`; the
      resulting changes are unstaged, pending review/commit.
- [x] ~~Pin an image digest for `maykinmedia/open-object`~~ — **done**:
      `values.yaml`'s `objecten.image.tag` is now
      `4.1.0@sha256:7738cb8161d221d0a286d39d9d270c35024ff78123c296ceb46f3d9dda7208f9`
      (fetched from Docker Hub's manifest API), and the image is recorded in
      `docs/images/images-4.9.0.yaml` alongside the release's other two
      image changes.
- [x] ~~Scaffold `docs/_UPGRADE_PATHS/<from>-to-<to>-upgrade.md`~~ — drafted
      as `docs/_UPGRADE_PATHS/4.8.X-to-4.9.0-upgrade.md` (new file, written
      directly rather than as a patch since it doesn't exist in git yet).
      Marked as a draft: `4.8.X` is a literal placeholder for the exact
      source patch version, pending team confirmation of which release this
      ships in.
- [ ] Audit per-gemeente values overrides for use of the two fields upstream
      4.0.0 removes (`objecttypes.items[].service_identifier`,
      `tokenauth.items[].{fields,use_fields}`) — needs access to
      per-gemeente values files outside this repo.
- [ ] Confirm every gemeente's *running* (not just chart-pinned) appVersion
      is ≥3.4.0 before relying on that migration having already happened —
      needs checking live deployments outside this repo.
- [ ] Inventory per-gemeente overrides for the section-F downstream
      consumers (`zac.objectenApi`/`.objecttypenApi`, `ita.*.type`,
      `kiss.adapter.*`/`kiss.settings.*.objectTypeUrl`) — F currently says
      "per-environment value updates" without an actual list of which
      gemeenten have overridden these; same outside-this-repo access
      constraint as the two items above, not previously called out as its
      own item.
- [x] ~~Write an explicit rollback runbook for the `openobject` cutover
      itself~~ — **done**: section C ("Rollback runbook") of
      `docs/_UPGRADE_PATHS/4.8.X-to-4.9.0-upgrade.md` now has the full
      numbered procedure — failure signature, confirm-then-rollback to
      `objecten` 3.6.1, re-running `check_for_external_objecttypes` to
      identify offending UUIDs, the still-exists-vs-deleted-upstream branch
      from A.6, re-verification, and retry — rather than just the one-line
      summary that lived here before.
