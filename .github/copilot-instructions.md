# Copilot Instructions — Dimpact Helm Charts

This is the single source of truth for AI assistant guidance in this repository.

---

## General Rules

### Check for repo updates before starting work

Before making any changes in **any** local repository (this repo or any external repo such as ZAC), check when the last `git fetch`/`git pull` was done. If the most recent update is more than 1 day old, run `git fetch` (or `git pull` if on the working branch) first and report any new commits on the current branch or its upstream. This prevents working on stale code.

---

## Repository Layout

```
charts/
  podiumd/            # Umbrella chart — 25+ sub-chart dependencies (main chart)
  kiss/               # Standalone KISS (customer interaction) chart
  monitoring-logging/ # Observability stack (Loki, Promtail, Prometheus, Grafana)
  vngreferentielijsten/ # VNG reference data chart
  beproeving/         # Pilot/experimental chart
  brp-personen-mock/  # BRP mock API for testing
```

---

## Common Commands

Dependency operations must be run from `charts/podiumd/`. Lint and template commands can be run from the repo root.
Required Helm repos are listed in `Chart.yaml`. To add them all at once run `charts/podiumd/scripts/add-helm-repos.sh` before `helm dependency update`.

```bash
# Update/build dependencies (from charts/podiumd/)
helm dependency update && helm dependency build

# Lint
helm lint charts/podiumd

# Render all templates (dry-run)
helm template podiumd charts/podiumd -f <values-file.yaml> -n podiumd

# Render a single template
helm template podiumd charts/podiumd -f <values-file.yaml> -s templates/<template.yaml>

# Deploy / upgrade
helm upgrade --install podiumd charts/podiumd -f <values-file.yaml> -n <namespace>
```

There are no dedicated Helm test manifests. Use `-s templates/<template.yaml>` to validate individual resources. `kiss.schema.json` provides JSON Schema validation for `values.yaml` (requires Helm 3.11+).

---

## Architecture

### `charts/podiumd` — Umbrella Chart

This chart does **not** define application containers directly. It:
- Declares 25+ upstream charts as dependencies in `Chart.yaml`
- Wires shared config across sub-charts via `values.yaml`
- Enables/disables components via `<component>.enabled` booleans and `tags.*` groups
- Provides ~30 custom templates for cross-cutting concerns:
  - `keycloak-cr.yaml`, `keycloak-secrets.yaml`, `keycloak-*-realm-config.yaml` — Keycloak operator CRD, DB credentials, and realm ConfigMaps
  - `keycloak-ensure-*.yaml`, `keycloak-import-*.yaml` — Jobs for provisioning the Keycloak SA client, admin user, and realm imports
  - `api-proxy-*.yaml` — nginx Deployment/Service/ConfigMap proxying BAG, BRP, and KVK Dutch government APIs
  - `adapter-*.yaml` — KISS adapter Deployment/Service/ConfigMap/Secret
  - `*-storage.yaml` — PVCs for all stateful apps (Azure CSI driver)
  - `create-required-*.yaml` — One-off Python seeding jobs (scripts stored in ConfigMaps); must be idempotent or guarded by `global.configuration` flags
  - `_helpers.tpl` — Shared label, name, and image helper templates
  - `serviceaccount.yaml` — Shared ServiceAccount used by seeding jobs

**Key sub-charts**: OpenZaak, OpenKlant, OpenFormulieren, OpenInwoner, OpenNotificaties, Objecten, Objecttypen, KISS, ZAC, Keycloak Operator, ClamAV, Redis Operator, and more.

**Component groups via tags:**
- `tags.contact: true` — enables KISS-related components
- `tags.zaak: true` — enables ZAC-related components

**Shared configuration pattern:**
- `global.settings.databaseHost` — shared PostgreSQL host injected into all sub-charts
- `global.configuration.enabled` / `global.configuration.overwrite` — controls whether init/seeding jobs run on deployment

**Persistent storage:**
All stateful apps use `*-storage.yaml` PVC templates. Azure CSI driver parameters (`volumeAttributeShareName`, `volumeAttributeResourceGroup`, `nodeStageSecretRefName`) live under `persistentVolume.*` in `values.yaml`.

**Some dependencies use `alias`** to shorten their name (e.g. `openformulieren` aliased from the upstream chart name). Check `Chart.yaml` for aliases before referencing sub-chart values keys.

**Vendored charts:** `charts/podiumd/charts/` contains pinned `.tgz` packages and `Chart.lock` for reproducible builds.

