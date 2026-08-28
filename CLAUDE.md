# Claude context

## Conventions and architecture

Read [`.github/copilot-instructions.md`](.github/copilot-instructions.md) before making any changes. It is the single source of truth for:
- Repository layout and chart architecture
- Lint/template/deploy commands and their required flags
- Image reference conventions and ACR mirror behaviour
- Resource requests/limits requirements
- AKS-blue cluster rules (read-only; no direct `helm`/`kubectl` mutations)
- Keycloak migration status (Bitnami → Hostzero Operator, active)
- Release process (production, snapshot, images manifest, upgrade notes)
- Dependency management (Renovate + manual `.tgz` workflow)
- ZAC repository conventions

## Branching strategy

See [`README.md`](README.md#branching-strategy). Summary: forward-cascade from `main` → `feature/podiumd-<X.Y.0>` → `feature/podiumd-<X.Y.0>-*` feature branches and `feature/<env>-podiumd-<X.Y.0>` environment branches.

## Pre-commit checklist

Always run before committing changes to `charts/podiumd/`:

```
/helm-precommit
```

This runs BOM check + duplicate key detection + helm lint in one step.

## Available slash commands

| Command | Purpose |
|---|---|
| `/helm-lint` | Lint the podiumd chart |
| `/helm-render` | Render a single template |
| `/helm-render-all` | Render all templates |
| `/helm-precommit` | BOM check + dup-key check + lint (run before every commit) |
| `/helm-deps` | Update Helm dependencies |
| `/helm-repos` | Add all required Helm repositories |
| `/helm-fetch-updates` | Check for upstream component updates |
| `/helm-dupecheck` | Detect duplicate keys in values.yaml |
| `/helm-bomcheck` | Check for UTF-8 BOM in values.yaml |
| `/helm-tgz-inspect` | Inspect vendored .tgz sub-charts |
| `/images-manifest` | Generate the images manifest for a release |
| `/fetch-image-digest` | Fetch the `sha256:` digest for a container image |
| `/verify-image-digests` | Verify/refresh digest pins for current image tags |
| `/check-image-cves` | Scan images for CVE-driven updates |
| `/upgrade-notes` | Scaffold a per-release upgrade guide |
| `/branch-overview` | Show current branch state vs main/upstream |
| `/verify-release-branches` | Audit release branch hygiene |
| `/kc-list-idp` | List configured Keycloak IDPs |
| `/kc-idp-secret` | Manage Keycloak IDP secrets |

## Available skills

| Skill | Purpose |
|---|---|
| `/podiumd-check-updates` | Check available updates for all PodiumD components |
| `/podiumd-configure-component` | Generate environment-specific component config + Keycloak client |
