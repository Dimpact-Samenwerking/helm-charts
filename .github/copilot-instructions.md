# Copilot Instructions — Dimpact Helm Charts

Single source of truth for AI assistant guidance.

---

## General Rules

### Check repo updates before work

Before any changes in ANY local repo (this or external like ZAC), check last `git fetch`/`git pull`. If >1 day old, run `git fetch` (or `git pull` on working branch) first, report new commits on current branch or upstream. Avoid stale code.

---

## Repository Layout

```
charts/
  podiumd/            # Umbrella — 25+ sub-chart deps (main)
  kiss/               # Standalone KISS (customer interaction)
  monitoring-logging/ # Observability (Loki, Promtail, Prometheus, Grafana)
  vngreferentielijsten/ # VNG reference data
  beproeving/         # Pilot/experimental
  brp-personen-mock/  # BRP mock API for testing
```

---

## Common Commands

Dependency ops → from `charts/podiumd/`. Lint/template → repo root.
Required Helm repos in `Chart.yaml`. Add all at once: `charts/podiumd/scripts/add-helm-repos.sh` before `helm dependency update`.

```bash
# Update/build deps (from charts/podiumd/)
helm dependency update && helm dependency build

# Lint — always use CI values file
helm lint charts/podiumd -f charts/podiumd/ci/lint-values.yaml

# Render all templates (dry-run, skip JSON schema)
helm template podiumd charts/podiumd -f charts/podiumd/ci/lint-values.yaml --skip-schema-validation

# Render single template
helm template podiumd charts/podiumd -f charts/podiumd/ci/lint-values.yaml --skip-schema-validation -s templates/<template.yaml>

# Render with env values (full validation)
helm template podiumd charts/podiumd -f <values-file.yaml> -n podiumd

# Deploy / upgrade
helm upgrade --install podiumd charts/podiumd -f <values-file.yaml> -n <namespace>
```

**Lint notes:**
- Always `-f charts/podiumd/ci/lint-values.yaml` — default `values.yaml` leaves security fields blank (no `changeme` defaults), fails validation without real values.
- `--skip-schema-validation` needed for `helm template` — KISS subchart JSON schema requires fields not in CI values.
- Keep `charts/podiumd/ci/lint-values.yaml` up to date with placeholders for new required fields.

No dedicated Helm test manifests. Use `-s templates/<template.yaml>` to validate individual resources. `kiss.schema.json` = JSON Schema validation for `values.yaml` (Helm 3.11+).

---

## Architecture

### `charts/podiumd` — Umbrella Chart

Does NOT define app containers directly. It:
- Declares 25+ upstream charts as deps in `Chart.yaml`
- Wires shared config across sub-charts via `values.yaml`
- Enables/disables via `<component>.enabled` booleans + `tags.*` groups
- ~30 custom templates for cross-cutting concerns:
  - `keycloak-cr.yaml`, `keycloak-secrets.yaml`, `keycloak-*-realm-config.yaml` — Keycloak operator CRD, DB creds, realm ConfigMaps
  - `keycloak-ensure-*.yaml`, `keycloak-import-*.yaml` — Jobs provisioning SA client, admin user, realm imports
  - `api-proxy-*.yaml` — nginx Deployment/Service/ConfigMap proxying BAG, BRP, KVK Dutch gov APIs
  - `adapter-*.yaml` — KISS adapter Deployment/Service/ConfigMap/Secret
  - `*-storage.yaml` — PVCs for stateful apps (Azure CSI driver)
  - `create-required-*.yaml` — Python seeding jobs (scripts in ConfigMaps); must be idempotent or guarded by `global.configuration` flags
  - `_helpers.tpl` — Shared label/name/image helpers
  - `serviceaccount.yaml` — Shared ServiceAccount for seeding jobs

**Key sub-charts**: OpenZaak, OpenKlant, OpenFormulieren, OpenInwoner, OpenNotificaties, Objecten, Objecttypen, KISS, ZAC, Keycloak Operator, ClamAV, Redis Operator, more.

**Component tags:**
- `tags.contact: true` — KISS-related
- `tags.zaak: true` — ZAC-related

**Shared config pattern:**
- `global.settings.databaseHost` — shared PostgreSQL host injected into all sub-charts
- `global.configuration.enabled` / `global.configuration.overwrite` — controls init/seeding jobs

**Persistent storage:** Stateful apps use `*-storage.yaml` PVC templates. Azure CSI driver params (`volumeAttributeShareName`, `volumeAttributeResourceGroup`, `nodeStageSecretRefName`) under `persistentVolume.*` in `values.yaml`.

**Some deps use `alias`** to shorten names (e.g. `openformulieren` aliased from upstream). Check `Chart.yaml` for aliases before referencing sub-chart values keys.

