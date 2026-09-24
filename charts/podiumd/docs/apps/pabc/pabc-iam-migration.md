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

ZAC takes the user's functional roles from the Keycloak **realm roles** in the
token (`realm_access.roles`) and asks PABC what those roles may do. The
`group_membership` claim (mapper `groups-member` on the `zac` client) is only
logged. So every functional role needs a realm role with exactly that name,
attached to the Keycloak group of the same name; users then get the role by
group membership. ZAC 5.4.4 logs both at login ("with groups: [...],
functional roles: '[...]'"), which is the quickest check.

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

The Job name contains a checksum of the dataset and of the rendered pod
template, so it runs once and then stays put across upgrades. It only runs again
if the dataset changes, or if something that decides what the Job does changes,
such as the migrations image tag or the seed job resources.

The seed job comes with a second Job, `pabc-keycloak-groups-job-<checksum>`,
for the Keycloak side. ZAC sends the user's Keycloak **realm roles** to PABC as
functional roles (not the group names), so the functional roles only work if the
`podiumd` realm has, per functional role, a realm role with exactly that name,
attached to a group with the same name. The realm import creates those with
`keycloak.config.skipGroups`/`skipRoles: false` (O/T); with `true` this Job
does it. Using `kcadm.sh` from the Keycloak image as the `keycloak-operator`
service account, it creates per functional role the realm role and the group if
they are missing and attaches the role to the group. Nothing else: it never
touches client roles, other groups or existing mappings, and never removes
anything. It needs `keycloak-operator.enabled` and
`keycloak-operator.jobs.ensureOperatorSa.clientSecret`, and can be switched off
with `pabc.seedJob.keycloak.enabled: false`. Users still have to be put in the
groups, by hand or through the identity provider.

> **Test environments only.** Like the seed job this is meant for empty test
> environments. Municipalities keep `pabc.seedJob.enabled: false` and map their
> own realm roles to functional roles in the PABC UI.
>
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

The Keycloak half of that job created realm roles named after the groups. That
**is** needed: ZAC resolves functional roles from the realm roles, not from the
`group_membership` claim. Both the realm import (`skipRoles`/`skipGroups:
false`) and `pabc-keycloak-groups-job` (with `pabc.seedJob.enabled`) create
these realm roles and attach them to the groups.

Note that the old job's matrix did not give `beheerders` the `recordmanager`
role. The dataset follows the realm config, which does.
