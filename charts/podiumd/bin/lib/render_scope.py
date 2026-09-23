"""Shared infrastructure for every check that operates on a full `helm
template` render: scoping a finding to this chart's own templates/ vs. a
vendored sub-chart, classifying a vendored sub-chart as a "friendly"
partner vendor worth per-item detail, splitting/mapping the render back to
its source templates, the common grouped-findings printer, and — for a
caller that needs to know whether a given dependency (or nested
dependency) actually renders anything at all right now, not just
whether it's vendored on disk — rendered_chart_paths. Used by
check_render (verify-podiumd), check_yamllint/check_kubeconform/
check_shellcheck/check_kube_score (lib/checks/*.py), and (rendered_chart_
paths specifically) check_subchart_image_visibility (lib.
checks.digest_pinning) and list-podiumd-images."""

import re

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lib.chart.release_baseline_basics import load_yaml
from lib.chart.values_tree_primitives import values_key_of
from lib.procutil import run
from lib.settings import helm_repos_urls_by_alias
from lib.settings import vendor_classification_chart_overrides
from lib.settings import vendor_classification_keywords

CHART_NAME = "podiumd"

OWN_TEMPLATES_PREFIX = "podiumd/templates/"


def lint_args_for(chart_dir: Path):
    """The extra `helm template`/`helm lint` args needed to render chart_dir
    with its own ci/lint-values.yaml overrides, e.g. ["-f", ".../ci/
    lint-values.yaml"] — every render/lint/check command in this toolchain
    uses this SAME result so they all validate against the same values
    instead of the chart's bare, aspirational defaults. Returns [] (with a
    printed warning) if no ci/lint-values.yaml exists."""
    lint_values = chart_dir / "ci" / "lint-values.yaml"
    if lint_values.is_file():
        return ["-f", str(lint_values)]
    print("WARNING: no ci/lint-values.yaml found — linting with bare defaults only")
    return []


_render_cache = {}


def render_chart(chart_dir: Path, extra_args: list):
    """Run `helm template <CHART_NAME> <chart_dir> <extra_args>`. Returns
    the raw subprocess result; every caller decides for itself what a
    non-zero returncode means and how to report it.

    Memoized in-process, keyed on (str(chart_dir), tuple(extra_args)) —
    `extra_args` is an ordinary list at every call site, not hashable on
    its own, so the tuple conversion happens here rather than pushing it
    onto every caller. verify-podiumd's own check_subchart_image_
    visibility/check_shared_image_usage/check_release_secret_size all
    call this with the EXACT same chart_dir/extra_args (verify-podiumd's
    own already-computed lint_args_for(chart_dir) result — confirmed,
    not assumed), so within one verify-podiumd run they now share a
    SINGLE real `helm template` subprocess instead of three independent
    ones. A genuine failure (non-zero returncode) is cached too, not
    just success — calling again with the identical args would
    deterministically fail the same way, and verify-podiumd runs once
    per process and exits, so there's no long-running-process staleness
    concern to worry about here. No "force fresh" escape hatch: nothing
    today needs one, since every existing caller already shares the
    same args on purpose.

    Not used by the existing check_render/check_yamllint/check_kubeconform/
    check_shellcheck/check_kube_score — each of those has its own inline
    `run(["helm", "template", ...])` call that its own test suite mocks via
    `monkeypatch.setattr(<that check's module>, "run", ...)`, relying on
    the call living in that module's own globals. Routing them through this
    function instead would resolve `run` via lib.render_scope's globals,
    silently breaking that mocking — out of scope for a change those checks
    didn't ask for. New callers (e.g. render-podiumd) are free to use
    this directly."""
    key = (str(chart_dir), tuple(extra_args))
    if key in _render_cache:
        return _render_cache[key]
    result = run(["helm", "template", CHART_NAME, str(chart_dir), *extra_args], capture_output=True, text=True)
    _render_cache[key] = result
    return result


def report_largest_templates(rendered_text: str, top_n: int):
    """Print the top_n templates in `rendered_text` (a full `helm template`
    render) by rendered line count, attributed via each "# Source: <path>"
    annotation — a diagnostic aid for spotting which template is bloating
    a render. Prints nothing if rendered_text has no "# Source:" lines at
    all (e.g. an empty or failed render)."""
    source_re = re.compile(r"^# Source: (.+)$")
    counts = Counter()
    current = None
    for line in rendered_text.splitlines():
        m = source_re.match(line)
        if m:
            current = m.group(1)
        elif current:
            counts[current] += 1

    if not counts:
        return
    print("Largest rendered templates (by line count):")
    for path, n in counts.most_common(top_n):
        print(f"  {n:6d}  {path}")


