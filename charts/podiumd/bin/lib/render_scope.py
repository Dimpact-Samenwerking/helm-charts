"""Shared helpers for checks on a full `helm template` render: own vs.
vendored scoping, partner-vendor classification, mapping render output
back to source templates, grouped-findings printing, and which
(nested) dependencies actually render."""

import re

from collections import Counter
from collections.abc import Callable
from collections.abc import Hashable
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.procutil import RunResult
from lib.procutil import run
from lib.settings import helm_repos_urls_by_alias
from lib.settings import vendor_chart_overrides
from lib.settings import vendor_classification_keywords
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlValue
from lib.yaml_types import is_yaml_mapping
from lib.yaml_types import is_yaml_value

CHART_NAME = "podiumd"

OWN_TEMPLATES_PREFIX = "podiumd/templates/"


def lint_args_for(chart_dir: Path) -> list[str]:
    """`helm template`/`helm lint` args applying chart_dir's
    ci/lint-values.yaml, so every check validates the same values. [] with a
    warning if the file doesn't exist."""
    lint_values = chart_dir / "ci" / "lint-values.yaml"
    if lint_values.is_file():
        return ["-f", str(lint_values)]
    print("WARNING: no ci/lint-values.yaml found — linting with bare defaults only")
    return []


# (chart_dir, extra_args) of one render_chart call.
type RenderCacheKey = tuple[str, tuple[str, ...]]

_render_cache: dict[RenderCacheKey, RunResult] = {}


def render_chart(chart_dir: Path, extra_args: list[str]) -> RunResult:
    """Run `helm template <CHART_NAME> <chart_dir> <extra_args>` and return
    the raw result; callers interpret the returncode.

    Memoized per process on (chart_dir, extra_args), failures included, so
    checks sharing the same args share one render. check_render/
    check_yamllint/check_kubeconform/check_shellcheck/check_kube_score keep
    their own `run` call because their tests monkeypatch `run` in their
    own module."""
    key = (str(chart_dir), tuple(extra_args))
    if key in _render_cache:
        return _render_cache[key]
    result = run(["helm", "template", CHART_NAME, str(chart_dir), *extra_args], capture_output=True, text=True)
    _render_cache[key] = result
    return result


def report_largest_templates(rendered_text: str, top_n: int):
    """Print the top_n templates of a render by line count, attributed via
    "# Source:" lines. Prints nothing if there are none."""
    source_re = re.compile(r"^# Source: (.+)$")
    counts: Counter[str] = Counter()
    current = None
    for line in rendered_text.splitlines():
        source_match = source_re.match(line)
        if source_match:
            current = source_match.group(1)
        elif current:
            counts[current] += 1

    if not counts:
        return
    print("Largest rendered templates (by line count):")
    for path, line_count in counts.most_common(top_n):
        print(f"  {line_count:6d}  {path}")


# Chart-tree directory before "/templates/" in a "# Source:" path or helm
# error, e.g. "podiumd/charts/openinwoner/charts/eck-operator". The full path
# is needed to tell a nested dependency from a same-named top-level one.
CHART_TREE_PATH_RE = re.compile(r"([A-Za-z0-9_./\-]+)/templates/")


def chart_tree_paths(text: str) -> list[str]:
    """All CHART_TREE_PATH_RE matches in `text`, in order, duplicates
    included."""
    return CHART_TREE_PATH_RE.findall(text)


def report_errors_by_subchart(error_text: str):
    """Print error counts per leaf sub-chart name, from the chart-tree paths
    in `error_text`. Prints nothing if there are none.

    Pass helm's stderr only: a failed `helm template --debug` still prints
    every rendered resource to stdout, so every chart would count."""
    counts = Counter(path.rsplit("/", 1)[-1] for path in chart_tree_paths(error_text))
    if not counts:
        return
    print("Errors by sub-chart:")
    for chart, error_count in counts.most_common():
        print(f"  {chart}: {error_count}")


def chart_name_from_source(source: str | None) -> str:
    """Leaf chart name of `source`'s chart-tree path, e.g. "eck-operator";
    falls back to `source` or "(unknown source)"."""
    path_match = CHART_TREE_PATH_RE.search(source or "")
    return path_match.group(1).rsplit("/", 1)[-1] if path_match else (source or "(unknown source)")


