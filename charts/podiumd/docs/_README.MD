# PodiumD chart documentation — structure

This folder holds all operator- and maintainer-facing documentation for the
`podiumd` umbrella chart. Underscore-prefixed entries sort to the top: they are
the navigation layer — start there.

## Layout

| Entry | What it holds |
|---|---|
| [`_UPGRADING.md`](_UPGRADING.md) | **Start here for any upgrade.** Operator index ("which guide do I read?") plus the maintainer section (official upgrade path, release requirements). |
| [`_UPGRADE_PATHS/`](_UPGRADE_PATHS/) | One set of files per upgrade hop, named version-first so `ls` sorts chronologically (see below). |
| [`apps/<app>/`](apps/) | Per-application docs — one subfolder per chart dependency (openzaak, keycloak, redis, …) plus supporting components (apiproxy, elastic, …). Runbooks, known-issues, design notes for that app live there. Every folder has an `<app>-BASICS.md` entry point; structure and template: [`apps/_APP-DOCS-PATTERN.md`](apps/_APP-DOCS-PATTERN.md). |
| [`images/`](images/) | ACR-mirror image manifests: `images-<release>.yaml` per release, [`images-baseline.yaml`](images/images-baseline.yaml) as the complete pinned set, and the [naming convention](images/acr-mirror-naming.md). |
| [`architecture/`](architecture/) | Platform-level architecture: PodiumD C4 system-context overview plus per-product context diagrams (KISS, Open Formulieren). Dutch-language. |
| [`misc/`](misc/) | Cross-cutting docs not tied to one app or release: observability, network policies, resource overview, security review, schema validation, and more (the MI-exports operator guide moved to [`charts/mi-data/docs/mi-exports.md`](../../mi-data/docs/mi-exports.md) with the 4.8.3 subchart extraction). |

## `_UPGRADE_PATHS/` — files per hop

Every hop `<from>-to-<to>` (e.g. `4.7.8-to-4.8.0`) has **three** files, so the
set sits adjacent in a directory listing — plus a fourth that only exists when
the hop touches an operator or CRDs:

| File | Purpose |
|---|---|
| `<from>-to-<to>-upgrade.md` | The operator guide for the hop: required manual steps, breaking changes, and pointers to the companions. Not a record of what changed — the `## Component versions` table is the only place versions appear. |
| `<from>-to-<to>-values-deltas.md` | The values edits for the hop and nothing else: one table per values file, columns `Key`/`Action`/`From`/`To`/`When`. No prose. One line when the hop needs no edits. |
| `<from>-to-<to>-gemeente-specific.md` | Findings that apply to one gemeente/environment only. Mostly empty; filled in if and when something comes up during rollouts. |
| `<from>-to-<to>-operators-crds.md` *(only where applicable)* | Operator and CRD additions/upgrades in the hop (keycloak-operator, redis-operator, eck-operator): what changes, CRD impact, and the pre-deploy steps (CRD installs/adoption usually run **before** `helm upgrade`). Not created for hops without operator/CRD changes. |

Consolidated guides (e.g. `4.6.8-to-4.7.6`) fold a range of patch releases into
one document; the granular per-patch notes are kept alongside for reference.
Which guides form the official path — and which are reference-only — is
defined in [`_UPGRADING.md`](_UPGRADING.md).

**Format is binding** — [`_UPGRADE_PATHS/CLAUDE.md`](_UPGRADE_PATHS/CLAUDE.md)
is the authority for every file in that folder, for humans and for Claude alike.
Read it before adding or editing one.

## Adding a new upgrade guide

For a new release `<new>` with predecessor `<prev>`:

1. Bump `charts/podiumd/Chart.yaml` and pin the new images in
   `charts/podiumd/values.yaml` (tag + digest).
2. Scaffold the guide with the `/upgrade-notes <prev>-to-<new>` skill →
   `_UPGRADE_PATHS/<prev>-to-<new>-upgrade.md`. Checklist first, details below;
   link app-specific runbooks from `apps/<app>/` instead of inlining them.
3. Create the companions in `_UPGRADE_PATHS/`:
   - `<prev>-to-<new>-values-deltas.md` — the table form specified in
     [`_UPGRADE_PATHS/CLAUDE.md`](_UPGRADE_PATHS/CLAUDE.md), or its one-line
     "no changes required" body when no gemeente values change.
   - `<prev>-to-<new>-gemeente-specific.md` — copy the empty template from any
     existing `*-gemeente-specific.md`.
   - `<prev>-to-<new>-operators-crds.md` — **only** when the release adds or
     upgrades an operator or CRDs: summary table (component / change / CRD
     impact / action) plus the pre-deploy CRD commands.
4. Generate the image manifest with `/images-manifest <new>` →
   `images/images-<new>.yaml` (skip when the release changes no images — note
   that in `_UPGRADING.md` instead).
5. Register the hop in [`_UPGRADING.md`](_UPGRADING.md): the operator
   "Which guide do I read?" table **and** the maintainer official-path table.
6. Verify: `/verify-image-digests`, `/helm-dupecheck`, `/helm-lint`, and a
   relative-link check over `docs/`.