# The full chart-tree directory a "# Source: <path>" annotation (or any
# other text embedding the same "<tree>/templates/<file>" shape, e.g. a
# helm error message) belongs to — e.g. "podiumd/charts/openinwoner/
# charts/eck-operator" out of ".../charts/openinwoner/charts/
# eck-operator/templates/x.yaml". The ONE place this parsing happens:
# rendered_chart_paths (below) keeps the FULL path — only the full path
# can tell a top-level dependency apart from a same-named NESTED one at
# any depth (e.g. openinwoner's own bundled "eck-operator" vs. the
# separate top-level "eck-operator" dependency) — while report_errors_
# by_subchart/chart_name_from_source only ever want the LEAF chart name
# (the last path segment) for their own per-chart counting/grouping.
CHART_TREE_PATH_RE = re.compile(r"([A-Za-z0-9_./\-]+)/templates/")


def chart_tree_paths(text: str):
    """Every distinct chart_tree_path match in `text` (a full render, or
    an error-output blob with one or more embedded "<tree>/templates/
    ..." paths) — in match order, duplicates included; callers reduce
    as fits their own purpose (report_errors_by_subchart counts by leaf
    name, rendered_chart_paths keeps the full paths as a set)."""
    return CHART_TREE_PATH_RE.findall(text)


def report_errors_by_subchart(error_text: str):
    """Print a per-sub-chart count of `error_text`'s embedded "<tree>/
    templates/..." paths (see chart_tree_paths), grouped by leaf chart
    name — lets a caller facing a wall of validator errors see at a
    glance which vendored sub-chart most of them belong to. Prints
    nothing if no chart-tree path appears in error_text at all."""
    counts = Counter(path.rsplit("/", 1)[-1] for path in chart_tree_paths(error_text))
    if not counts:
        return
    print("Errors by sub-chart:")
    for chart, n in counts.most_common():
        print(f"  {chart}: {n}")


def chart_name_from_source(source: str | None):
    """The leaf chart name at the end of `source`'s embedded "<tree>/
    templates/..." path (see CHART_TREE_PATH_RE/chart_tree_paths) — e.g.
    "eck-operator" out of ".../charts/openinwoner/charts/eck-operator/
    templates/x.yaml". Falls back to `source` itself (or the literal
    "(unknown source)" if source is falsy/has no such path) so a caller
    always gets some printable label rather than a KeyError."""
    m = CHART_TREE_PATH_RE.search(source or "")
    return m.group(1).rsplit("/", 1)[-1] if m else (source or "(unknown source)")