def rendered_chart_paths(rendered_text: str) -> set[str]:
    """Chart-tree paths that rendered at least one resource in a full
    render, plus all their ancestors, e.g. {"podiumd",
    "podiumd/charts/zac", ...}.

    Ancestors are added because an umbrella chart without templates of its
    own (e.g. eck-stack) otherwise looks disabled. Siblings of rendered
    paths are never added.

    Asking Helm what rendered avoids re-implementing its condition:/tags:
    precedence, which can leave an image default inert in a vendored
    sub-chart (e.g. openinwoner's bundled eck-operator, disabled via
    tags)."""
    source_lines = "\n".join(line for line in rendered_text.splitlines() if line.startswith("# Source: "))
    paths = set(chart_tree_paths(source_lines))
    ancestors: set[str] = set()
    for path in paths:
        segments = path.split("/charts/")
        ancestor = segments[0]
        for segment in segments[1:-1]:
            ancestor = f"{ancestor}/charts/{segment}"
            ancestors.add(ancestor)
    return paths | ancestors


def resolve_dependency_repo(repository: str, required_repos: dict[str, str]) -> str:
    """A Chart.yaml `repository:` with an "@alias" resolved via
    required_repos; anything else is returned unchanged."""
    if repository.startswith("@"):
        return required_repos.get(repository[1:], repository)
    return repository


def friendly_vendor_charts(chart_dir: Path) -> dict[str, str]:
    """Chart name (alias or name) -> vendor label for dependencies whose
    findings are shown per item: partner vendors whose resolved repository
    contains a vendor_classification keyword (case-insensitive; "@alias"
    resolved first), vendor_classification.chart_overrides for charts the
    URL can't identify (e.g. kiss), and "Local" for file:// dependencies.
    Other vendored charts stay count-only."""
    required_repos = helm_repos_urls_by_alias(chart_dir)
    keywords = vendor_classification_keywords(chart_dir)
    chart_overrides = vendor_chart_overrides(chart_dir)

    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    dep_chart_names = {values_key_of(dep) for dep in deps}

    # Only apply an override for a chart that's actually a dependency here
    # — otherwise a name collision with some unrelated future dependency
    # would silently inherit an override meant for a specific chart.
    mapping = {name: vendor for name, vendor in chart_overrides.items() if name in dep_chart_names}
    for dep in deps:
        vendor = _repository_vendor(resolve_dependency_repo(dep.get("repository", ""), required_repos), keywords)
        if vendor is not None:
            mapping[values_key_of(dep)] = vendor
    return mapping


def _repository_vendor(repo: str, keywords: dict[str, str]) -> str | None:
    """The vendor label of a resolved repository: "Local" for file://, else the first keyword it contains."""
    if repo.startswith("file://"):
        return "Local"
    lowered = repo.lower()
    return next((vendor for keyword, vendor in keywords.items() if keyword.lower() in lowered), None)


def build_line_sources(rendered_text: str) -> dict[int, str | None]:
    """Map each 1-based render line to its preceding "# Source:" path, so
    line-only findings (yamllint) can be attributed to a template."""
    sources: dict[int, str | None] = {}
    current: str | None = None
    for line_number, line in enumerate(rendered_text.splitlines(), 1):
        if line.startswith("# Source: "):
            current = line[len("# Source: ") :].strip()
        sources[line_number] = current
    return sources


# kubeconform output has no line/file per resource, so own vs. vendored is
# split before validation (see split_rendered_by_source).
# (kind, namespace, name) -> 1-based rendered line; see build_resource_locations.
ResourceLocations = dict[tuple[str, str, str], int]
# (source, doc_text) of one "# Source:" block; see split_rendered_by_source.
type RenderedDoc = tuple[str, str]

SOURCE_DOC_SPLIT_RE = re.compile(r"(?m)^---\n(?=# Source: )")


def split_rendered_by_source(rendered_text: str) -> list[RenderedDoc]:
    """Split a render into (source, doc_text) pairs per "# Source:" block.
    Each doc_text keeps its "---" header, so any subset concatenates into a
    valid YAML stream."""
    docs = SOURCE_DOC_SPLIT_RE.split(rendered_text)
    result: list[RenderedDoc] = []
    for doc in docs:
        source_match = re.match(r"# Source: (.+)\n", doc)
        if source_match:
            result.append((source_match.group(1).strip(), f"---\n{doc}"))
    return result


# Workload kinds and the path from the resource to its pod spec.
POD_SPEC_PATHS = {
    "Pod": ("spec",),
    "Deployment": ("spec", "template", "spec"),
    "StatefulSet": ("spec", "template", "spec"),
    "DaemonSet": ("spec", "template", "spec"),
    "ReplicaSet": ("spec", "template", "spec"),
    "Job": ("spec", "template", "spec"),
    "CronJob": ("spec", "jobTemplate", "spec", "template", "spec"),
}


