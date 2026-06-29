# PodiumD upgrade guides

This directory holds the per-hop upgrade guides and the per-release image
manifests. Start here: this page defines the **official upgrade path**, the
files required for each hop, and which guides are reference-only.

## Official upgrade path

```
4.5.15 ─▶ 4.5.16 ─▶ 4.6.4 ─▶ 4.6.8 ─▶ 4.7.3 ─▶ 4.7.4 ─▶ 4.7.5 ─▶ 4.8.0
```

Upgrade one hop at a time, in order. Each hop has exactly **one** upgrade guide
and a matching image manifest (the ACR-mirror set for that hop):

| Hop | Upgrade guide | Image manifest (ACR mirror set) |
|---|---|---|
| 4.5.15 → 4.5.16 | [`upgrade-from-4.5.15-to-4.5.16.md`](upgrade-from-4.5.15-to-4.5.16.md) | [`images/images-4.5.16.yaml`](images/images-4.5.16.yaml) |
| 4.5.16 → 4.6.4  | [`upgrade-from-4.5.16-to-4.6.4.md`](upgrade-from-4.5.16-to-4.6.4.md)  | [`images/images-4.6.4.yaml`](images/images-4.6.4.yaml) |
| 4.6.4 → 4.6.8   | [`upgrade-from-4.6.4-to-4.6.8.md`](upgrade-from-4.6.4-to-4.6.8.md)   | [`images/images-4.6.8.yaml`](images/images-4.6.8.yaml) |
| 4.6.8 → 4.7.3   | [`upgrade-from-4.6.8-to-4.7.3.md`](upgrade-from-4.6.8-to-4.7.3.md)   | 4.7 chain: [`images-4.7.0`](images/images-4.7.0.yaml) · [`4.7.1`](images/images-4.7.1.yaml) · [`4.7.2`](images/images-4.7.2.yaml) · [`4.7.3`](images/images-4.7.3.yaml) |
| 4.7.3 → 4.7.4   | [`upgrade-from-4.7.3-to-4.7.4.md`](upgrade-from-4.7.3-to-4.7.4.md)   | [`images/images-4.7.4.yaml`](images/images-4.7.4.yaml) |
| 4.7.4 → 4.7.5   | [`upgrade-from-4.7.4-to-4.7.5.md`](upgrade-from-4.7.4-to-4.7.5.md)   | [`images/images-4.7.5.yaml`](images/images-4.7.5.yaml) |
| 4.7.5 → 4.8.0   | [`upgrade-from-4.7.5-to-4.8.0.md`](upgrade-from-4.7.5-to-4.8.0.md)   | [`images/images-4.8.0.yaml`](images/images-4.8.0.yaml) |

> The 4.6.4 → 4.6.8 and 4.6.8 → 4.7.3 guides are **consolidated**: each folds
> several intermediate releases into one document so an operator reads one
> guide per hop instead of chasing a chain of patch-level notes.


> **4.7.6 is a parallel patch on the 4.7 line**, not a stepping stone to 4.8.0.
> The path to 4.8.0 goes directly `4.7.5 → 4.8.0`. A 4.7.6 environment is also a
> valid source (4.7.6 only adds OAB documentation/config hardening over 4.7.5;
> nothing 4.8.0 needs to re-apply).


### Environments already on 4.6.6

4.6.6 is a supported source baseline. From 4.6.6 there are two equivalent routes
to 4.7.3 — pick one:

| Route | Guides |
|---|---|
| **Direct jump** | [`upgrade-from-4.6.6-to-4.7.3.md`](upgrade-from-4.6.6-to-4.7.3.md) (one document) |
| **Two smaller hops** | [`upgrade-from-4.6.6-to-4.6.8.md`](upgrade-from-4.6.6-to-4.6.8.md) → [`upgrade-from-4.6.8-to-4.7.3.md`](upgrade-from-4.6.8-to-4.7.3.md) |

The only difference between starting at 4.6.6 vs 4.6.8 is the Open Inwoner image
(`2.1.1` → stable `2.1.2`); everything else is identical. The
[`images-4.6.8.yaml`](images/images-4.6.8.yaml) manifest (cumulative vs 4.6.4)
covers the 4.6.6 → 4.6.8 hop too — it over-lists a few images a 4.6.6
environment already has, which is harmless for an ACR-mirror set.

## ⚠️ Open Inwoner `2.1.2-rc1` — never use