def rendered_chart_paths(rendered_text: str):
    """Every distinct chart-tree directory that either produced at least
    one rendered resource of its OWN in `rendered_text` (a full `helm
    template` render), or has at least one rendered DESCENDANT — e.g.
    {"podiumd", "podiumd/charts/zac", "podiumd/charts/openinwoner",
    "podiumd/charts/eck-operator", ...}. Parsed from each "# Source:
    <path>" line's own chart_tree_path (see above) — the ONE ground-
    truth oracle for "is chart-tree path X genuinely live right now" —
    PLUS every proper ancestor of each such path (splitting on
    "/charts/" segments): a dependency can be a pure "umbrella" chart
    with no templates/ of its own at all, bundling only NESTED
    dependencies that do all the actual rendering (real, confirmed live
    case: eck-stack/"kiss-eck" itself never appears in any "# Source:"
    line — only its own nested eck-elasticsearch/eck-kibana do — yet
    kiss-eck is very much enabled) — without ancestor inference, such a
    dependency would look indistinguishable from a genuinely-disabled
    one to every consumer below, a real bug caught only by testing
    against the real chart rather than a synthetic one where every
    dependency happens to own at least one template directly.

    Exists because Helm's condition:/tags: mechanism (on a Chart.yaml
    dependency directly, or transitively — a NESTED dependency's own
    "tags:" entry in ITS OWN Chart.yaml, or a nested dependency's own
    "condition:" overridden at "<parent>.<nested>.enabled" in podiumd's
    values.yaml) can leave a real-looking image/version default sitting
    inert in a vendored sub-chart's own values.yaml with NOTHING ever
    actually rendering it — e.g. openinwoner's own bundled eck-operator
    (globally disabled via ITS OWN Chart.yaml "tags: [eck-operator.
    enabled]", set false in podiumd's own top-level values.yaml "tags:"
    block) or any Maykin chart's own bundled bitnami/redis (same "tags:"
    mechanism, disabled the same way). Asking Helm itself what actually
    rendered — rather than re-implementing its own condition/tags
    precedence rules by hand — avoids a real risk of subtle bugs and
    Helm-version drift for a comparatively rare, easy-to-get-wrong
    algorithm (confirmed the hard way: even reasoning through a single
    2-dependency example by hand took several wrong turns before landing
    on the right answer via a real `helm template` render).

    Ancestor inference never widens the set beyond genuinely-live
    subtrees: a SIBLING or descendant path (e.g. openinwoner's own
    disabled nested eck-operator, a sibling of its own enabled nested
    eck-elasticsearch) is never added just because another child of the
    same parent happens to render — only actual ancestors of an
    actually-rendered path are added.

    Used by lib.checks.digest_pinning.check_subchart_image_visibility and
    list-podiumd-images to gate a finding/entry/row on whether its own
    owning dependency (or nested dependency — see lib.chart.
    resolve_subchart_default) genuinely renders right now, instead of
    just being vendored on disk."""
    paths = set(chart_tree_paths(rendered_text))
    ancestors = set()
    for path in paths:
        segments = path.split("/charts/")
        for depth in range(2, len(segments)):
            ancestors.add("/charts/".join(segments[:depth]))
    return paths | ancestors


def resolve_dependency_repo(repository: str, required_repos: dict):
    """`repository` (a Chart.yaml dependency's `repository:` field), with
    an "@alias" resolved to its real URL via `required_repos` (see
    lib.settings.helm_repos_urls_by_alias) — anything else (a plain
    https:// URL, an oci:// registry ref, a "file://" local dependency)
    passes through unchanged."""
    if repository.startswith("@"):
        return required_repos.get(repository[1:], repository)
    return repository


def friendly_vendor_charts(chart_dir: Path):
    """Chart name -> vendor label, for every Chart.yaml dependency whose
    (resolved) repository matches a vendor_classification.keywords entry
    (see lib.settings.vendor_classification_keywords — vendored sub-charts
    from these upstream orgs are close/collaborative dependencies, Dutch
    govtech partners in the same "common ground" ecosystem this repo
    lives in, worth seeing individual findings for even though this repo
    still can't directly fix their code; matched case-insensitively as a
    substring of the dependency's resolved repository, an "@alias" first
    resolved via required_repos since e.g. "@zac" itself doesn't contain
    "infonl" — only its resolved URL does; every other vendored sub-chart
    — elastic, redis-operator, keycloak-operator, openbao, ... — stays
    aggregate-count-only: harder to act on, not worth the extra detail),
    plus the vendor_classification.chart_overrides exceptions that can't
    be derived that way (see lib.settings.
    vendor_classification_chart_overrides — e.g. "kiss" can't be derived
    from its own Chart.yaml repository field: KISS (oci://ghcr.io/
    klantinteractie-servicesysteem) is developed by ICATT (org
    "icatt-menselijk-digitaal" on GitHub/GHCR — see docs/apps/kiss/
    kiss-BASICS.md and the podiumd-adapter image repository), but neither
    appears in KISS's own repository URL, only in prose/its own
    sub-chart's image override), plus any "file://" dependency — a local
    sub-chart living in this same monorepo (e.g. mi-data) isn't a
    "vendor" at all and is trivially fixable here, so it gets the same
    per-item visibility. Chart name is the dependency's alias if it has
    one, else its name — matching how Helm names the charts/<name>/
    directory a "# Source:" path is rooted at, and how chart_overrides is
    keyed (matching chart_name_from_source)."""
    required_repos = helm_repos_urls_by_alias(chart_dir)
    keywords = vendor_classification_keywords(chart_dir)
    chart_overrides = vendor_classification_chart_overrides(chart_dir)

    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    deps = chart_yaml.get("dependencies", [])
    dep_chart_names = {values_key_of(dep) for dep in deps}

    # Only apply an override for a chart that's actually a dependency here
    # — otherwise a name collision with some unrelated future dependency
    # would silently inherit an override meant for a specific chart.
    mapping = {name: vendor for name, vendor in chart_overrides.items() if name in dep_chart_names}
    for dep in deps:
        chart_name = values_key_of(dep)
        repo = resolve_dependency_repo(dep.get("repository", ""), required_repos)
        if repo.startswith("file://"):
            mapping[chart_name] = "Local"
            continue
        for keyword, vendor in keywords.items():
            if keyword in repo.lower():
                mapping[chart_name] = vendor
                break
    return mapping


