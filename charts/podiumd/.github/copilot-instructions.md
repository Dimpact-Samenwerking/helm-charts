# Copilot instructions for PodiumD chart (charts/podiumd)

Purpose
This file summarizes commands, architecture, and repository conventions for Copilot sessions.

Where to run
Run commands from the chart root:
cd charts\podiumd

Build / dependency / lint / template commands
# Setup helm repos (run once before dependency operations)
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add maykinmedia https://maykinmedia.github.io/charts/
helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts
helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
helm repo add kiss-elastic https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic
helm repo add openshift https://charts.openshift.io
helm repo add zac https://infonl.github.io/dimpact-zaakafhandelcomponent/
helm repo add zgw-office-addin https://infonl.github.io/zgw-office-addin
helm repo add adfinis https://charts.adfinis.com

# Dependency management (from charts/podiumd/)
helm dependency update
helm dependency build

# Lint the chart
helm lint charts/podiumd

# Render templates (dry-run)
helm template podiumd charts/podiumd -f <values-file.yaml> -n podiumd

# Render a single template (validate one manifest / "single test")
helm template podiumd charts/podiumd -f <values-file.yaml> -s templates/<template.yaml>

# Install / upgrade
helm upgrade --install podiumd charts/podiumd -f <values-file.yaml> -n <namespace>

Notes on testing
- There are no dedicated Helm test manifests in this chart by default. To validate a single manifest or to "test" a one-off resource, render the specific template with -s (see above).
- values schema: kiss.schema.json contains a JSON Schema for values validation; use Helm 3.11+ or external validation tooling to validate values against the schema.

High-level architecture (short)
- This is an umbrella/wrapper Helm chart that aggregates many upstream application charts declared in Chart.yaml (OpenZaak, OpenKlant, OpenForms, Keycloak/Keycloak-operator, etc.).
- The chart's role: wire shared configuration via values.yaml, enable/disable components with <component>.enabled booleans, and provide custom templates for Cross-cutting resources:
  - keycloak operator CR and secrets (keycloak-cr.yaml, keycloak-secrets.yaml, keycloak-* realm configs)
  - API-proxy (nginx) for BAG/BRP/KVK (api-proxy-*.yaml)
  - KISS adapter (adapter-*.yaml)
  - Persistent storage PVC templates (*-storage.yaml)
  - One-off seeding Jobs (create-required-*.yaml) that run Python scripts stored as ConfigMaps
  - _helpers.tpl for naming/labels
- Keycloak migration: chart now prefers keycloak-operator (keycloak-operator.enabled: true); legacy Bitnami keycloak + Infinispan is deprecated. See docs/migrating-to-keycloak-operator.md.

Key conventions and patterns
- Dependency management: bump versions in Chart.yaml, then run helm dependency update/build.
- Component toggles: each sub-chart is controlled by <component>.enabled boolean in values.yaml; some components are grouped by tags (e.g., contact, zaak).
- Aliases: some dependencies use 'alias' for a shorter name (see Chart.yaml).
- Persistent storage: configured under persistentVolume.* and templates/*-storage.yaml; be cautious with Azure CSI attributes present in values.yaml.
- One-off jobs: create-required-* templates run Python scripts (scripts/) via ConfigMaps; these should be idempotent or guarded by global.configuration settings.
- Vendored charts: charts/ contains pinned .tgz packages for reproducible builds; Chart.lock also present.
- Schema and validation: kiss.schema.json provides schema for values.yaml.
- Documentation: check docs/ for migration notes (Keycloak) and API-proxy URL rewriting.

Where to look
- Chart.yaml — dependency versions and conditions
- values.yaml — primary configuration (heavily commented)
- templates/ — custom resources and helper templates
- docs/ and scripts/ — migration and helper scripts
- CLAUDE.md — authoritative Copilot/automation guidance for this chart

AI assistant configs
- CLAUDE.md (detailed guidance) and .claude/settings.local.json exist in the repo root; prefer CLAUDE.md for operational commands and CI details.

End
If edits are needed or more coverage (CI, release workflow, or per-subchart notes) is desired, request specific areas to add.
