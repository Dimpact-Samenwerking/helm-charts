# Switching from the old to the new IAM setup (ZAC + PABC)

Short guide for environments that still authorise ZAC the "old" way and need to
move to PABC. Applies from PodiumD **4.8.4**.

## What changed

| | Old setup | New setup |
|---|---|---|
| Where authorisation lives | Keycloak only | Keycloak (who you are) + PABC (what you may do) |
| ZAC roles | `zac` client roles on each Keycloak group | PABC application roles, resolved per request |
| Access to zaaktypen | `domein_elk_zaaktype` client role = all zaaktypen | PABC mapping, either `isAllEntityTypes: true` or scoped to a domain |
| Who administers it | Keycloak admin | Functioneel beheerder, in the PABC UI |

The Keycloak groups themselves do **not** change. ZAC reads the user's group
names from the `group_membership` claim (mapper `groups-member` on the `zac`
client) and asks PABC what those groups may do. In PABC a Keycloak group name is
called a **functional role**.

The practical consequence: an environment where PABC is empty gives every user
zero application roles, and ZAC answers every page with
**"u heeft geen toestemming om deze pagina te bekijken"**. Keycloak looks
perfectly fine in that situation, which makes this easy to misdiagnose.

## Steps

### 1. Make sure PABC itself runs

Follow [enabling-pabc.md](./enabling-pabc.md) first: database, secrets, values,
DNS. Verify the `pabc` pod is `1/1 Running` and the `pabc-migrations` job is
`Complete`. Migrations only create the schema; they do not put any data in.

### 2. Seed the basic setup

Enable both values on the environment:

```yaml
pabc:
  datasetConfigMap:
    enabled: true
  seedJob:
    enabled: true
```

On the next `helm upgrade` the `pabc-seed-job-<checksum>` Job runs once and
loads `files/pabc-dataset.json`: the `zaakafhandelcomponent` application, its six
application roles, six functional roles matching the Keycloak group names, and
mappings that mirror the `zac` client roles those groups had in the old setup,
including the equivalent of `domein_elk_zaaktype`.

The Job name contains a checksum of the dataset, so it runs once and then stays
put across upgrades. It only runs again if the dataset itself changes.

> **Seeding replaces everything.** The migration service deletes all
> applications, application roles, functional roles, domains, entity types and
> mappings before inserting the dataset. On an environment that has already been
> curated in the PABC UI, leave `seedJob.enabled: false` and do the work in the
> UI instead.

### 3. Verify

```bash
kubectl -n podiumd get job -l app.kubernetes.io/component=pabc
kubectl -n podiumd logs job/pabc-seed-job-<checksum>
```

Then log in to ZAC with a user in one of the groups and open a zaak. If it still
fails, check in the PABC UI (`https://pabc.<env-domain>`, user must be in the
`administrators` group) whether the functional roles are present and mapped.

### 4. Refine (optional)

The seeded setup grants each group access to all zaaktypen, which matches what
`domein_elk_zaaktype` did before. To restrict groups to specific zaaktypen,
create domains in the PABC UI and move the mappings onto them. Do not re-enable
the seed job afterwards: it would discard that work.

## Group to application role matrix

Seeded by the dataset, mirroring `keycloak-podiumd-realm-config.yaml`:

| Keycloak group (functional role) | ZAC application roles |
|---|---|
| `administrators` | `administrator`, `beheerder`, `coordinator`, `behandelaar`, `raadpleger`, `recordmanager` |
| `beheerders` | `beheerder`, `coordinator`, `behandelaar`, `raadpleger`, `recordmanager` |
| `recordmanagers` | `recordmanager`, `coordinator`, `behandelaar`, `raadpleger` |
| `coordinators` | `coordinator`, `behandelaar`, `raadpleger` |
| `behandelaars` | `behandelaar`, `raadpleger` |
| `raadplegers` | `raadpleger` |

## Relation to the older init job

`podiumd-infra` carries `kubernetes/post-deployment-setup/post-deployment-pabc-init-job.yml`,
which did the same seeding through raw SQL plus a Keycloak step. The chart-native
seed job replaces it and is preferable on managed clusters, for two reasons:

- The SQL job uses `postgres:15` and `curlimages/curl`, which the Azure Policy
  allowed-images constraint on the `aks-blue-*` clusters rejects. The seed job
  reuses the already-mirrored `pabc-migrations` image.
- It runs as part of the release, so it does not have to be applied by hand on
  every environment.

The Keycloak half of that job created realm roles named after the groups. That is
not needed for the ZAC to PABC path: ZAC resolves functional roles from the
`group_membership` claim, not from realm roles.

Note that the old job's matrix did not give `beheerders` the `recordmanager`
role. The dataset follows the realm config, which does.
