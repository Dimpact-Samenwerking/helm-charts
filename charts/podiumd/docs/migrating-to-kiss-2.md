# Migrating KISS configuration to schema 2.x (PodiumD 4.5+)

PodiumD 4.5 switches from KISS 1.x to the KISS 2.x Helm chart. The new chart uses a strict JSON schema to validate `values.yaml`. If the values file does not match the schema the upgrade will fail.

The migration script `scripts/migrate-kiss-schema.py` automates this transformation.

## Prerequisites

Python 3.8+. Install the recommended YAML library:

```bash
pip install ruamel.yaml
```

`ruamel.yaml` preserves existing comments and quote styles. If it is not available the script falls back to PyYAML, but comments will be lost.

## Usage

```bash
# Preview the result without writing (recommended first step):
python scripts/migrate-kiss-schema.py podiumd.yaml --dry-run

# Migrate in-place:
python scripts/migrate-kiss-schema.py podiumd.yaml

# Write to a new file, keeping the original untouched:
python scripts/migrate-kiss-schema.py podiumd.yaml -o podiumd-migrated.yaml
```

The script exits with a warning and does nothing if no `kiss:` key is found, or if `kiss.settings` already exists (indicating the file has already been migrated).

## What the script changes

### Structural renames

| Old path | New path | Notes |
|---|---|---|
| `kiss.brp` | `kiss.settings.haalCentraal` | Key renamed |
| `kiss.kvk.apikey` | `kiss.settings.kvk.apiKey` | Capitalisation fixed |
| `kiss.elastic` | `kiss.settings.elastic` | See below |
| `kiss.enterpriseSearch` | `kiss.settings.enterpriseSearch` | See below |
| `kiss.esuite` | `kiss.adapter.esuite` | `isDefault` removed |
| `kiss.database` | `kiss.settings.database` | See below |
| `kiss.email` | `kiss.settings.email` + `kiss.settings.feedback` | Split into two keys |
| `kiss.objecten` + `kiss.objecttypen` | `kiss.settings.afdelingen/groepen/logboek` + `kiss.adapter.objecten/objecttypen` | Split — see below |
| `kiss.vac` | `kiss.settings.syncJobs.vac` | `useVacs` → `manageFromKiss` |
| `kiss.sync` | `kiss.settings.syncJobs` | Restructured — see below |
| `kiss.oidc` | `kiss.settings.oidc` | See below |
| `kiss.managementApiKey` | `kiss.settings.managementInformatie.apiKey` | |
| `kiss.organisatieIds` | `kiss.settings.organisatieIds` | String → single-element list |
| `kiss.frontend.image` | `kiss.image` | Moved to top level |

### elastic

`kiss.elastic.image`, `kiss.elastic.nodeSelector`, and `kiss.elastic.persistence` are removed. Elasticsearch is now managed by the ECK operator (deployed separately). The script fills in the cluster-internal service URL when `baseUrl` was empty:

```yaml
# Old (1.x)
kiss:
  elastic:
    baseUrl: ""           # empty — was deployed by KISS chart
    username: elastic
    password: "..."
    image:
      repository: acrprodmgmt.azurecr.io/elasticsearch
      tag: "8.9.0"
    nodeSelector: ...
    persistence: ...

# New (2.x)
kiss:
  settings:
    elastic:
      baseUrl: "https://kiss-es-http.podiumd.svc.cluster.local:9200"
      username: elastic
      password: "..."
```

The same default URL logic applies to `enterpriseSearch.baseUrl` → `https://kiss-ent-http.podiumd.svc.cluster.local:3002`.

> **Note:** After migration, verify these URLs match the actual ECK service names in your cluster. The defaults assume the standard ECK service names `kiss-es-http` and `kiss-ent-http` in namespace `podiumd`.

### enterpriseSearch

`privateApikey` and `publicApikey` (lowercase `k`) are renamed to `privateApiKey` and `publicApiKey`. `image` and `nodeSelector` are removed.

### database

`user` is renamed to `username`. `port: 5432` is added with a default if not already present.

### email → email + feedback

`feedbackFrom` and `feedbackTo` are split out into a separate `feedback` key. `enableSsl` and `port` defaults are added.

```yaml
# Old
kiss:
  email:
    host: "mail.example.nl"
    feedbackFrom: "noreply@example.nl"
    feedbackTo: "feedback@example.nl"

# New
kiss:
  settings:
    email:
      enableSsl: true
      host: "mail.example.nl"
      port: 587
    feedback:
      emailFrom: "noreply@example.nl"
      emailTo: "feedback@example.nl"
```

### objecten + objecttypen split

The old `kiss.objecten` and `kiss.objecttypen` keys are split across two destinations:

- **`kiss.settings.afdelingen/groepen/logboek`** — one entry per object type, each containing `baseUrl`, `objectTypeUrl` (assembled from `objecttypen.baseUrlIntern` + the respective UUID), and `token`.
- **`kiss.adapter.objecten`** and **`kiss.adapter.objecttypen`** — unchanged credential and UUID values used by the adapter itself.