**Vendored charts:** `charts/podiumd/charts/` has pinned `.tgz` packages + `Chart.lock` for reproducible builds.

**Inspecting vendored `.tgz`:** Prefer inspection without extracting — `tar -xzOf <chart>.tgz <path>` reads a file to stdout. If you must extract `.tgz` or checkout chart dir, **always delete both extracted dir AND original `.tgz` from `charts/podiumd/charts/` when done.** Helm prefers extracted dirs over `.tgz` — leaving extracted charts causes `helm template`/`lint`/`upgrade` to silently use extracted (possibly modified) version instead of pinned package → breaks deployments.

### Keycloak Migration (Active)
Transitioning Bitnami Keycloak + Infinispan → **Hostzero Keycloak Operator**:
- **New (default)**: `keycloak-operator.enabled: true` — manages Keycloak via `Keycloak` CRD (`keycloak-cr.yaml`)
- **Legacy (deprecated)**: `keycloak.enabled: true` + `infinispan.enabled: true`
- Both use SAME PostgreSQL database; realm data preserved
- Key `keycloak.*` values (e.g. `externalDatabase`, `secretsName`, `config`, `image`) shared by both
- Migration guide: `charts/podiumd/docs/migrating-to-keycloak-operator.md`
- Cleanup script: `charts/podiumd/scripts/cleanup-keycloak-and-infinispan.sh`

### API Proxy
nginx proxy (`apiproxy.*` in values) for 3 Dutch gov APIs:
- **BAG** — Building and Address Registry (iConnect / Kadaster)
- **BRP** — Personal Records Database
- **KVK** — Chamber of Commerce (Search, Basic Profile, Branch Profile)

Supports optional mTLS (`nginxCertsSecret`) + response URL rewriting via nginx `sub_filter`. See `charts/podiumd/docs/api-proxy-url-rewriting.md`.

---

## Key Conventions

### Resource Requests and Limits
Every container in every template **MUST** declare `requests` + `limits` for CPU/memory:
- All custom templates (Deployments, Jobs, init containers, sidecars)
- Sub-chart components wired via `values.yaml`

Wire sub-chart resources via sub-chart's documented key (e.g. `openzaak.resources`, `keycloak-operator.operator.resources`). Document defaults + chart limitations in `charts/podiumd/docs/resource-overview.md`. If sub-chart doesn't expose `resources` key, note there + raise with upstream.

### Image References
All images in podiumd templates use `{{ include "podiumd.image" <image> }}` with `{registry, repository, tag}` map in `values.yaml`. NEVER embed plain `"repo:tag"` strings in templates.

On aks-blue envs, all images pulled from env-specific ACR (set via `global.imageRegistry`). Tags defined by chart defaults — env values files only contain repository overrides, not tags.

### AKS-Blue Cluster Conventions
- **Never** `helm install/upgrade/delete` or `kubectl apply/delete` directly against aks-blue. All changes via CI/CD pipeline.
- Read-only ops OK: `kubectl get`, `logs`, `describe`, `helm status`, `helm template`. Always `--context <cluster-name>` with every `kubectl`.
- All workloads on aks-blue require `nodeSelector: kubernetes.azure.com/mode: user` — keycloak-operator, Keycloak CR pod template, all app workloads.

### Security Documentation
- Keycloak realm security changes (token lifespans, brute force, password policy, session settings) → log in `charts/podiumd/docs/keycloak-security-updates.md`.
- ClamAV security/config updates → log in `charts/podiumd/docs/clamav-security-updates.md`.

### BOM Check
Before committing `values.yaml`, verify no UTF-8 BOM (bytes `0xEF 0xBB 0xBF`) — breaks YAML tooling:

```powershell
$bytes = [System.IO.File]::ReadAllBytes("charts/podiumd/values.yaml")
if ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [System.IO.File]::WriteAllBytes("charts/podiumd/values.yaml", $bytes[3..($bytes.Length-1)])
    Write-Host "BOM removed"
} else { Write-Host "No BOM - OK" }
```

### Duplicate Key Detection
Before committing `values.yaml`, run dup key check — catches silent data-loss:

```powershell
# Working tree (before git add)
pwsh charts/podiumd/scripts/check-duplicate-keys.ps1

# Staged (after git add, before git commit)
pwsh charts/podiumd/scripts/check-duplicate-keys.ps1 -Staged
```

List-item hits (`value:`, `mountPath:`) = false positives, ignore.

### Git Workflow
Never commit or push automatically. Always wait for explicit user approval before `git commit` or `git push`.

---

## Release Process

### Production Releases (Automatic)
Trigger: push to `main` or `release/*`. Uses `helm/chart-releaser-action`. Applies to ALL charts.

