# PodiumD chart documentation — structure

This folder holds all operator- and maintainer-facing documentation for the
`podiumd` umbrella chart. Underscore-prefixed entries sort to the top: they are
the navigation layer — start there.

## Layout

| Entry | What it holds |
|---|---|
| [`_UPGRADING.md`](_UPGRADING.md) | **Start here for any upgrade.** Operator index ("which guide do I read?") plus the maintainer section (official upgrade path, release requirements). |
| [`_UPGRADE_PATHS/`](_UPGRADE_PATHS/) | One set of files per upgrade hop, named version-first so `ls` sorts chronologically (see below). |
| [`apps/<app>/`](apps/) | Per-application docs — one subfolder per chart dependency (openzaak, keycloak, redis, …) plus supporting components (apiproxy, elastic, …). Runbooks, known-issues, design notes for that app live there. |
| [`images/`](images/) | ACR-mirror image manifests: `images-<release>.yaml` per release, [`images-baseline.yaml`](images/images-baseline.yaml) as the complete pinned set, and the [naming convention](images/acr-mirror-naming.md). |
| `misc/` | Cross-cutting analyses that are not tied to one app or release (observability, network policies, resource overview, security review, schema validation). |

## `_UPGRADE_PATHS/` — files per hop

Every hop `<from>-to-<to>` (e.g. `4.7.8-to-4.8.0`) has **three** files, so the
trio sits adjacent in a directory listing:

| File | Purpose |
|---|---|
| `<from>-to-<to>-upgrade.md` | The operator guide for the hop: per-environment checklist up top, explanation of every change below. |
| `<from>-to-<to>-values-deltas.md` | Key-by-key gemeente `podiumd.yml` reference (add/change/remove). A short placeholder when the release needed no values edits. |
| `<from>-to-<to>-gemeente-specific.md` | Findings that apply to one gemeente/environment only. Mostly empty; filled in if and when something comes up during rollouts. |

Consolidated guides (e.g. `4.6.8-to-4.7.6`) fold a range of patch releases into
one document; the granular per-patch notes are kept alongside for reference.
Which guides form the official path — and which are reference-only — is
defined in [`_UPGRADING.md`](_UPGRADING.md).

## Adding a new upgrade guide

For a new release `<new>` with predecessor `<prev>`:

1. Bump `charts/podiumd/Chart.yaml` and pin the new images in
   `charts/podiumd/values.yaml` (tag + digest).
2. Scaffold the guide with the `/upgrade-notes <prev>-to-<new>` skill →
   `_UPGRADE_PATHS/<prev>-to-<new>-upgrade.md`. Checklist first, details below;
   link app-specific runbooks from `apps/<app>/` instead of inlining them.
3. Create the companions in `_UPGRADE_PATHS/`:
   - `<prev>-to-<new>-values-deltas.md` — full key-by-key reference, or the
     placeholder text used by the existing placeholders when no gemeente
     values change.
   - `<prev>-to-<new>-gemeente-specific.md` — copy the empty template from any
     existing `*-gemeente-specific.md`.
4. Generate the image manifest with `/images-manifest <new>` →
   `images/images-<new>.yaml` (skip when the release changes no images — note
   that in `_UPGRADING.md` instead).
5. Register the hop in [`_UPGRADING.md`](_UPGRADING.md): the operator
   "Which guide do I read?" table **and** the maintainer official-path table.
6. Verify: `/verify-image-digests`, `/helm-dupecheck`, `/helm-lint`, and a
   relative-link check over `docs/`.