Open Inwoner `2.1.2-rc1` was a release candidate that release 4.6.7 briefly
carried (and 4.7.0 inherited). It is **not part of any official upgrade** and
**must never be pinned**. On the official path:

- At **4.6.8** Open Inwoner is the **stable `2.1.2`** (the 4.6.4 → 4.6.8 guide
  goes `2.1.1` → stable `2.1.2`, skipping the rc).
- From **4.6.8 through 4.7.5** it stays on stable `2.1.2`; at **4.8.0** it moves
  to `2.3.0`.

Always pin `openinwoner.image.tag` to a stable version. If you see `2.1.2-rc1`
anywhere in an environment values file, fix it.

## What each hop requires

For every release you upgrade **to**, four things must exist and agree:

1. **`Chart.yaml`** — `version` and `appVersion` bumped to the new release.
2. **`values.yaml`** — image pins (`tag` + `digest`) for every new/changed image.
3. **`upgrade-from-<prev>-to-<new>.md`** — the operator-facing guide for the hop
   (scaffold it with `/upgrade-notes <prev>-to-<new>`).
4. **`images/images-<new>.yaml`** — the ACR-mirror set: every image new or
   changed in the release, each with a fetched `sha256:` digest (build it with
   `/images-manifest <new>`).

A hop is "ready" only when all four are present and consistent
(`/verify-image-digests`, `/helm-dupecheck`, `/helm-lint`).

### Image manifests are cumulative on the official path

Image manifests are normally a **delta** vs the immediately preceding release.
But the official path **skips** intermediate releases (e.g. 4.6.4 → 4.6.8 jumps
over 4.6.5/4.6.6/4.6.7), so a path-target manifest must be **cumulative vs the
previous stepping stone**:

- [`images-4.6.8.yaml`](images/images-4.6.8.yaml) lists everything new/changed
  since **4.6.4** (not just since 4.6.7).
- For the 4.6.8 → 4.7.3 hop the 4.7.x chain manifests are kept individually
  (`images-4.7.0` … `images-4.7.3`); read together they cover the full hop.

## Intermediate / reference guides (NOT the official path)

These are kept for reference but are **not** stepping stones — do not build the
official path out of them:

| File | Why it's kept |
|---|---|
| [`upgrade-from-4.6.0-to-4.6.4.md`](upgrade-from-4.6.0-to-4.6.4.md) | Alternate entry point for environments starting at 4.6.0 (the official path enters 4.6.4 via 4.5.16). |
| [`upgrade-from-4.7.0-to-4.7.1.md`](upgrade-from-4.7.0-to-4.7.1.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.3 guide). |
| [`upgrade-from-4.7.1-to-4.7.2.md`](upgrade-from-4.7.1-to-4.7.2.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.3 guide). |
| [`upgrade-from-4.7.2-to-4.7.3.md`](upgrade-from-4.7.2-to-4.7.3.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.3 guide). |
| [`upgrade-from-4.7.3-to-4.8.0.md`](upgrade-from-4.7.3-to-4.8.0.md) | Alternate entry point for environments still on 4.7.3 (the official path enters 4.8.0 via 4.7.5). |
| [`values-changes-4.7.0.md`](values-changes-4.7.0.md) | Full values add/change/remove table for the 4.7.0 jump. |
| [`values-changes-4.8.0.md`](values-changes-4.8.0.md) | Full values add/change/remove table for the 4.8.0 jump (ZAC 5.0.1 breaking changes + ITA medewerker). |
| [`zac-brp-protocollering.md`](zac-brp-protocollering.md) | ZAC BRP protocollering vendor reference (iConnect, eServices, 2Secure/EnableU) — ZAC 5.0.1. |

The 4.7.x granular notes are intentionally retained for now; once the 4.7 line
closes they can be retired in favour of the consolidated 4.6.8 → 4.7.3 guide.

## Adding a new release

1. Bump `charts/podiumd/Chart.yaml` (`version` + `appVersion`) and pin images in
   `charts/podiumd/values.yaml`.
2. `/images-manifest <new>` → writes `images/images-<new>.yaml` (delta vs the
   previous release; digests fetched via `/fetch-image-digest`).
3. `/upgrade-notes <prev>-to-<new>` → scaffolds the upgrade guide.
4. Verify: `/verify-image-digests`, `/helm-dupecheck`, `/helm-lint`.
5. If the release becomes a new official-path stepping stone, add a row to the
   path table above and make its image manifest cumulative vs the previous
   stepping stone (see [above](#image-manifests-are-cumulative-on-the-official-path)).
