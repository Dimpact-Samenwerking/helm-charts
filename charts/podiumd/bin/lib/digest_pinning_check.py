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

from lib.chart import get_path, load_yaml, subchart_values
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

# (scope_key, subpath prefix) for every vendored-subchart-default image
# find_unresolved_subchart_images() would otherwise flag, already
# reviewed and confirmed to never warrant a podiumd override — see
# check_subchart_image_visibility. A finding matches if its own subpath
# equals the prefix exactly or starts with "<prefix>.". Scoped per
# dependency rather than a bare rule-name match (e.g. "any 'staging'
# anywhere") so an unrelated future dependency introducing its own,
# differently-motivated "staging" toggle still gets a fresh look instead
# of silently inheriting this one's reasoning.
SUBCHART_VISIBILITY_EXEMPT = {
    ("zaakbrug", "staging"): (
        "permanently disabled by hard Dimpact policy, not just \"not "
        "currently used\": enabling it pulls in the sub-chart's bundled "
        "bitnami/redis transitive dependency, which policy forbids "
        "outright (see the values.yaml comment on zaakbrug.staging, and "
        "commit 85041ad). Anything gated behind this toggle is never "
        "going to be enabled in this chart's use case, so it's never "
        "worth a podiumd override regardless of what upstream changes "
        "about it."
    ),
}


def _subchart_visibility_exempt_reason(scope_key, subpath):
    """The SUBCHART_VISIBILITY_EXEMPT reason string if (scope_key, subpath)
    matches an exempt prefix for that same dependency, else None."""
    for (exempt_scope, exempt_prefix), reason in SUBCHART_VISIBILITY_EXEMPT.items():
        if scope_key == exempt_scope and (subpath == exempt_prefix or subpath.startswith(exempt_prefix + ".")):
            return reason
    return None


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


def find_unresolved_subchart_images(chart_dir):
    """(scope_key, subpath, tag, already_pinned) for every "image: {tag:
    ...}" block found in a vendored dependency's OWN default values.yaml
    (see lib.chart.subchart_values) that podiumd's own values.yaml does
    NOT override at the corresponding path — i.e. an image the check
    above can never see, since it only ever walks podiumd's own
    values.yaml, not a sub-chart's. `scope_key` is the dependency's alias
    (or name) as used in podiumd's own values.yaml; `subpath` is the
    dotted path within that scope ("" for the sub-chart's own top-level
    "image:"). A dependency not yet vendored (no .tgz under
    chart_dir/charts/ — see the "Dependencies" step) is silently skipped,
    since there's nothing on disk yet to read; a genuinely un-findable
    default counts the same as no default at all rather than a hard
    error, since Helm itself would fall back to whatever's actually
    vendored at render time regardless of what this scan can parse.

    Deliberately NOT cross-checked against EXEMPT_PATHS above — those
    exempt fields (keycloak-operator.operator, omc) are ones podiumd DOES
    override in its own values.yaml (that's the whole reason they need an
    exemption from the check above), so they already have an own_tag here
    and never show up as unresolved in the first place."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    own_values = load_yaml(chart_dir / "values.yaml") or {}

    findings = []
    for dep in chart_yaml.get("dependencies", []):
        scope_key = dep.get("alias") or dep["name"]
        sub_values = subchart_values(chart_dir, dep)
        if sub_values is None:
            continue
        for path, tag in find_image_tag_paths(sub_values):
            subpath = ".".join(path)
            own_image_tag_path = f"{scope_key}.{subpath}.image.tag" if subpath else f"{scope_key}.image.tag"
            if get_path(own_values, own_image_tag_path) is None:
                findings.append((scope_key, subpath, tag, bool(DIGEST_SUFFIX_RE.search(tag))))
    return findings


def check_subchart_image_visibility(chart_dir):
    """Report-only: lists every image find_unresolved_subchart_images()
    finds — minus whatever SUBCHART_VISIBILITY_EXEMPT already has a
    reviewed answer for — so a NEW one introduced by a dependency bump
    doesn't silently stay invisible to the pinning discipline the rest of
    this chart follows. Never fails the run — whether a given
    sub-chart-default image actually warrants a podiumd override (vs.
    being fine left as dead config, a permanently-disabled feature, or a
    generic default nobody needs to touch) is a per-case judgment call
    this scan can't make on its own; a human decides that from the
    report, once, and it's recorded in SUBCHART_VISIBILITY_EXEMPT from
    then on."""
    all_findings = find_unresolved_subchart_images(chart_dir)
    exempt_count = sum(1 for f in all_findings if _subchart_visibility_exempt_reason(f[0], f[1]))
    findings = [f for f in all_findings if not _subchart_visibility_exempt_reason(f[0], f[1])]

    if not findings:
        suffix = f" ({exempt_count} exempt)" if exempt_count else ""
        print(f"OK: no sub-chart-default images found without a podiumd override{suffix}")
        return True, f"0 unresolved ({exempt_count} exempt)" if exempt_count else "0 unresolved"

    unpinned = [f for f in findings if not f[3]]
    print(f"Found {len(findings)} image(s) defined only in a vendored sub-chart's own "
          f"default values.yaml, with no podiumd override — invisible to the digest-"
          f"pinning check above ({len(unpinned)} of these use a floating tag in that "
          f"default; {exempt_count} more already reviewed and exempted, see "
          f"SUBCHART_VISIBILITY_EXEMPT). Not a failure: decide per image whether it "
          f"warrants an override.")
    for scope_key, subpath, tag, pinned in sorted(findings):
        own_image_tag_path = f"{scope_key}.{subpath}.image.tag" if subpath else f"{scope_key}.image.tag"
        marker = "pinned" if pinned else "FLOATING"
        print(f"  {own_image_tag_path}: {tag!r} ({marker} in the sub-chart's own default)")

    return True, (f"{len(findings)} unresolved ({len(unpinned)} floating tag(s), "
                  f"{exempt_count} exempt) — report only")
