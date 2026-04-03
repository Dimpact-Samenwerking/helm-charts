# Copilot Instructions — Dimpact Helm Charts

This is the single source of truth for AI assistant guidance in this repository.

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

```bash
# Add required Helm repos (run once before dependency operations)
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add maykinmedia https://maykinmedia.github.io/charts/
helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts
helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
helm repo add kiss-elastic https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic
helm repo add zac https://infonl.github.io/dimpact-zaakafhandelcomponent/
helm repo add zgw-office-addin https://infonl.github.io/zgw-office-addin
helm repo add adfinis https://charts.adfinis.com
helm repo add opstree https://ot-container-kit.github.io/helm-charts/

# Update/build dependencies
cd charts/podiumd
helm dependency update
helm dependency build

# Lint
helm lint charts/podiumd

# Render all templates (dry-run)
helm template podiumd charts/podiumd -f <values-file.yaml> -n podiumd

# Render a single template ("single test")
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
Before committing changes to `values.yaml`, run this scan to catch YAML keys that silently overwrite earlier ones (duplicate map keys are a silent data-loss bug).

> **Important:** the script reads the file from disk (working tree). If you have already staged your changes with `git add` without running the check first, use the staged variant below — otherwise the check runs against the pre-change file and misses the staged content.

**Working tree (run before `git add`):**
```powershell
$script = @'
import re
lines = open(r'charts/podiumd/values.yaml', encoding='utf-8').readlines()
stack = []
scope_keys = {}
duplicates = []
for i, line in enumerate(lines, 1):
    stripped = line.lstrip()
    if stripped.startswith('#') or stripped.startswith('-'):
        continue
    m = re.match(r'^(\s*)([a-zA-Z0-9_\-][^:#\n]*?)\s*:', line)
    if not m:
        continue
    indent = len(m.group(1))
    key = m.group(2).strip()
    while stack and stack[-1][0] >= indent:
        stack.pop()
    scope_id = tuple(k for _,k in stack)
    if scope_id not in scope_keys:
        scope_keys[scope_id] = {}
    if key in scope_keys[scope_id]:
        parent = ' > '.join(scope_id) if scope_id else '(root)'
        duplicates.append(f'Line {i}: duplicate "{key}" under [{parent}] (first line {scope_keys[scope_id][key]})')
    else:
        scope_keys[scope_id][key] = i
    stack.append((indent, key))
if duplicates:
    print(f'FOUND {len(duplicates)} duplicate(s):')
    for d in duplicates: print(' ', d)
else:
    print('No duplicate keys found')
'@
$script | python
```

**Staged variant (run after `git add`, before `git commit`):**
```powershell
$script = @'
import re, sys
lines = sys.stdin.read().splitlines(keepends=True)
stack = []
scope_keys = {}
duplicates = []
for i, line in enumerate(lines, 1):
    stripped = line.lstrip()
    if stripped.startswith('#') or stripped.startswith('-'):
        continue
    m = re.match(r'^(\s*)([a-zA-Z0-9_\-][^:#\n]*?)\s*:', line)
    if not m:
        continue
    indent = len(m.group(1))
    key = m.group(2).strip()
    while stack and stack[-1][0] >= indent:
        stack.pop()
    scope_id = tuple(k for _,k in stack)
    if scope_id not in scope_keys:
        scope_keys[scope_id] = {}
    if key in scope_keys[scope_id]:
        parent = ' > '.join(scope_id) if scope_id else '(root)'
        duplicates.append(f'Line {i}: duplicate "{key}" under [{parent}] (first line {scope_keys[scope_id][key]})')
    else:
        scope_keys[scope_id][key] = i
    stack.append((indent, key))
if duplicates:
    print(f'FOUND {len(duplicates)} duplicate(s):')
    for d in duplicates: print(' ', d)
else:
    print('No duplicate keys found')
'@
git show :charts/podiumd/values.yaml | python -c $script
```

Hits inside YAML sequences (list items sharing key names like `value:` or `mountPath:`) are false positives and can be ignored.

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
For each podiumd release, an images manifest is created at:
```
charts/podiumd/docs/images/images-<version>.yaml
```

The format mirrors `ExternalsPodiumD/pipelines/images.yml` — an Azure DevOps pipeline YAML with a `parameters.images` list, each entry having `name`, `url`, and `version`. The file covers **only images that are new or changed** in that release compared to the previous one, including:
- Application image tag bumps (from subchart or `values.yaml` changes)
- Any new sidecar/exporter images enabled in that release (e.g. from `values-enable-observability.yaml`)

All images listed must have a corresponding `{registry, repository, tag}` definition in `values.yaml` so they can be overridden to point at the environment-specific ACR. Use the same tag values as defined in `values.yaml` (do not invent versions). Each entry must include a `digest` field (`sha256:...`) fetched from the source registry at the time of writing. The file is a flat YAML list (no pipeline wrapper, no indentation on list items). Include a short Dutch comment per group (e.g. `# Applicaties`, `# Observability`) matching the style of the reference file.

---

## Dependency Management

Renovate is configured (`renovate.json`) with the recommended defaults and automatically opens PRs for upstream dependency version bumps.

To upgrade a sub-chart, bump its version in `Chart.yaml`, then run `helm dependency update` from `charts/podiumd/`. Vendored `.tgz` packages in `charts/podiumd/charts/` and `Chart.lock` are committed for reproducible builds.

---

## Known Documentation Issues

### `charts/podiumd/docs/upgrade-from-4.5.13-to-4.6.0.md` — incorrect precedence description
The section "Configuration jobs for objecten and opennotificaties" originally stated that subchart defaults take precedence over the parent `podiumd/values.yaml`. This is backwards — in Helm the parent chart's `values.yaml` always overrides subchart defaults.

What actually happened: in 4.5.13 `podiumd/values.yaml` did not contain `objecten.configuration.job.enabled: true`, so the subchart default of `false` won by absence. The fix was adding the override to `podiumd/values.yaml` in 4.6.0. No env-level override for `job.enabled` is required.

**Helm value precedence** (lowest → highest):
1. Subchart's own `values.yaml`
2. Parent chart's `values.yaml`
3. User-supplied `-f env-values.yaml`
4. `--set` flags

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
| `charts/podiumd/scripts/cleanup-keycloak-and-infinispan.sh` | Pre-migration cleanup for legacy Keycloak/Infinispan |
| `charts/podiumd/scripts/patch-keycloak-entra-idp.ps1` | Patch Entra ID IDP settings on a target cluster |
