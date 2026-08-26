"""Verifies every "image: {tag: ...}" block in this chart's own
values.yaml (see lib.upgradedoc.find_image_tag_paths — structural, finds
a tag regardless of whether it already carries a digest, unlike
lib.image_digests.scan_digest_pins which only ever sees ones that
already do) has its tag digest-pinned ("<version>@sha256:<64-hex>") —
the convention this chart uses everywhere else specifically so a tag can
never silently drift to a different image underneath a floating version
string, and so lib.image_digests' own duplicate/drift check and
release-table.csv's image_basename resolution (both regex/text-based)
can actually see the pin at all.

Two known exceptions:
- keycloak-operator's own "operator.image" field uses the adfinis
  keycloak-operator chart's own convention instead — a separate sibling
  "sha:" field the chart's own template appends onto the tag at render
  time ("repository:tag@sha256:{{ .sha }}"). Embedding @sha256 directly
  in "tag" there would produce an invalid double digest — see the
  values.yaml comment above that field. podiumd doesn't override "sha"
  there at all (inherits the vendored chart's own default, confirmed by
  hand against the live registry manifest to be correct for the
  currently-pinned tag) — the sibling "sha:" only ever gets set in
  podiumd's own values.yaml when overriding a stale default, so a
  follow-up structural check here can't tell "not set, correct default"
  apart from "not set, no default at all" without vendoring the
  sub-chart's own values.yaml (a genuinely different, heavier check than
  this one), so this path is exempted outright instead.
- omc's own image can't be digest-pinned at all — its values.yaml
  comment says the OMC subchart itself can't handle a digest-pinned
  tag; the tag must contain ONLY the version."""
import re

from lib.chart import load_yaml
from lib.upgradedoc import find_image_tag_paths

# "@sha256:<64 hex chars>" at the end of a tag value — the same shape
# lib.image_digests.DIGEST_PIN_RE requires, checked here as a suffix
# match since we already have the tag value in hand rather than a raw
# line to regex.
DIGEST_SUFFIX_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

# (dotted path, as the tuple find_image_tag_paths itself yields) for
# every field that intentionally does NOT embed a digest in its own
# "tag" — see this module's docstring for why.
EXEMPT_PATHS = {
    ("keycloak-operator", "operator"),
    ("omc",),
}


def check_digest_pinning(chart_dir):
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "0 pin(s), 0 unpinned"

    values = load_yaml(values_path) or {}
    images = list(find_image_tag_paths(values))

    missing = [(path, tag) for path, tag in images
               if path not in EXEMPT_PATHS and not DIGEST_SUFFIX_RE.search(tag)]

    if not missing:
        print(f"OK: all {len(images)} image tag(s) in values.yaml are digest-pinned "
              f"({len(EXEMPT_PATHS)} exempt)")
        return True, f"{len(images)} pin(s), 0 unpinned"

    print(f"Found {len(missing)} image tag(s) not digest-pinned "
          f"(missing \"@sha256:<64 hex chars>\"):")
    for path, tag in sorted(missing):
        print(f"  {'.'.join(path)}.image.tag: {tag!r}")

    return False, f"{len(missing)}/{len(images)} image(s) not digest-pinned"