### Keycloak Migration (Active)
Transitioning from Bitnami Keycloak + Infinispan → **Hostzero Keycloak Operator**:
- **New (default)**: `keycloak-operator.enabled: true` — manages Keycloak via `Keycloak` CRD (`keycloak-cr.yaml`)
- **Legacy (deprecated)**: `keycloak.enabled: true` + `infinispan.enabled: true`
- Both use the **same PostgreSQL database**; realm data is preserved
- Key values under `keycloak.*` (e.g. `externalDatabase`, `secretsName`, `config`, `image`) are shared by both approaches
- Migration guide: `charts/podiumd/docs/migrating-to-keycloak-operator.md`
- Cleanup script: `charts/podiumd/scripts/cleanup-keycloak-and-infinispan.sh`

### API Proxy
nginx-based proxy (`apiproxy.*` in values) for three Dutch government APIs:
- **BAG** — Building and Address Registry (iConnect / Kadaster)
- **BRP** — Personal Records Database
- **KVK** — Chamber of Commerce (Search, Basic Profile, Branch Profile)

Supports optional mTLS (`nginxCertsSecret`) and response URL rewriting via nginx `sub_filter`. See `charts/podiumd/docs/api-proxy-url-rewriting.md`.

---

## Key Conventions

### Resource Requests and Limits
Every container in every template **must** declare `requests` and `limits` for CPU and memory. This includes:
- All custom templates (Deployments, Jobs, init containers, sidecars)
- Sub-chart components wired through `values.yaml`

Wire sub-chart resources via the sub-chart's documented key (e.g., `openzaak.resources`, `keycloak-operator.operator.resources`). Document defaults and chart limitations in `charts/podiumd/docs/resource-overview.md`. If a sub-chart does not expose a `resources` key, note it there and raise it with the upstream team.

### Image References
All images in podiumd templates must use `{{ include "podiumd.image" <image> }}` with a `{registry, repository, tag}` map in `values.yaml`. Never embed plain strings like `"repo:tag"` directly in templates.

On aks-blue environments, all images must be pulled from the environment-specific ACR (set via `global.imageRegistry`). Image tags are defined by chart defaults — environment values files should only contain repository overrides, not tags.

### AKS-Blue Cluster Conventions
- **Never** run `helm install/upgrade/delete` or `kubectl apply/delete` directly against aks-blue clusters. All changes must go through the CI/CD pipeline.
- Read-only operations are fine: `kubectl get`, `logs`, `describe`, `helm status`, `helm template`. Always pass `--context <cluster-name>` to every `kubectl` command.
- All workloads on aks-blue environments require `nodeSelector: kubernetes.azure.com/mode: user` — including keycloak-operator, the Keycloak CR pod template, and all application workloads.

### Security Documentation
- Keycloak realm security changes (token lifespans, brute force, password policy, session settings, etc.) must be logged in `charts/podiumd/docs/keycloak-security-updates.md`.
- ClamAV security/config updates must be logged in `charts/podiumd/docs/clamav-security-updates.md`.

### Duplicate Key Detection
Before committing changes to `values.yaml`, run the duplicate key check to catch silent data-loss bugs:

```powershell
# Working tree (before git add)
pwsh charts/podiumd/scripts/check-duplicate-keys.ps1

# Staged (after git add, before git commit)
pwsh charts/podiumd/scripts/check-duplicate-keys.ps1 -Staged
```

List-item hits (`value:`, `mountPath:`) are false positives — ignore them.

### Git Workflow
Never commit or push automatically. Always wait for explicit user approval before running `git commit` or `git push`.

---

## Release Process

### Production Releases (Automatic)
Triggered on push to `main` or `release/*`. Uses `helm/chart-releaser-action`. Applies to **all charts**.

### Snapshot Releases — Podiumd Only (Manual)
Trigger via the **Release Snapshot Charts** workflow in the Actions tab.
- Versions: `podiumd-<version>-<branch-name>-snapshot`
- Marked as pre-release; auto-deleted after 3 weeks
- Only applies to `charts/podiumd`

### Manual Release with Changelogs
The **Release Charts met changelogs** workflow fetches upstream changelogs (Open Zaak, Open Formulieren, Open Klant, etc.) from GitHub and generates release notes.

### Images Manifest per Release
For each podiumd release, create `charts/podiumd/docs/images/images-<version>.yaml` covering **only images that are new or changed** vs the previous release (including sidecar/exporter images from `values-enable-observability.yaml`).

