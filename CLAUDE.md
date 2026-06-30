# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**Dimpact PodiumD** Helm charts — a Dutch government "zaakgericht werken" stack. GitHub: `Dimpact-Samenwerking/helm-charts`.

The umbrella chart is `charts/podiumd`, composing many sub-charts (openzaak, openinwoner, keycloak-operator, redis-operator, zgw-office-addin, zaakbrug, open-notificaties, etc.). Per-gemeente deployments inject their own values over the chart defaults.

> Note: if a `CLAUDE.md` describing "CrawlDock" (an MCP search server) is loaded from a parent/workspace directory, it does **not** apply here — this repo is the Helm charts.

## Branches

- `feature/podiumd-4.8.0` — current release integration base; feature/fix PRs target it, then it rolls up to `main`.
- `main` — default branch.

## Conventions

@.claude/memory/branch-workflow.md
@.claude/memory/render-verify.md

## Skills

Project skills live in `.claude/commands/` (e.g. `/helm-render-all`, `/helm-deps`, `/helm-lint`, `/check-image-cves`, `/verify-image-digests`, `/images-manifest`, `/branch-overview`). Prefer these for chart workflows.

## Images manifest

`charts/podiumd/docs/images/images-baseline.yaml` is the single complete strip-registry mirror manifest (per-release delta images + long-stable gap-fillers). `scripts/mirror-strip-registry.py --gen-manifest` regenerates only the per-release-delta subset; the gap-filler entries are hand-maintained there.