@dataclass(frozen=True)
class RenderedContainer:
    """One container of a rendered workload, with its pod spec and where it came from."""

    source: str
    kind: str
    name: str
    namespace: str | None
    pod_spec: YamlMapping
    container: YamlMapping
    init: bool


def _pod_spec(resource: YamlMapping) -> YamlMapping | None:
    path = POD_SPEC_PATHS.get(str(resource.get("kind")))
    node: object = resource
    for key in path or ():
        node = node.get(key) if isinstance(node, dict) else None
    return node if path and is_yaml_mapping(node) else None


def rendered_containers(docs: Sequence[tuple[str, str]]) -> list[RenderedContainer]:
    """Every container and init container of every rendered workload, in render order.

    `docs` is split_rendered_by_source's (source, doc_text) list.
    """
    containers: list[RenderedContainer] = []
    for source, doc in docs:
        for resource in _doc_resources(doc):
            if is_yaml_mapping(resource):
                containers.extend(_workload_containers(source, resource))
    return containers


def _doc_resources(doc: str) -> list[object]:
    """The YAML documents in `doc`; [] when it isn't YAML, so it has no containers to report."""
    try:
        return list(yaml.safe_load_all(doc))
    except yaml.YAMLError:
        return []


def _workload_containers(source: str, resource: YamlMapping) -> list[RenderedContainer]:
    """rendered_containers for one resource; [] when it is not a workload."""
    pod_spec = _pod_spec(resource)
    if pod_spec is None:
        return []
    kind = str(resource["kind"])
    name = text_at(resource, "metadata.name") or ""
    namespace = text_at(resource, "metadata.namespace")
    containers: list[RenderedContainer] = []
    for field, init in (("initContainers", True), ("containers", False)):
        items = pod_spec.get(field)
        listed = items if isinstance(items, list) else []
        containers.extend(
            RenderedContainer(source, kind, name, namespace, pod_spec, container, init)
            for container in listed
            if is_yaml_mapping(container)
        )
    return containers


def build_resource_locations(rendered_text: str) -> ResourceLocations:
    """Map (kind, namespace, name) to the 1-based line where the resource
    starts in the render, for tools without line numbers. namespace is ""
    when unset (most resources; some set it explicitly)."""
    lines = rendered_text.splitlines()
    marker_indices = [index for index, line in enumerate(lines) if line.startswith("# Source: ")]
    locations: ResourceLocations = {}
    ends = [next_start - 1 for next_start in marker_indices[1:]] + [len(lines)]
    for start, end in zip(marker_indices, ends, strict=True):
        kind, namespace, name = _block_identity(lines[start + 1 : end])
        if kind and name:
            locations[(kind, namespace or "", name)] = start + 2  # 1-based line right after "# Source:"
    return locations


def _block_identity(doc_lines: list[str]) -> tuple[str | None, str | None, str | None]:
    """resource_identity of one "# Source:" block's lines, without a trailing "---" separator."""
    if doc_lines and doc_lines[-1].strip() == "---":
        doc_lines = doc_lines[:-1]
    parsed = parse_rendered_doc("\n".join(doc_lines))
    return (None, None, None) if parsed is None else resource_identity(parsed)


def parse_rendered_doc(doc_text: str) -> YamlValue | None:
    """One rendered doc parsed, or None when it is empty or not YAML (not a resource)."""
    try:
        parsed = yaml.safe_load(doc_text)
    except yaml.YAMLError:
        return None
    return parsed if parsed is not None and is_yaml_value(parsed) else None


def resource_identity(parsed: YamlValue) -> tuple[str | None, str | None, str | None]:
    """(kind, namespace or "", name) of a single-object doc; all None otherwise, so no resource_line lookup."""
    if not isinstance(parsed, dict):
        return None, None, None
    return text_at(parsed, "kind"), text_at(parsed, "metadata.namespace") or "", text_at(parsed, "metadata.name")


def resource_line(
    locations: ResourceLocations, kind: str | None, name: str | None, namespace: str | None = None
) -> int | None:
    """A resource's rendered line. Exact with namespace; without it
    (kubeconform), matches on (kind, name) only if unambiguous, else
    None."""
    if kind is None or name is None:
        return None
    if namespace is not None:
        return locations.get((kind, namespace, name))
    candidates = {
        line
        for (located_kind, _ns, located_name), line in locations.items()
        if located_kind == kind and located_name == name
    }
    return candidates.pop() if len(candidates) == 1 else None


