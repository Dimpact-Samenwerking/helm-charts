# Copilot Instructions — Dimpact Helm Charts

This repository contains Helm charts for **PodiumD**, a Dutch municipal services platform. The primary chart is `charts/podiumd`. For deep operational guidance on that chart, see [`charts/podiumd/.github/copilot-instructions.md`](../charts/podiumd/.github/copilot-instructions.md) and [`charts/podiumd/CLAUDE.md`](../charts/podiumd/CLAUDE.md).

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

Run all commands from the repo root unless noted.

```bash
# Add required Helm repos (do this once before dependency operations)
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add maykinmedia https://maykinmedia.github.io/charts/
helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts
helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
helm repo add kiss-elastic https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic
helm repo add zac https://infonl.github.io/dimpact-zaakafhandelcomponent/
helm repo add zgw-office-addin https://infonl.github.io/zgw-office-addin
helm repo add adfinis https://charts.adfinis.com
helm repo add opstree https://ot-container-kit.github.io/helm-charts/

# Update/build dependencies (from a specific chart directory)
cd charts/podiumd
helm dependency update
helm dependency build

# Lint a chart
helm lint charts/podiumd

# Render all templates (dry-run)
helm template podiumd charts/podiumd -f <values-file.yaml> -n podiumd

# Render a single template ("single test")
helm template podiumd charts/podiumd -f <values-file.yaml> -s templates/<template.yaml>
```

---

## Architecture

### `charts/podiumd` — Umbrella Chart

This is the central chart. It does **not** define application containers directly. Instead it:
- Declares 25+ upstream charts as dependencies in `Chart.yaml`
- Wires shared config across sub-charts via `values.yaml`
- Enables/disables components with `<component>.enabled` booleans and `tags.*` groups
- Provides ~30 custom templates for cross-cutting concerns:
  - `keycloak-cr.yaml` / `keycloak-*` — Keycloak operator CRD and realm seeding jobs
  - `api-proxy-*.yaml` — nginx proxy for Dutch government APIs (BAG, BRP, KVK)
  - `adapter-*.yaml` — KISS adapter
  - `*-storage.yaml` — PVCs for all stateful apps (Azure CSI driver)
  - `create-required-*.yaml` — One-off Python seeding jobs (run via ConfigMaps)
  - `_helpers.tpl` — Shared label and name templates

**Key sub-charts**: OpenZaak, OpenKlant, OpenFormulieren, OpenInwoner, OpenNotificaties, Objecten, Objecttypen, KISS, ZAC, Keycloak Operator, ClamAV, Redis Operator, and more.

**Component groups via tags:**
- `tags.contact: true` — enables KISS-related components
- `tags.zaak: true` — enables ZAC-related components

**Shared configuration pattern:**
- `global.settings.databaseHost` — injected into all sub-charts as the shared PostgreSQL host
- `global.configuration.enabled` / `global.configuration.overwrite` — controls whether init/seeding jobs run

### Keycloak Migration (Active)
The chart is transitioning from Bitnami Keycloak + Infinispan → **Hostzero Keycloak Operator**:
- **New (default)**: `keycloak-operator.enabled: true` — manages Keycloak via `Keycloak` CRD
- **Legacy (deprecated)**: `keycloak.enabled: true` + `infinispan.enabled: true`
- Both use the **same PostgreSQL database**; realm data is preserved across migration
- See `charts/podiumd/docs/migrating-to-keycloak-operator.md`

---

## Key Conventions

### Resource Requests and Limits
Every container in every template **must** declare `requests` and `limits` for CPU and memory. This includes:
- All custom templates (Deployments, Jobs, init containers, sidecars)
- Sub-chart components wired through `values.yaml`

Wire sub-chart resources via the sub-chart's documented key (e.g., `openzaak.resources`, `keycloak-operator.operator.resources`). Document defaults and chart limitations in `charts/podiumd/docs/resource-overview.md`.

### Image References (Podiumd)
All images must use `{{ include "podiumd.image" <image> }}` with a `{registry, repository, tag}` map in `values.yaml`. Never embed plain strings like `"repo:tag"` directly in templates.

On aks-blue environments, all images must be pulled from the environment-specific ACR (set via `global.imageRegistry`). Image tags are defined by chart defaults — environment values files should only contain repository overrides.