def build_line_sources(rendered_text: str):
    """Map each 1-based line number in a full `helm template` render to the
    most recent preceding "# Source: <path>" comment, so a yamllint finding
    (which only knows line numbers) can be attributed back to the template
    file that produced it."""
    sources = {}
    current = None
    for i, line in enumerate(rendered_text.splitlines(), 1):
        if line.startswith("# Source: "):
            current = line[len("# Source: ") :].strip()
        sources[i] = current
    return sources


# kind/version/name only — kubeconform's JSON output carries no line number
# or originating-file info per resource (unlike yamllint), so scoping own
# vs. vendored has to happen BEFORE validation: split the render into
# separate per-scope YAML streams and run the tool once per stream.
SOURCE_DOC_SPLIT_RE = re.compile(r"(?m)^---\n(?=# Source: )")


def split_rendered_by_source(rendered_text: str):
    """Split a full `helm template` render into (source, doc_text) pairs,
    one per "# Source: <path>" block — each doc_text keeps its own leading
    "---\\n# Source: ...\\n" header, so any subset of the pairs can be
    concatenated back into a smaller, still-valid multi-document YAML
    stream (used to validate this chart's own templates and its vendored
    sub-charts as separate runs)."""
    docs = SOURCE_DOC_SPLIT_RE.split(rendered_text)
    result = []
    for doc in docs:
        m = re.match(r"# Source: (.+)\n", doc)
        if m:
            result.append((m.group(1).strip(), f"---\n{doc}"))
    return result


def build_resource_locations(rendered_text: str):
    """Map (kind, namespace, name) -> the 1-based line number where that
    resource's manifest begins (the line right after its own "# Source:"
    comment) in the full multi-document `helm template` render — a
    debugging aid for kubeconform/kube-score findings, neither of which
    carries a line number of its own (only kind/name, and kubeconform's
    JSON doesn't even have namespace — see resource_line). namespace is
    "" for a resource that renders with none set on it (this chart is
    installed into one namespace via `helm install -n`, so most resources
    have no templated "namespace:" field at all — but ~50 do in this
    chart's own render today, so it can't just be ignored)."""
    lines = rendered_text.splitlines()
    marker_indices = [i for i, line in enumerate(lines) if line.startswith("# Source: ")]
    locations = {}
    for pos, start in enumerate(marker_indices):
        end = marker_indices[pos + 1] - 1 if pos + 1 < len(marker_indices) else len(lines)
        doc_lines = lines[start + 1 : end]
        if doc_lines and doc_lines[-1].strip() == "---":
            doc_lines = doc_lines[:-1]
        try:
            parsed = yaml.safe_load("\n".join(doc_lines))
        except yaml.YAMLError:  # noqa: S112 -- not a YAML resource, has no location to record
            continue
        if not isinstance(parsed, dict):
            continue
        kind = parsed.get("kind")
        metadata = parsed.get("metadata") or {}
        name = metadata.get("name")
        if not kind or not name:
            continue
        namespace = metadata.get("namespace") or ""
        locations[(kind, namespace, name)] = start + 2  # 1-based line right after "# Source:"
    return locations


def resource_line(locations: dict, kind: str, name: str | None, namespace: str | None = None):
    """Look up a resource's rendered-line hint from build_resource_locations's
    map. With namespace known (kube-score's own object_name gives one),
    matches exactly. Without it (kubeconform's JSON has no namespace
    field), falls back to matching on (kind, name) alone — but only when
    that's unambiguous across every namespace the same kind/name might
    render into; otherwise returns None rather than risk pointing at the
    wrong one."""
    if namespace is not None:
        return locations.get((kind, namespace, name))
    candidates = {line for (k, _ns, n), line in locations.items() if k == kind and n == name}
    return candidates.pop() if len(candidates) == 1 else None