def print_grouped_findings[FindingT, GroupKeyT: Hashable](
    findings: Sequence[FindingT],
    key_fn: Callable[[FindingT], GroupKeyT],
    item_fn: Callable[[FindingT], object],
    label_fn: Callable[[GroupKeyT], object],
    items_label: str = "line(s)",
):
    """Print findings grouped by key_fn with one item_fn line each, since
    one root cause usually repeats once per resource."""
    groups: dict[GroupKeyT, list[FindingT]] = {}
    for finding in findings:
        groups.setdefault(key_fn(finding), []).append(finding)
    for key, group in groups.items():
        count = f" x{len(group)}" if len(group) > 1 else ""
        print(f"  {label_fn(key)}{count}")
        print(f"      {items_label}:")
        for finding in group:
            print(f"        {item_fn(finding)}")


@dataclass
class VendorBucketScan[OwnFindingT, VendoredFindingT]:
    """A render + tool pass: line lookup, friendly-vendor map, and findings
    split into own / vendored-friendly / vendored-other."""

    locations: ResourceLocations
    vendor_map: dict[str, str]
    own_real: list[OwnFindingT]
    vendored_friendly: list[VendoredFindingT]
    vendored_other: list[VendoredFindingT]


@dataclass
class RenderedDocs:
    """The rendered chart split for a render + tool check: the
    rendered-line lookup (see build_resource_locations) and the
    (source, text) docs (see split_rendered_by_source)."""

    locations: ResourceLocations
    docs: list[RenderedDoc]


def render_chart_docs(chart_dir: Path, extra_args: list[str]) -> tuple[RenderedDocs | None, str | None]:
    """(RenderedDocs, None) for the rendered chart, or (None, error) if
    helm template fails."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return None, "helm template failed to render"
    return RenderedDocs(build_resource_locations(result.stdout), split_rendered_by_source(result.stdout)), None


# (findings or None, error) of a check tool run over own docs.
type OwnFindingsResult[ResultT] = tuple[list[ResultT] | None, str | None]
# (friendly, other or None, error) of a check tool run over vendored docs.
type VendoredFindingsResult[ResultT] = tuple[list[ResultT] | None, list[ResultT] | None, str | None]
type OwnFindingsRun[ResultT] = Callable[[list[RenderedDoc]], OwnFindingsResult[ResultT]]
type VendoredFindingsRun[ResultT] = Callable[[list[RenderedDoc], dict[str, str]], VendoredFindingsResult[ResultT]]
# (scan or None, error) of scan_rendered_chart.
type ScanResult[OwnT, VendoredT] = tuple[VendorBucketScan[OwnT, VendoredT] | None, str | None]


def scan_rendered_chart[OwnFindingT, VendoredFindingT](
    chart_dir: Path,
    extra_args: list[str],
    own_findings: OwnFindingsRun[OwnFindingT],
    vendored_findings: VendoredFindingsRun[VendoredFindingT],
) -> ScanResult[OwnFindingT, VendoredFindingT]:
    """Render the chart and run one tool over it, as check_kubeconform and
    check_shellcheck do. own_findings(own_docs) returns (own_real, error);
    vendored_findings(vendored_docs, vendor_map) returns
    (vendored_friendly, vendored_other, error). Returns (VendorBucketScan,
    None), or (None, error) on the first render or tool failure."""
    rendered, error = render_chart_docs(chart_dir, extra_args)
    if rendered is None:
        return None, error
    own_docs = [doc for doc in rendered.docs if doc[0].startswith(OWN_TEMPLATES_PREFIX)]
    vendored_docs = [doc for doc in rendered.docs if not doc[0].startswith(OWN_TEMPLATES_PREFIX)]
    own_real, error = own_findings(own_docs)
    if own_real is None:
        return None, error
    vendor_map = friendly_vendor_charts(chart_dir)
    vendored_friendly, vendored_other, error = vendored_findings(vendored_docs, vendor_map)
    if vendored_friendly is None or vendored_other is None:
        return None, error
    return VendorBucketScan(rendered.locations, vendor_map, own_real, vendored_friendly, vendored_other), None


def scan_outcome(
    own_real: Sequence[object], vendored_friendly: Sequence[object], vendored_other: Sequence[object]
) -> tuple[bool, str]:
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
