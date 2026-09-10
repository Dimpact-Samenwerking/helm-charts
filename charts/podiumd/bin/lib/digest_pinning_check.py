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

Three known exceptions:
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
- keycloak-operator's own "operator.config.keycloakImage" field (the
  default Keycloak SERVER image the operator stamps onto CRs that don't
  specify their own — see lib.chart.COMPONENT_IMAGE_PATHS) uses the
  exact same split "tag:"/"sha:" convention, for the same reason — same
  exemption. Confirmed by hand against the real values.yaml: podiumd
  DOES override this one's own "sha:" explicitly (it deliberately runs a
  Keycloak version ahead of whatever the operator chart's own appVersion
  defaults to), unlike operator.image's inherited default above, but the
  same "not set vs. wrong default" ambiguity this check can't resolve
  structurally still applies.
- omc's own image can't be digest-pinned at all — its values.yaml
  comment says the OMC subchart itself can't handle a digest-pinned
  tag; the tag must contain ONLY the version."""
import re

from lib.chart import get_path, load_yaml, resolve_subchart_default, subchart_template_text, subchart_values
from lib.render_scope import CHART_NAME, render_chart, rendered_chart_paths
from lib.upgradedoc import find_image_tag_paths

# "@sha256:<64 hex chars>" at the end of a tag value — the same shape
# lib.image_digests.DIGEST_PIN_RE requires, checked here as a suffix
# match since we already have the tag value in hand rather than a raw
# line to regex.
DIGEST_SUFFIX_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

# (dotted path, as the tuple find_image_tag_paths itself yields — always
# ending in the image key itself, "image" or an "...Image"-suffixed
# sibling) for every field that intentionally does NOT embed a digest in
# its own "tag" — see this module's docstring for why.
EXEMPT_PATHS = {
    ("keycloak-operator", "operator", "image"),
    ("keycloak-operator", "operator", "config", "keycloakImage"),
    # keycloak.image aliases the above via YAML anchor (repository/tag/
    # sha all shared — see values.yaml's own comment there) and so uses
    # the exact same split shape, not the ordinary embedded-digest one.
    ("keycloak", "image"),
    ("omc", "image"),
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


def subchart_visibility_exempt_reason(scope_key, subpath):
    """The SUBCHART_VISIBILITY_EXEMPT reason string if (scope_key, subpath)
    matches an exempt prefix for that same dependency, else None. Public —
    also reused by lib.dead_values_check to keep the same permanently-
    unreachable subtrees out of ITS findings too, rather than duplicating
    this same prefix-match logic."""
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
        print(f"  {'.'.join(path)}.tag: {tag!r}")

    return False, f"{len(missing)}/{len(images)} image(s) not digest-pinned"


def find_unresolved_subchart_images(chart_dir, deps, own_values, rendered_paths):
    """(scope_key, subpath, tag, already_pinned) for every "<key>: {tag:
    ...}" block ("image", or an "...Image"-suffixed sibling — see
    lib.upgradedoc.find_image_tag_paths) found in a vendored dependency's
    OWN default values.yaml (see lib.chart.subchart_values) that podiumd's
    own values.yaml (`own_values`) does NOT override at the corresponding
    path — i.e. an image the check above can never see, since it only
    ever walks podiumd's own values.yaml, not a sub-chart's. `deps` is
    the chart's own Chart.yaml "dependencies" list (a caller that already
    has both `deps`/`own_values` in hand — e.g. lib.image_docs.
    regenerate_images_baseline_manifest — passes them straight through
    rather than this function re-reading Chart.yaml/values.yaml itself;
    check_subchart_image_visibility below reads them fresh from
    `chart_dir` since it has nothing else handy). `scope_key` is the
    dependency's alias (or name) as used in podiumd's own values.yaml;
    `subpath` is the dotted path within that scope, always ending in the
    image key itself (just "image" for the sub-chart's own top-level
    "image:"). A dependency not yet vendored (no .tgz under
    chart_dir/charts/ — see the "Dependencies" step) is silently skipped,
    since there's nothing on disk yet to read; a genuinely un-findable
    default counts the same as no default at all rather than a hard
    error, since Helm itself would fall back to whatever's actually
    vendored at render time regardless of what this scan can parse.

    ALSO includes a block whose own "tag:" is null/missing but which DOES
    have a "repository:" (lib.upgradedoc.find_image_tag_paths's own
    include_null_tags mode) — resolved to `tag`=the dependency's (or, for
    a NESTED dependency, that nested dependency's own — see lib.chart.
    resolve_subchart_default) Chart.yaml "appVersion", the exact version
    Helm's own ".tag | default .Chart.AppVersion" template convention
    would use. Skipped outright if that can't be resolved to anything
    real (never fabricated).

    `rendered_paths` (see lib.render_scope.rendered_chart_paths, from a
    real `helm template` render) gates EVERY finding — real tag or
    resolved-default alike — on whether its own owning chart-tree path
    (lib.chart.resolve_subchart_default's own first half; usually dep's
    own top-level path, but a NESTED dependency's own path when the
    field actually belongs to one of dep's OWN declared Chart.yaml
    dependencies instead) actually rendered at least one resource right
    now. A genuinely-vendored default sitting in a sub-chart's own
    values.yaml doesn't mean Helm ever installs it — Helm's own
    condition:/tags: mechanism (directly on dep, or transitively on one
    of ITS OWN nested dependencies) can leave it entirely inert, e.g.
    openinwoner's own bundled eck-operator (globally disabled via ITS
    OWN Chart.yaml "tags:", set in podiumd's own top-level values.yaml)
    or zaakbrug's own condition-disabled "staging" block.

    Also silently drops a finding whose top-level values key is never
    referenced anywhere in that same sub-chart's own templates/ (see
    subchart_template_text) -- e.g. pabc's own "web"/"poller" keys, which
    no template in the pabc chart reads at all: setting a podiumd override
    there would be structurally inert regardless of value, so it is not
    even a judgment call the way SUBCHART_VISIBILITY_EXEMPT's entries are.
    Only applied when templates/ was actually readable (non-None) -- a
    dependency with no readable templates/ at all (an unusually-shaped
    chart, or a test fixture that only vendors values.yaml) can't be told
    apart from "genuinely unreferenced" by an empty haystack, so every
    finding for it is kept instead of silently swallowed (subject to the
    render-gate above either way).

    Deliberately NOT cross-checked against EXEMPT_PATHS above — those
    exempt fields (keycloak-operator.operator, omc) are ones podiumd DOES
    override in its own values.yaml (that's the whole reason they need an
    exemption from the check above), so they already have an own_tag here
    and never show up as unresolved in the first place."""
    findings = []
    for dep in deps:
        scope_key = dep.get("alias") or dep["name"]
        sub_values = subchart_values(chart_dir, dep)
        if sub_values is None:
            continue
        template_text = subchart_template_text(chart_dir, dep)
        for path, tag in find_image_tag_paths(sub_values, include_null_tags=True):
            subpath = ".".join(path)
            own_image_tag_path = f"{scope_key}.{subpath}.tag"
            if get_path(own_values, own_image_tag_path) is not None:
                continue
            top_level_key = path[0]
            if template_text is not None and not re.search(rf"\b{re.escape(top_level_key)}\b", template_text):
                continue

            chart_tree_path, resolved_version = resolve_subchart_default(chart_dir, dep, CHART_NAME, path)
            if chart_tree_path not in rendered_paths:
                continue

            if tag is None:
                if resolved_version is None:
                    continue
                findings.append((scope_key, subpath, resolved_version, False))
            else:
                findings.append((scope_key, subpath, tag, bool(DIGEST_SUFFIX_RE.search(tag))))
    return findings


def _print_subchart_image_finding(scope_key, subpath, tag, pinned, exempt_reason=None):
    own_image_tag_path = f"{scope_key}.{subpath}.tag"
    marker = "pinned" if pinned else "FLOATING"
    suffix = f" (exempt: {exempt_reason})" if exempt_reason else ""
    print(f"  {own_image_tag_path}: {tag!r} ({marker} in the sub-chart's own default){suffix}")


def check_subchart_image_visibility(chart_dir, extra_args):
    """Report-only: lists every image find_unresolved_subchart_images()
    finds — minus whatever SUBCHART_VISIBILITY_EXEMPT already has a
    reviewed answer for — so a NEW one introduced by a dependency bump
    doesn't silently stay invisible to the pinning discipline the rest of
    this chart follows. Never fails the run (except a render failure
    itself — see below): whether a given sub-chart-default image actually
    warrants a podiumd override (vs. being fine left as dead config, a
    permanently-disabled feature, or a generic default nobody needs to
    touch) is a per-case judgment call this scan can't make on its own; a
    human decides that from the report, once, and it's recorded in
    SUBCHART_VISIBILITY_EXEMPT from then on.

    Every exempt item is still printed by name (with its own reason),
    right alongside the non-exempt findings (or alone, under the "OK"
    line, when there are no non-exempt findings at all) — never just a
    bare count with no way to see which images those are without reading
    SUBCHART_VISIBILITY_EXEMPT in the source.

    Renders via lib.render_scope.render_chart (this check's OWN new need
    for a render — see rendered_chart_paths) to compute the render-gate
    find_unresolved_subchart_images now requires; a render failure here
    fails the step outright (unlike every finding below it, which is
    genuinely report-only) — this check now structurally depends on a
    working render, unlike before."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"
    rendered_paths = rendered_chart_paths(result.stdout)

    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    own_values = load_yaml(chart_dir / "values.yaml") or {}
    all_findings = find_unresolved_subchart_images(chart_dir, chart_yaml.get("dependencies", []), own_values, rendered_paths)
    exempt = [(f, subchart_visibility_exempt_reason(f[0], f[1])) for f in all_findings]
    exempt_findings = [(f, reason) for f, reason in exempt if reason]
    findings = [f for f, reason in exempt if not reason]

    if findings:
        unpinned = [f for f in findings if not f[3]]
        print(f"Found {len(findings)} image(s) defined only in a vendored sub-chart's own "
              f"default values.yaml, with no podiumd override\n"
              f"invisible to the digest-pinning check above ({len(unpinned)} of these use a "
              f"floating tag in that default; {len(exempt_findings)} more already reviewed "
              f"and exempted, see SUBCHART_VISIBILITY_EXEMPT). Not a failure: decide per "
              f"image whether it warrants an override.")
        for scope_key, subpath, tag, pinned in sorted(findings):
            _print_subchart_image_finding(scope_key, subpath, tag, pinned)
    else:
        suffix = f" ({len(exempt_findings)} exempt)" if exempt_findings else ""
        print(f"OK: no sub-chart-default images found without a podiumd override{suffix}")

    if exempt_findings:
        print("Exempt (see SUBCHART_VISIBILITY_EXEMPT for why):")
        for (scope_key, subpath, tag, pinned), reason in sorted(exempt_findings):
            _print_subchart_image_finding(scope_key, subpath, tag, pinned, exempt_reason=reason)

    if not findings:
        return True, f"0 unresolved ({len(exempt_findings)} exempt)" if exempt_findings else "0 unresolved"
    return True, (f"{len(findings)} unresolved ({len(unpinned)} floating tag(s), "
                  f"{len(exempt_findings)} exempt) — report only")