def print_grouped_findings(findings: list, key_fn, item_fn, label_fn, items_label: str = "line(s)"):
    """Shared grouping printer for check_yamllint/check_kubeconform/
    check_shellcheck/check_kube_score: the same root cause (e.g. a
    duplicated label key) typically shows up once per resource, not once
    overall — group by key_fn and list the occurrences (item_fn) one per
    line under the group's own heading, so N near-identical hits print as
    a handful of headings instead of a wall of repeats (and each
    location list stays readable instead of one giant comma-joined
    line)."""
    groups = {}
    for finding in findings:
        groups.setdefault(key_fn(finding), []).append(finding)
    for key, group in groups.items():
        count = f" x{len(group)}" if len(group) > 1 else ""
        print(f"  {label_fn(key)}{count}")
        print(f"      {items_label}:")
        for f in group:
            print(f"        {item_fn(f)}")


@dataclass
class VendorBucketScan:
    """A completed render + tool pass over the chart, as check_kubeconform
    and check_shellcheck report it: the rendered-line lookup (locations),
    the friendly-vendor map (for the report's label text), and the
    findings split into own / vendored-friendly / vendored-other."""

    locations: object
    vendor_map: dict
    own_real: list
    vendored_friendly: list
    vendored_other: list


@dataclass
class RenderedDocs:
    """The rendered chart split for a render + tool check: the
    rendered-line lookup (see build_resource_locations) and the
    (source, text) docs (see split_rendered_by_source)."""

    locations: object
    docs: list


def render_chart_docs(chart_dir: Path, extra_args: list[str]) -> tuple[RenderedDocs | None, str | None]:
    """(RenderedDocs, None) for the rendered chart, or (None, error) if
    helm template fails."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return None, "helm template failed to render"
    return RenderedDocs(build_resource_locations(result.stdout), split_rendered_by_source(result.stdout)), None


def scan_rendered_chart(
    chart_dir: Path,
    extra_args: list[str],
    own_findings: Callable[[list[tuple[str, str]]], tuple[list[Any] | None, str | None]],
    vendored_findings: Callable[
        [list[tuple[str, str]], dict[str, str]], tuple[list[Any] | None, list[Any] | None, str | None]
    ],
) -> tuple[VendorBucketScan | None, str | None]:
    """Render the chart and run one tool over it, as check_kubeconform and
    check_shellcheck do. own_findings(own_docs) returns (own_real, error);
    vendored_findings(vendored_docs, vendor_map) returns
    (vendored_friendly, vendored_other, error). Returns (VendorBucketScan,
    None), or (None, error) on the first render or tool failure."""
    rendered, error = render_chart_docs(chart_dir, extra_args)
    if rendered is None:
        return None, error
    own_docs = [(s, t) for s, t in rendered.docs if s.startswith(OWN_TEMPLATES_PREFIX)]
    vendored_docs = [(s, t) for s, t in rendered.docs if not s.startswith(OWN_TEMPLATES_PREFIX)]
    own_real, error = own_findings(own_docs)
    if own_real is None:
        return None, error
    vendor_map = friendly_vendor_charts(chart_dir)
    vendored_friendly, vendored_other, error = vendored_findings(vendored_docs, vendor_map)
    if vendored_friendly is None or vendored_other is None:
        return None, error
    return VendorBucketScan(rendered.locations, vendor_map, own_real, vendored_friendly, vendored_other), None


def scan_outcome(own_real: list, vendored_friendly: list, vendored_other: list) -> tuple[bool, str]:
    """(passed, detail) for a render + tool check: it passes only without
    own findings; vendored findings are reported, never failing."""
    detail = f"{len(own_real)} real (own), {len(vendored_friendly)} partner-vendor, {len(vendored_other)} other-vendor"
    return not own_real, detail


def print_own_findings_heading(tool: str, count: int) -> None:
    """The heading above a render + tool check's own-template findings."""
    print(f"Found {count} real {tool} issue(s) in this chart's own templates (not cosmetic — these fail the check):")


def print_partner_findings_heading(tool: str, count: int) -> None:
    """The heading above a render + tool check's partner-vendored findings."""
    print(
        f"Found {count} {tool} issue(s) in partner-maintained vendored sub-chart(s) "
        f"(reported for visibility, never a failure):"
    )


def print_other_vendor_summary(tool: str, count: int, chart_count: int) -> None:
    """The one-line summary of a render + tool check's other-vendor findings."""
    print(
        f"{count} {tool} finding(s) across {chart_count} other vendored sub-chart(s) "
        f"(outside this repo's scope, not shown, never a failure)"
    )