A new `kiss.settings.logboek` entry is added for the Activiteitenlog object type introduced in KISS 2.0. Its `objectTypeUrl` is constructed using the placeholder `REP_ITA_ACTIVITEITENLOG_UUID_REP`, which is the same UUID already used by ITA. Verify this placeholder is defined in your keyvault/replacement script.

### registers (new)

`kiss.settings.registers` is a new list that replaces the old scattered adapter/e-Suite configuration. The script builds one default register entry from:

- `kiss.adapter.baseUrl / clientId / secret` — used for `contactmomenten`, `interneTaak`, `klanten`, and `zaaksysteem` credentials.
- `kiss.objecttypen.interneTaakUUID` — used for `interneTaak.objectTypeUrl`.
- `kiss.esuite.baseUrl` — used for `zaaksysteem.deeplink.url` (the script appends `/mp/zaak/` if not already present).

```yaml
# New
kiss:
  settings:
    registers:
      - isDefault: true
        contactmomenten:
          baseUrl: "http://podiumd-adapter.podiumd.svc.cluster.local"
          clientId: contact_intern
          clientSecret: "..."
        interneTaak:
          baseUrl: "http://podiumd-adapter.podiumd.svc.cluster.local"
          clientId: contact_intern
          clientSecret: "..."
          objectTypeUrl: "https://objecttypen.example.nl/api/v2/objecttypes/REP_CONTACT_INTERNETAAK_UUID_REP"
          objectTypeVersion: 1
        klanten:
          baseUrl: "http://podiumd-adapter.podiumd.svc.cluster.local/klanten"
          clientId: contact_intern
          clientSecret: "..."
        zaaksysteem:
          catalogiBaseUrl: "http://podiumd-adapter.podiumd.svc.cluster.local/catalogi/api/v1"
          clientId: contact_intern
          clientSecret: "..."
          deeplink:
            property: identificatie
            url: "https://midoffice.example.nl/mp/zaak/"
          documentenBaseUrl: "http://podiumd-adapter.podiumd.svc.cluster.local/documenten/api/v1"
          useExperimentalQueries: false
          zakenBaseUrl: "http://podiumd-adapter.podiumd.svc.cluster.local/zaken/api/v1"
```

### sync → syncJobs

`kiss.sync` is restructured into `kiss.settings.syncJobs`. Key changes:

| Old | New | Notes |
|---|---|---|
| `sync.smoelenboek` | `syncJobs.medewerkers` | Renamed |
| `sync.domain` | `syncJobs.website` | Only included when `domain.enabled: true` and `url` is set |
| `sync.successfulJobsHistoryLimit` | `syncJobs.*.historyLimit` | Applied per job |
| `sync.failedJobsHistoryLimit` | _(removed)_ | No equivalent in 2.x |
| `sync.initialSync` | _(removed)_ | No equivalent in 2.x |
| `sync.*.enabled` | _(removed)_ | Jobs are always active in 2.x |
| `kiss.vac.useVacs` | `syncJobs.vac.manageFromKiss` | Boolean flag |

The `kennisbank`, `medewerkers`, and `vac` jobs now each require explicit `baseUrl`, `objectTypeUrl`, and `token`/`clientSecret` fields. These are assembled by the script from the existing `objecten`, `objecttypen`, and `adapter` values.

### oidc

`kiss.oidc.secret` is renamed to `clientSecret`. `medewerkerIdentificatieClaim` moves into a nested object:

```yaml
# Old
kiss:
  oidc:
    secret: "..."
    medewerkerIdentificatieClaim: samaccountname

# New
kiss:
  settings:
    oidc:
      clientSecret: "..."
      medewerkerIdentificatie:
        claim: samaccountname
```

### organisatieIds

The value changes from a plain string to a YAML sequence:

```yaml
# Old
kiss:
  organisatieIds: "856683164"

# New
kiss:
  settings:
    organisatieIds: ["856683164"]
```

## What the script does NOT change

- `kiss.configuration` — unchanged.
- `kiss.nodeSelector` — unchanged.
- `kiss.alpine` — unchanged.
- `kiss.adapter.image / baseUrl / clientId / secret` — fields are preserved as-is; `objecten`, `objecttypen`, and `esuite` sub-sections are added.

## Post-migration checklist

1. Verify `kiss.settings.elastic.baseUrl` and `kiss.settings.enterpriseSearch.baseUrl` point to the correct ECK services in your cluster.
2. Confirm `REP_ITA_ACTIVITEITENLOG_UUID_REP` is defined in your keyvault and replacement script. Its value is the UUID of the Activiteitenlog object type (standard value: `2eb81bd1-0d2b-4123-84ab-d55b99b9e75a`).
3. Check `kiss.settings.registers[0].zaaksysteem.deeplink.url` — the script appends `/mp/zaak/` to the old `esuite.baseUrl`; confirm this matches your e-Suite deeplink format.
4. If `kiss.sync.domain.enabled` was `false`, no `syncJobs.website` entry is created. Add one manually if website crawling needs to be enabled.
5. Delete the legacy `podiumd-frontend` deployment after the first successful upgrade:
   ```bash
   kubectl delete deployment podiumd-frontend -n podiumd
   ```
