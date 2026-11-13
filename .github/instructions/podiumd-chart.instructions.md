---
applyTo: "charts/podiumd/values.yaml,charts/podiumd/Chart.yaml,charts/podiumd/templates/**,charts/podiumd/ci/**"
excludeAgent: "cloud-agent"
---

# Review: podiumd chart, values and templates

## Images

- Templates render images with `{{ include "podiumd.image" <image> }}` and a
  `registry`, `repository`, `tag` map in `values.yaml`. Flag a plain
  `"repo:tag"` string in a template.
- Tags in `values.yaml` are pinned as `"<tag>@sha256:<digest>"`. Flag a tag
  change without a new digest, and a tag without a digest.
- A new or changed image tag has an entry with the same tag and digest in
  `charts/podiumd/docs/images/images-<version>.yaml` of the release.

## Resources

- Every container has CPU and memory `requests` and `limits`: Deployments,
  Jobs, init containers and sidecars in templates, and sub-chart components
  through the sub-chart's own key (for example `openzaak.resources`).
- A new workload must run with `nodeSelector: kubernetes.azure.com/mode: user`,
  which aks-blue requires.

## Values

- No duplicate keys in `values.yaml`: a later key silently replaces an earlier
  one. No UTF-8 BOM at the start of the file.
- Security fields default to `""`: no `changeme`, no real values. A new
  required field gets a placeholder in `ci/lint-values.yaml`.
- A URL value has no `example.nl` default: it stays `""` and the example goes
  in its `# --` comment.
- A sub-chart key uses the dependency's `alias` from `Chart.yaml` when it has
  one.

## Keycloak

- A Keycloak client with redirect URIs in
  `templates/keycloak-podiumd-realm-config.yaml` has an entry in the
  `$oidcClients` render check, gated on the component's `.enabled`, and a
  `ci.podiumd.test` URL in `ci/lint-values.yaml`.
- A realm security change (token lifespans, brute force, password policy,
  sessions) is logged in
  `charts/podiumd/docs/apps/keycloak/keycloak-security-updates.md`. ClamAV
  security changes go in `docs/apps/clamav/clamav-security-updates.md`.

## Jobs

- `create-required-*` seeding jobs can run twice without harm, or are guarded
  by the `global.configuration` flags.