### AKS-Blue Cluster Conventions
- **Never** run `helm install/upgrade/delete` or `kubectl apply/delete` directly against aks-blue clusters. All changes must go through the CI/CD pipeline.
- Read-only operations are fine: `kubectl get`, `logs`, `describe`, `helm status`, `helm template`.
- All workloads on aks-blue environments require `nodeSelector: kubernetes.azure.com/mode: user` — including keycloak-operator, the Keycloak CR pod template, and all application workloads.

### Security Documentation
- Keycloak realm security changes (token lifespans, brute force, password policy, session settings, etc.) must be logged in `charts/podiumd/docs/keycloak-security-updates.md`.
- ClamAV security/config updates must be logged in `charts/podiumd/docs/clamav-security-updates.md`.

### Duplicate Key Detection
Before committing changes to `values.yaml`, run the duplicate key scan from `charts/podiumd/.github/copilot-instructions.md` to catch silent YAML key overwrites.

### Git Workflow
Never commit or push automatically. Always wait for explicit user approval before running `git commit` or `git push`.

---

## Release Process

### Production Releases (Automatic)
Triggered on push to `main` or `release/*`. Uses `helm/chart-releaser-action`. Applies to **all charts**.

### Snapshot Releases — Podiumd Only (Manual)
Trigger via the **Release Snapshot Charts** workflow ([Actions tab](../../actions/workflows/release-snapshot.yaml)).
- Versions: `podiumd-<version>-<branch-name>-snapshot`
- Marked as pre-release; auto-deleted after 3 weeks
- Only applies to `charts/podiumd`

### Manual Release with Changelogs
The **Release Charts met changelogs** workflow fetches upstream changelogs (Open Zaak, Open Formulieren, Open Klant, etc.) from GitHub and generates release notes.

---

## Dependency Management

Renovate is configured (`renovate.json`) with the recommended defaults and automatically opens PRs for upstream dependency version bumps.

To upgrade a sub-chart, bump its version in `Chart.yaml`, then run:
```bash
cd charts/podiumd
helm dependency update
```
Vendored `.tgz` packages in `charts/podiumd/charts/` are committed for reproducible builds.

---

## Known Documentation Issues

### `docs/upgrade-from-4.5.13-to-4.6.0.md` — incorrect precedence description
The section "Enable configuration jobs for objecten and opennotificaties" states:
> "The `objecten` and `opennotificaties` subcharts default to `job.enabled: false` at the subchart level, **which takes precedence over the parent `podiumd/values.yaml` default of `true`**."

This has the precedence direction backwards. In Helm, parent chart `values.yaml` always overrides subchart defaults — not the other way around. The subchart defaults are the lowest priority layer.

What actually happened: in 4.5.13 the parent `values.yaml` did **not** contain `objecten.configuration.job.enabled: true`, so the subchart default of `false` applied by default (no parent override existed). The fix was to add the override to `podiumd/values.yaml`, which is present in 4.6.0. The env-level workaround described in the upgrade guide is therefore unnecessary for anyone deploying from the chart — the chart default now handles it.

Same applies to `openarchiefbeheer`: both the subchart default (`true`) and `podiumd/values.yaml` (`true`) agree, so no env override is needed. The upgrade guide does not mention archiefbeheer in this context, which is consistent.

**Precedence order for reference** (lowest → highest):
1. Subchart's own `values.yaml` (defaults)
2. Parent chart's `values.yaml` (overrides subchart defaults)
3. User-supplied `-f env-values.yaml`
4. `--set` flags

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `charts/podiumd/Chart.yaml` | All dependency versions; bump here to upgrade components |
| `charts/podiumd/values.yaml` | Primary configuration file (heavily commented) |
| `charts/podiumd/kiss.schema.json` | JSON Schema for values validation (Helm 3.11+) |
| `charts/podiumd/templates/_helpers.tpl` | Named templates for labels, names, image rendering |
| `charts/podiumd/docs/resource-overview.md` | Resource requests/limits matrix for all components |
| `charts/podiumd/docs/migrating-to-keycloak-operator.md` | Keycloak migration guide |
| `charts/podiumd/docs/api-proxy-url-rewriting.md` | nginx URL rewriting for BAG/BRP/KVK proxies |
| `charts/podiumd/scripts/patch-keycloak-entra-idp.ps1` | Patch Entra ID IDP settings on a target cluster |