### Snapshot Releases — Podiumd Only (Manual)
Trigger via **Release Snapshot Charts** workflow in Actions tab.
- Versions: `podiumd-<version>-<branch-name>-snapshot`
- Pre-release; auto-deleted after 3 weeks
- Only `charts/podiumd`

### Manual Release with Changelogs
**Release Charts met changelogs** workflow fetches upstream changelogs (Open Zaak, Open Formulieren, Open Klant, etc.) from GitHub + generates release notes.

### Images Manifest per Release
For each podiumd release, create `charts/podiumd/docs/images/images-<version>.yaml` covering **only new/changed images** vs previous release (including sidecar/exporter images from `values-enable-observability.yaml`).

Format: flat YAML list with `name`, `url`, `version`, `digest` fields. Use component name from chart (e.g. `openinwoner`, not `open-inwoner`). Same tag as `values.yaml`. Short Dutch group comment (e.g. `# Applicaties`). Style ref: `images-4.6.1.yaml`.

Find changed images:
```powershell
git diff main...HEAD -- charts/podiumd/values.yaml | Select-String "^\+.*tag:"
git diff main...HEAD -- charts/podiumd/Chart.yaml
```

Fetch digests via registry API with Python's `urllib.request` — request manifest with `Accept: application/vnd.oci.image.index.v1+json`, read `Docker-Content-Digest` response header. Docker Hub: first obtain bearer token from `auth.docker.io`.

---

### Upgrade Notes per Release
For each release with breaking changes, new images, or manual steps, create `charts/podiumd/docs/upgrade-from-<prev>-to-<version>.md` covering: new images needing ACR override (key path + snippet), new optional components, removed/deprecated components, required manual steps, component version bump table (`| Component | old | new |`). Style ref: `upgrade-from-4.5.13-to-4.6.0.md`.

---

## Dependency Management

Renovate (`renovate.json`) auto-opens PRs for upstream bumps. Manual sub-chart upgrade: bump version in `Chart.yaml`, run `helm dependency update` from `charts/podiumd/`. Commit updated `.tgz` packages in `charts/podiumd/charts/` + `Chart.lock`.

## Helm Value Precedence (lowest → highest)
1. Subchart's own `values.yaml`
2. Parent chart's `values.yaml`
3. User-supplied `-f env-values.yaml`
4. `--set` flags

---

## Working with ZAC Repository

ZAC chart lives at `https://github.com/infonl/dimpact-zaakafhandelcomponent` (local clone: `C:\Users\johnb\IdeaProjects\dimpact-zaakafhandelcomponent`).

PRs/commits there — follow their conventions exactly:

- **Branch names**: `feature/PZ-XXX-short-description` — always PZ Jira ticket. External contributions without ticket can omit but keep `feature/` prefix.
- **PR title**: `<type>[optional scope]: <description>` (Conventional Commits). E.g. `fix(helm): use health endpoint for Solr liveness probe`.
- **PR body**: One line plain text describing change.
- **PR footer**: `Solves PZ-XXX` referencing Jira ticket. Omit for external contributions without ticket.
- **Commit messages**: Same `<type>[scope]: <description>` format. When squash-merging, copy PR body into squash description.
- **Chart version**: Bump `charts/zac/Chart.yaml` `version` (patch increment) with every chart change.
- **SPDX headers**: Modified source files need `SPDX-FileCopyrightText` / `SPDX-License-Identifier: EUPL-1.2+`. Don't add `INFO.nl` to header unless you are an INFO.nl developer.

Valid commit types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `perf`, `style`.

---

## Key Files

| File | Purpose |
|------|---------|
| `charts/podiumd/Chart.yaml` | All dep versions + aliases; bump here to upgrade |
| `charts/podiumd/values.yaml` | Primary config (heavily commented) |
| `charts/podiumd/kiss.schema.json` | JSON Schema for values (Helm 3.11+) |
| `charts/podiumd/templates/_helpers.tpl` | Named templates for labels, names, image rendering |
| `charts/podiumd/docs/resource-overview.md` | Resource requests/limits matrix |
| `charts/podiumd/docs/migrating-to-keycloak-operator.md` | Keycloak migration guide |
| `charts/podiumd/docs/api-proxy-url-rewriting.md` | nginx URL rewriting for BAG/BRP/KVK proxies |
| `charts/podiumd/docs/keycloak-security-updates.md` | Keycloak realm security changelog |
| `charts/podiumd/docs/images/images-<version>.yaml` | Images manifest per release (new/changed only) |
| `charts/podiumd/docs/upgrade-from-<prev>-to-<version>.md` | Upgrade guide per release |
| `charts/podiumd/scripts/cleanup-keycloak-and-infinispan.sh` | Pre-migration cleanup for legacy Keycloak/Infinispan |
| `charts/podiumd/scripts/patch-keycloak-entra-idp.ps1` | Patch Entra ID IDP settings on target cluster |