Format: flat YAML list with `name`, `url`, `version`, and `digest` fields. Use the component name from the chart (e.g. `openinwoner`, not `open-inwoner`). Use the same tag as in `values.yaml`. Include a short Dutch group comment (e.g. `# Applicaties`). See `images-4.6.1.yaml` as style reference.

To find changed images:
```powershell
git diff main...HEAD -- charts/podiumd/values.yaml | Select-String "^\+.*tag:"
git diff main...HEAD -- charts/podiumd/Chart.yaml
```

Fetch digests via the registry API using Python's `urllib.request` — request the manifest with `Accept: application/vnd.oci.image.index.v1+json` and read the `Docker-Content-Digest` response header. For Docker Hub, first obtain a bearer token from `auth.docker.io`.

---

### Upgrade Notes per Release
For each release with breaking changes, new images, or required manual steps, create `charts/podiumd/docs/upgrade-from-<prev>-to-<version>.md` covering: new images needing ACR override (key path + snippet), new optional components, removed/deprecated components, required manual steps, and a component version bump table (`| Component | old | new |`). See `upgrade-from-4.5.13-to-4.6.0.md` as style reference.
---

## Dependency Management

Renovate (`renovate.json`) automatically opens PRs for upstream version bumps. To upgrade a sub-chart manually: bump its version in `Chart.yaml`, then run `helm dependency update` from `charts/podiumd/`. Commit the updated `.tgz` packages in `charts/podiumd/charts/` and `Chart.lock`.

## Helm Value Precedence (lowest → highest)
1. Subchart's own `values.yaml`
2. Parent chart's `values.yaml`
3. User-supplied `-f env-values.yaml`
4. `--set` flags

---

## Working with the ZAC Repository

The ZAC chart lives at `https://github.com/infonl/dimpact-zaakafhandelcomponent` (local clone: `C:\Users\johnb\IdeaProjects\dimpact-zaakafhandelcomponent`).

When raising PRs or commits there, follow their conventions exactly:

- **Branch names**: `feature/PZ-XXX-short-description` — always use a PZ Jira ticket number. External contributions without a ticket can omit it but keep the `feature/` prefix.
- **PR title**: `<type>[optional scope]: <description>` (Conventional Commits). E.g. `fix(helm): use health endpoint for Solr liveness probe`.
- **PR body**: One line of plain text describing the change.
- **PR footer**: `Solves PZ-XXX` referencing the Jira ticket. Omit for external contributions with no ticket.
- **Commit messages**: Same `<type>[scope]: <description>` format. When squash-merging, copy the PR body into the squash description.
- **Chart version**: Bump `charts/zac/Chart.yaml` `version` field (patch increment) with every chart change.
- **SPDX headers**: All modified source files need `SPDX-FileCopyrightText` / `SPDX-License-Identifier: EUPL-1.2+` headers. Do not add `INFO.nl` to the header unless you are an INFO.nl developer.

Valid commit types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `perf`, `style`.

---

## Key Files

| File | Purpose |
|------|---------|
| `charts/podiumd/Chart.yaml` | All dependency versions and aliases; bump here to upgrade components |
| `charts/podiumd/values.yaml` | Primary configuration file (heavily commented) |
| `charts/podiumd/kiss.schema.json` | JSON Schema for values validation (Helm 3.11+) |
| `charts/podiumd/templates/_helpers.tpl` | Named templates for labels, names, image rendering |
| `charts/podiumd/docs/resource-overview.md` | Resource requests/limits matrix for all components |
| `charts/podiumd/docs/migrating-to-keycloak-operator.md` | Keycloak migration guide |
| `charts/podiumd/docs/api-proxy-url-rewriting.md` | nginx URL rewriting for BAG/BRP/KVK proxies |
| `charts/podiumd/docs/keycloak-security-updates.md` | Log of Keycloak realm security changes |
| `charts/podiumd/docs/images/images-<version>.yaml` | Images manifest per release (new/changed images only) |
| `charts/podiumd/docs/upgrade-from-<prev>-to-<version>.md` | Upgrade guide per release (new images, breaking changes, manual steps) |
| `charts/podiumd/scripts/cleanup-keycloak-and-infinispan.sh` | Pre-migration cleanup for legacy Keycloak/Infinispan |
| `charts/podiumd/scripts/patch-keycloak-entra-idp.ps1` | Patch Entra ID IDP settings on a target cluster |
