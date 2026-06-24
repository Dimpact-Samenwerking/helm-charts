# Upgrade guide: PodiumD 4.6.6 → 4.6.8

> **Consolidated guide.** This hop folds the intermediate release 4.6.7. The
> only functional change between 4.6.6 and 4.6.8 is the Open Inwoner image. See
> [`UPGRADING.md`](UPGRADING.md) for the full upgrade path.
>
> **Open Inwoner:** this hop moves the Open Inwoner image from `2.1.1` to the
> **stable `2.1.2`** release. The transient `2.1.2-rc1` release candidate that
> 4.6.7 briefly carried is **skipped** — never pin `openinwoner.image.tag` to
> `2.1.2-rc1` on the official upgrade path.

## Changes

### Open Inwoner 2.1.1 → 2.1.2 (stable)

The Open Inwoner image is updated from `2.1.1` to the **stable** `2.1.2` upstream release, carrying the DRT-557 fix ([#306](https://github.com/Dimpact-Samenwerking/helm-charts/pull/306)).

> **Do not use `2.1.2-rc1`.** Release 4.6.7 briefly pinned the `2.1.2-rc1`
> release candidate; 4.6.8 promotes it to the stable `2.1.2`. The official
> upgrade path skips the release candidate entirely — always pin
> `openinwoner.image.tag` to the stable `2.1.2`.

#### Action required

No action required. The ACR mirror must mirror the `maykinmedia/open-inwoner:2.1.2` tag and digest (see [`docs/images/images-4.6.8.yaml`](images/images-4.6.8.yaml)).

---

## Component version bumps (chart defaults — no action needed in env values)

| Component | 4.6.6 | 4.6.8 |
|---|---|---|
| openinwoner (Open Inwoner image) | 2.1.1 | 2.1.2 (stable) |

> Open Inwoner `2.1.2-rc1` is **not** a version on the upgrade path. 4.6.7
> carried it transiently; the official path goes 2.1.1 → stable 2.1.2.

---

For the full list of new and changed images in this release, see
[docs/images/images-4.6.8.yaml](images/images-4.6.8.yaml). That manifest is
cumulative vs 4.6.4, so it also lists `referentielijsten-api`, `open-beheer`
and `omc` — those are already mirrored if you are on 4.6.6, and re-mirroring
them is harmless.
