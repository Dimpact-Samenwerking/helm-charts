# PodiumD upgrade guides

This directory holds the per-hop upgrade guides and the per-release image
manifests (folder layout: [`_README.MD`](_README.MD)). The first half of this
page is for **operators** performing an upgrade; everything under
[For chart maintainers](#for-chart-maintainers) is about producing releases and
can be skipped when deploying.

## How to upgrade — three steps

1. **Find your current version**: `helm -n podiumd list` (chart column), or
   the pinned chart version in your environment's deploy configuration.
2. **Look up your row** in the table below and read the guide(s) in order —
   the whole guide, once, before touching anything.
3. **Then, per environment**, work through the **per-environment checklist**
   at the top of the guide. The checklist is the repeatable part; the guide
   body is the explanation behind each item.

## Which guide do I read?

Upgrade one hop at a time, in order. Each guide covers exactly one hop.

| You are on | Read, in this order |
|---|---|
| 4.8.4 | [`4.8.4-to-4.8.5-upgrade.md`](_UPGRADE_PATHS/4.8.4-to-4.8.5-upgrade.md) |
| 4.8.3 | [`4.8.3-to-4.8.4-upgrade.md`](_UPGRADE_PATHS/4.8.3-to-4.8.4-upgrade.md) |
| 4.8.2 | [`4.8.2-to-4.8.3-upgrade.md`](_UPGRADE_PATHS/4.8.2-to-4.8.3-upgrade.md) |
| 4.8.1 | [`4.8.1-to-4.8.2-upgrade.md`](_UPGRADE_PATHS/4.8.1-to-4.8.2-upgrade.md) |
| 4.7.8 | [`4.7.8-to-4.8.0-upgrade.md`](_UPGRADE_PATHS/4.7.8-to-4.8.0-upgrade.md) |
| 4.7.7 | [`4.7.7-to-4.7.8-upgrade.md`](_UPGRADE_PATHS/4.7.7-to-4.7.8-upgrade.md) → then the 4.8.0 guide |
| 4.7.6 | [`4.7.6-to-4.7.7-upgrade.md`](_UPGRADE_PATHS/4.7.6-to-4.7.7-upgrade.md) → [`4.7.7-to-4.7.8-upgrade.md`](_UPGRADE_PATHS/4.7.7-to-4.7.8-upgrade.md) → then the 4.8.0 guide |
| 4.7.0 – 4.7.5 | [`4.6.8-to-4.7.6-upgrade.md`](_UPGRADE_PATHS/4.6.8-to-4.7.6-upgrade.md) (start at your version) → then the 4.7.7 and 4.7.8 patch guides → the 4.8.0 guide |
| 4.6.8 | [`4.6.8-to-4.7.6-upgrade.md`](_UPGRADE_PATHS/4.6.8-to-4.7.6-upgrade.md) → then the 4.7.7 and 4.7.8 patch guides → the 4.8.0 guide |
| 4.6.6 | two equivalent routes to 4.7.3 — [see below](#environments-on-466) — then continue up the path |
| 4.6.4 | [`4.6.4-to-4.6.8-upgrade.md`](_UPGRADE_PATHS/4.6.4-to-4.6.8-upgrade.md) → 4.7.6 guide → and continue up the path |
| 4.5.16 | [`4.5.16-to-4.6.4-upgrade.md`](_UPGRADE_PATHS/4.5.16-to-4.6.4-upgrade.md) → and continue up the path |
| 4.5.15 | [`4.5.15-to-4.5.16-upgrade.md`](_UPGRADE_PATHS/4.5.15-to-4.5.16-upgrade.md) → and continue up the path |

### Each guide has companions

| Companion | What it is for |
|---|---|
| [`_UPGRADE_PATHS/<from>-to-<to>-values-deltas.md`](_UPGRADE_PATHS/) | Every gemeente `podiumd.yml` key to add/change/remove (one per hop, placeholder when a release needed no values edits) — keep it open next to the values file while editing |
| [`_UPGRADE_PATHS/<from>-to-<to>-gemeente-specific.md`](_UPGRADE_PATHS/) | Findings that apply to one gemeente/environment only (one per hop; mostly empty until something comes up) — check it for your gemeente before deploying |
| [`_UPGRADE_PATHS/<from>-to-<to>-operators-crds.md`](_UPGRADE_PATHS/) | Operator and CRD additions/upgrades for the hop (keycloak-operator, redis-operator, eck-operator) — **only exists when the hop touches an operator or CRDs**; read it before the deploy, CRD steps often must run first |
| `images/images-<ver>.yaml` | The ACR-mirror image set for the hop — hand it to SSC-Hosting before the deploy |
| Deep-dives linked from the guide | One-time or high-risk procedures too large for the hop guide, e.g. [`migrating-to-eck-stack.md`](apps/elastic/migrating-to-eck-stack.md) (4.8.0) |

### Environments on 4.6.6

4.6.6 is a supported source baseline. From 4.6.6 there are two equivalent routes
to 4.7.3 — pick one:

| Route | Guides |
|---|---|
| **Direct jump** | [`4.6.6-to-4.7.3-upgrade.md`](_UPGRADE_PATHS/4.6.6-to-4.7.3-upgrade.md) (one document) |
| **Two smaller hops** | [`4.6.6-to-4.6.8-upgrade.md`](_UPGRADE_PATHS/4.6.6-to-4.6.8-upgrade.md) → [`4.6.8-to-4.7.3-upgrade.md`](_UPGRADE_PATHS/4.6.8-to-4.7.3-upgrade.md) |

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
- From **4.6.8 through 4.7.8** it stays on stable `2.1.2`; at **4.8.0** it moves
  to `2.3.1`.

Always pin `openinwoner.image.tag` to a stable version. If you see `2.1.2-rc1`
anywhere in an environment values file, fix it.

---

# For chart maintainers

Everything below is about **producing** releases (guides, manifests, pins) —
not needed when deploying one.

## Official upgrade path

```
4.5.15 ─▶ 4.5.16 ─▶ 4.6.4 ─▶ 4.6.8 ─▶ 4.7.3 ─▶ 4.7.4 ─▶ 4.7.5 ─▶ 4.7.6 ─▶ 4.7.7 ─▶ 4.7.8 ─▶ 4.8.0
```

Each hop has exactly **one** upgrade guide and a matching image manifest (the
ACR-mirror set for that hop):

| Hop | Upgrade guide | Image manifest (ACR mirror set) |
|---|---|---|
| 4.5.15 → 4.5.16 | [`4.5.15-to-4.5.16-upgrade.md`](_UPGRADE_PATHS/4.5.15-to-4.5.16-upgrade.md) | [`images/images-4.5.16.yaml`](images/images-4.5.16.yaml) |
| 4.5.16 → 4.6.4  | [`4.5.16-to-4.6.4-upgrade.md`](_UPGRADE_PATHS/4.5.16-to-4.6.4-upgrade.md)  | [`images/images-4.6.4.yaml`](images/images-4.6.4.yaml) |
| 4.6.4 → 4.6.8   | [`4.6.4-to-4.6.8-upgrade.md`](_UPGRADE_PATHS/4.6.4-to-4.6.8-upgrade.md)   | [`images/images-4.6.8.yaml`](images/images-4.6.8.yaml) |
| 4.6.8 → 4.7.6   | [`4.6.8-to-4.7.6-upgrade.md`](_UPGRADE_PATHS/4.6.8-to-4.7.6-upgrade.md)   | 4.7 chain: [`images-4.7.0`](images/images-4.7.0.yaml) · [`4.7.1`](images/images-4.7.1.yaml) · [`4.7.2`](images/images-4.7.2.yaml) · [`4.7.3`](images/images-4.7.3.yaml) · [`4.7.4`](images/images-4.7.4.yaml) · [`4.7.5`](images/images-4.7.5.yaml) |
| 4.7.6 → 4.7.7   | [`4.7.6-to-4.7.7-upgrade.md`](_UPGRADE_PATHS/4.7.6-to-4.7.7-upgrade.md)   | [`images/images-4.7.7.yaml`](images/images-4.7.7.yaml) |
| 4.7.7 → 4.7.8   | [`4.7.7-to-4.7.8-upgrade.md`](_UPGRADE_PATHS/4.7.7-to-4.7.8-upgrade.md)   | — (no image changes) |
| 4.7.8 → 4.8.0   | [`4.7.8-to-4.8.0-upgrade.md`](_UPGRADE_PATHS/4.7.8-to-4.8.0-upgrade.md)   | [`images/images-4.8.0.yaml`](images/images-4.8.0.yaml) |
| 4.8.3 → 4.8.4   | [`4.8.3-to-4.8.4-upgrade.md`](_UPGRADE_PATHS/4.8.3-to-4.8.4-upgrade.md)   | [`images/images-4.8.4.yaml`](images/images-4.8.4.yaml) |
| 4.8.4 → 4.8.5   | [`4.8.4-to-4.8.5-upgrade.md`](_UPGRADE_PATHS/4.8.4-to-4.8.5-upgrade.md)   | [`images/images-4.8.5.yaml`](images/images-4.8.5.yaml) |

> The 4.6.4 → 4.6.8 and 4.6.8 → 4.7.6 guides are **consolidated**: each folds
> several intermediate releases into one document so an operator reads one
> guide per hop instead of chasing a chain of patch-level notes. For the
> 4.6.8 → 4.7.6 hop the granular per-release notes (4.7.0→4.7.1 … 4.7.5→4.7.6)
> are kept alongside for reference; 4.7.6 itself adds no image bumps (there is
> no `images-4.7.6.yaml`).
>
> **4.7.7** (Open Zaak 1.27.2 → 1.27.3) and **4.7.8** (`OPENZAAK_PORT` uwsgi
> workaround, no image changes) are small patch stepping stones with their own
> guides. `images-4.8.0.yaml` is cumulative from 4.7.6, so it also covers
> environments that skipped the 4.7.7 mirror update.

## What each hop requires

For every release you upgrade **to**, four things must exist and agree:

1. **`Chart.yaml`** — `version` and `appVersion` bumped to the new release.
2. **`values.yaml`** — image pins (`tag` + `digest`) for every new/changed image.
3. **`<prev>-to-<new>-upgrade.md`** — the operator-facing guide for the hop
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
- For the 4.6.8 → 4.7.6 hop the 4.7.x chain manifests are kept individually
  (`images-4.7.0` … `images-4.7.5`); read together they cover the full hop.
- `images-4.8.0.yaml` is cumulative from 4.7.6 (includes the 4.7.7 Open Zaak
  bump; 4.7.8 added no images), so it also covers environments coming from
  4.7.6 or 4.7.7.

## Intermediate / reference guides (NOT the official path)

These are kept for reference but are **not** stepping stones — do not build the
official path out of them:

| File | Why it's kept |
|---|---|
| [`4.6.0-to-4.6.4-upgrade.md`](_UPGRADE_PATHS/4.6.0-to-4.6.4-upgrade.md) | Alternate entry point for environments starting at 4.6.0 (the official path enters 4.6.4 via 4.5.16). |
| [`4.6.8-to-4.7.3-upgrade.md`](_UPGRADE_PATHS/4.6.8-to-4.7.3-upgrade.md) | Shorter consolidated hop that stops at **4.7.3** (subset of the official 4.6.8 → 4.7.6 guide); referenced by the 4.6.6 two-hop route. |
| [`4.7.0-to-4.7.1-upgrade.md`](_UPGRADE_PATHS/4.7.0-to-4.7.1-upgrade.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.6 guide). |
| [`4.7.1-to-4.7.2-upgrade.md`](_UPGRADE_PATHS/4.7.1-to-4.7.2-upgrade.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.6 guide). |
| [`4.7.2-to-4.7.3-upgrade.md`](_UPGRADE_PATHS/4.7.2-to-4.7.3-upgrade.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.6 guide). |
| [`4.7.3-to-4.7.4-upgrade.md`](_UPGRADE_PATHS/4.7.3-to-4.7.4-upgrade.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.6 guide). |
| [`4.7.4-to-4.7.5-upgrade.md`](_UPGRADE_PATHS/4.7.4-to-4.7.5-upgrade.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.6 guide). |
| [`4.7.5-to-4.7.6-upgrade.md`](_UPGRADE_PATHS/4.7.5-to-4.7.6-upgrade.md) | Granular 4.7.x patch note (folded into the 4.6.8 → 4.7.6 guide). |
| [`4.6.5-to-4.7.0-values-deltas.md`](_UPGRADE_PATHS/4.6.5-to-4.7.0-values-deltas.md) | Full values add/change/remove table for the 4.7.0 jump. |
| [`4.7.8-to-4.8.0-values-deltas.md`](_UPGRADE_PATHS/4.7.8-to-4.8.0-values-deltas.md) | Full values add/change/remove table for the 4.8.0 jump (ZAC 5.0.1 breaking changes + ITA medewerker). |
| [`4.8.1-to-4.8.2-gemeente-specific.md`](_UPGRADE_PATHS/4.8.1-to-4.8.2-gemeente-specific.md#zac--brp-protocollering-configuration-per-gemeente) | ZAC BRP protocollering vendor reference (iConnect, eServices, 2Secure/EnableU) — ZAC 5.0.1. |

The 4.7.x granular notes are intentionally retained for now; once the 4.7/4.8 line
closes they can be retired in favour of the consolidated guides.

## Adding a new release

1. Bump `charts/podiumd/Chart.yaml` (`version` + `appVersion`) and pin images in
   `charts/podiumd/values.yaml`.
2. `/images-manifest <new>` → writes `images/images-<new>.yaml` (delta vs the
   previous release; digests fetched via `/fetch-image-digest`). Skip when the
   release changes no images.
3. `/upgrade-notes <prev>-to-<new>` → scaffolds the upgrade guide. Also create
   the companions in `_UPGRADE_PATHS/`: `<prev>-to-<new>-values-deltas.md`
   (placeholder text when no gemeente values change),
   `<prev>-to-<new>-gemeente-specific.md` (empty template), and — only when the
   release adds or upgrades an operator or CRDs —
   `<prev>-to-<new>-operators-crds.md`. See [`_README.MD`](_README.MD).
4. Verify: `/verify-image-digests`, `/helm-dupecheck`, `/helm-lint`.
5. If the release becomes a new official-path stepping stone, add a row to the
   path table above and make its image manifest cumulative vs the previous
   stepping stone (see [above](#image-manifests-are-cumulative-on-the-official-path)).
