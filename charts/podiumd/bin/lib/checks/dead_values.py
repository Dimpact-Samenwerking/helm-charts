"""Report-only check for values.yaml leaves that no template (own or vendored) ever reads.

Static grepping can't see reads via `index`/`tpl`/`range` or condition wiring, so each
leaf is set to null via an extra `-f` overlay and the chart re-rendered; a render
structurally identical to the baseline means the leaf is a dead-code candidate.

The baseline is values.yaml + ci/lint-values.yaml with every Chart.yaml dependency
"condition:" forced true (_enable_overlay), so off-by-default dependencies still render.
Internal toggles inside a sub-chart's values (e.g. zaakbrug "staging") are not forced,
so leaves behind them may be reported dead: findings are a human call, never a failure.

Cost control:
1. Top-down: a whole subtree is nulled at once; only one that errors or differs is
   recursed into, level by level.
2. Scoping (_resolve_scope): a key matching a vendored dependency renders that .tgz
   alone (~0.1-0.3s vs ~7s) with its sliced merged values plus "global"; a key matching
   no dependency renders podiumd's own templates alone (_make_own_scope). Any scope
   whose baseline fails falls back to the full chart.

Scoped findings are only candidates: each is re-confirmed against the full chart
(_confirm_against_full_chart), because podiumd's own templates can read a dependency's
values (e.g. keycloak). Dependency "condition:" leaves are excluded up front: a
standalone sub-chart render ignores them, so they always look dead there.

Each BFS level is dispatched to a thread pool from the calling thread (workers never
submit work, so no deadlock). Renders are compared as parsed YAML since Go map `range`
order is random; lists built from map ranges can still differ, but that only hides dead
leaves, never reports a live one.
"""

import concurrent.futures
import copy
import os
import re
import shutil
import tempfile

from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeVar

import yaml

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import ChartYaml
from lib.chart.chart_yaml import chart_dependencies
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.chart_yaml import load_chart_yaml
from lib.chart.pull_and_subchart_resolution import subchart_values
from lib.chart.values_tree_primitives import deep_merge
from lib.chart.values_tree_primitives import mapping_at
from lib.chart.values_tree_primitives import values_key_of
from lib.procutil import run
from lib.render_scope import CHART_NAME
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlShapeError
from lib.yaml_types import YamlValue
from lib.yaml_types import is_yaml_value
from lib.yaml_types import load_yaml_mapping
from lib.yaml_types import yaml_problem

# Each render is a separate CPU-bound `helm template` subprocess.
DEAD_VALUES_MAX_WORKERS = os.cpu_count() or 4


class RenderScope(TypedDict):
    """What one dead-values render runs: `helm template chart_name
    chart_path extra_args -f <overlay>` with base_overlay plus the nulled
    leaves (see _render_with_null_overrides), each leaf path first
    stripped of `strip` leading keys. baseline_docs is that render with
    nothing nulled (None when it failed); temp_dir is set when chart_path
    is a throwaway copy the caller must remove."""

    chart_name: str
    chart_path: Path
    extra_args: list[str]
    base_overlay: YamlMapping
    strip: int
    baseline_docs: list[YamlValue] | None
    temp_dir: NotRequired[Path]


# A values leaf as its key path; a subtree still to search as (scope, its
# path, its node); that plus its candidate leaves; a dead leaf found in a scope.
LeafPath = tuple[str, ...]
FrontierEntry = tuple[RenderScope, LeafPath, YamlValue]
PendingSubtree = tuple[RenderScope, LeafPath, YamlValue, list[LeafPath]]
DeadCandidate = tuple[RenderScope, LeafPath]
RenderFuture = concurrent.futures.Future[list[YamlValue] | None]


def flatten_leaves(node: YamlValue, path: LeafPath = ()) -> Iterator[tuple[LeafPath, YamlValue]]:
    """(path tuple, value) for every leaf under node.

    An empty dict is a leaf; a list is always one leaf (Helm can't override one element).
    """
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from flatten_leaves(value, (*path, key))
    else:
        yield path, node


def _candidate_leaves(
    node: YamlValue, path: LeafPath, exempt_full_paths: AbstractSet[LeafPath] = frozenset()
) -> Iterator[LeafPath]:
    """flatten_leaves(node, path) minus already-null values and exempt_full_paths."""
    for leaf_path, value in flatten_leaves(node, path):
        if value is None or not leaf_path:
            continue
        if leaf_path in exempt_full_paths:
            continue
        yield leaf_path


def candidate_leaf_paths(values: YamlMapping, exempt_full_paths: AbstractSet[LeafPath] = frozenset()) -> list[LeafPath]:
    """Every values.yaml leaf worth null-testing, as a flat list (for the "N checked" count)."""
    return list(_candidate_leaves(values, (), exempt_full_paths))


def _condition_leaf_paths(chart_dir: Path) -> set[LeafPath]:
    """Every Chart.yaml dependency "condition:" as a full leaf path, e.g. ("eck-operator", "enabled").

    Exempt from testing: a standalone sub-chart render ignores its own condition, so it
    always looks dead there and would only be rejected by the slow full-chart pass.
    Nested umbrellas (kiss-eck -> eck-stack) have the same issue one level down, unhandled.
    """
    paths: set[LeafPath] = set()
    for dep in load_chart_dependencies(chart_dir / "Chart.yaml"):
        condition = dep.get("condition")
        if condition:
            paths.add(tuple(condition.split(".")))
    return paths


def _set_path(tree: YamlMapping, path: LeafPath, value: YamlValue):
    """Set `tree[path]` to `value`, creating or replacing non-mapping levels with mappings."""
    node = tree
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def _load_merged_values(chart_dir: Path, extra_args: list[str]) -> YamlMapping:
    """values.yaml deep-merged with every "-f <file>" in extra_args, in order.

    Only for sub-chart scoped overlays, which need a slice of the merged tree that Helm's
    own -f layering can't produce.
    """
    merged = copy.deepcopy(load_yaml_mapping(chart_dir / "values.yaml"))
    for i, arg in enumerate(extra_args):
        if arg == "-f":
            deep_merge(merged, load_yaml_mapping(Path(extra_args[i + 1])))
    return merged


def _dependency_by_key(chart_dir: Path):
    return {values_key_of(dep): dep for dep in load_chart_dependencies(chart_dir / "Chart.yaml")}


def _coalesced_values(chart_dir: Path, merged_values: YamlMapping, dep_by_key: dict[str, ChartDependency]):
    """merged_values with each dependency's vendored defaults merged in under podiumd's override.

    Replicates Helm's coalescing for parent templates reading ".Values.<dep>" (e.g.
    keycloak-operator-servicemonitor-rbac.yaml reads the vendored
    operator.serviceAccount). Only _make_own_scope needs this; the other scopes get it
    from Helm itself.
    """
    coalesced = copy.deepcopy(merged_values)
    for key, dep in dep_by_key.items():
        defaults = subchart_values(chart_dir, dep)
        if defaults is None:
            continue
        with_defaults = copy.deepcopy(defaults)
        deep_merge(with_defaults, mapping_at(coalesced, key))
        coalesced[key] = with_defaults
    return coalesced


def _enable_overlay(chart_dir: Path) -> YamlMapping:
    """A nested dict setting every Chart.yaml dependency "condition:" path to True."""
    overlay: YamlMapping = {}
    for dep in load_chart_dependencies(chart_dir / "Chart.yaml"):
        condition = dep.get("condition")
        if not condition:
            continue
        _set_path(overlay, tuple(condition.split(".")), value=True)
    return overlay


HELM_OUTPUT_SOURCE = "helm template output"


def _parsed_docs(rendered_text: str) -> list[YamlValue]:
    """The non-empty documents of a `helm template` render."""
    docs: list[YamlValue] = []
    for doc in yaml.safe_load_all(rendered_text):
        if doc is None:
            continue
        if not is_yaml_value(doc):
            problem = yaml_problem(doc) or "not YAML data"
            raise YamlShapeError(HELM_OUTPUT_SOURCE, problem)
        docs.append(doc)
    return docs


def _helm_template(chart_name: str, chart_path: Path, extra_args: list[str], overlay_path: Path):
    """The raw `helm template` result, for callers that must inspect stderr."""
    args = ["helm", "template", chart_name, str(chart_path), *extra_args, "-f", str(overlay_path)]
    return run(args, capture_output=True, text=True)


def _render(chart_name: str, chart_path: Path, extra_args: list[str], overlay_path: Path):
    """Parsed render of `chart_name` at `chart_path` with an extra "-f overlay_path", or None on failure."""
    result = _helm_template(chart_name, chart_path, extra_args, overlay_path)
    if result.returncode != 0:
        return None
    return _parsed_docs(result.stdout)


RenderT = TypeVar("RenderT")


def _with_overlay_file(overlay: YamlMapping, render_fn: Callable[[Path], RenderT]) -> RenderT:
    """Call render_fn with `overlay` dumped to a temp file, always removed afterwards."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(overlay, f)
        overlay_path = Path(f.name)
    try:
        return render_fn(overlay_path)
    finally:
        overlay_path.unlink()


def _render_with_null_overrides(scope: RenderScope, relative_paths: list[LeafPath]) -> list[YamlValue] | None:
    """Render `scope` with relative_paths nulled on top of a deep copy of its base_overlay.

    Paths are relative to the scope's own top-level values (see _resolve_scope's "strip").
    The copy is needed because calls run concurrently.
    """
    overlay = copy.deepcopy(scope["base_overlay"])
    for path in relative_paths:
        _set_path(overlay, path, value=None)
    return _with_overlay_file(
        overlay,
        lambda overlay_path: _render(scope["chart_name"], scope["chart_path"], scope["extra_args"], overlay_path),
    )


# Helm names the failing chart two ways (_error_chart_names tries both):
#  - schema validation: a "<chart>:" line per offending chart;
#  - template execution: "execution error at (<path>/templates/...)", where the first
#    "charts/<name>/" segment is the top-level dependency even for nested charts.
_SCHEMA_ERROR_CHART_RE = re.compile(r"^([A-Za-z0-9_.\-]+):$", re.MULTILINE)
_EXECUTION_ERROR_PATH_RE = re.compile(r"execution error at \(([^)]+)\):")
_TOP_LEVEL_CHART_PATH_RE = re.compile(r"charts/([A-Za-z0-9_.\-]+)/")


def _error_chart_names(stderr: str) -> set[str]:
    names: set[str] = set(_SCHEMA_ERROR_CHART_RE.findall(stderr))
    for path in _EXECUTION_ERROR_PATH_RE.findall(stderr):
        chart_match = _TOP_LEVEL_CHART_PATH_RE.search(path)
        if chart_match:
            names.add(chart_match.group(1))
    return names


def _make_full_scope(chart_dir: Path, extra_args: list[str], enable_overlay: YamlMapping) -> RenderScope:
    """The full-chart scope: the fallback for every key and the authority for confirmation.

    base_overlay starts as enable_overlay, since only this render decides which
    dependencies appear. Some forced-on dependencies fail with the CI values (omc schema,
    zaakbrug required guard); as the last resort this render can't just fail, so each
    dependency Helm's error names has its condition dropped (reported once) and the
    render retried. The helm error is printed if a failure can't be attributed.
    """
    overlay = copy.deepcopy(enable_overlay)
    dropped: list[str] = []
    while True:
        result = _with_overlay_file(
            overlay, lambda overlay_path: _helm_template(CHART_NAME, chart_dir, extra_args, overlay_path)
        )
        scope: RenderScope = {
            "chart_name": CHART_NAME,
            "chart_path": chart_dir,
            "extra_args": extra_args,
            "base_overlay": overlay,
            "strip": 0,
            "baseline_docs": None,
        }
        if result.returncode == 0:
            scope["baseline_docs"] = _parsed_docs(result.stdout)
            if dropped:
                print(
                    f"Note: could not force-enable {', '.join(sorted(dropped))} (its own values "
                    f"aren't satisfied by this chart's current CI placeholder values) — tested at "
                    f"its natural, un-forced default instead",
                    flush=True,
                )
            return scope

        failing = (_error_chart_names(result.stderr) & set(overlay)) - set(dropped)
        if not failing:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", flush=True)
            scope["baseline_docs"] = None
            return scope
        for name in failing:
            del overlay[name]
            dropped.append(name)


def _own_template_subchart_refs(chart_dir: Path) -> set[str]:
    """Dependency aliases/names podiumd's own templates reference via ".Subcharts.<name>".

    _make_own_scope must keep these vendored. Read literally from the templates, not guessed.
    """
    templates_dir = chart_dir / "templates"
    if not templates_dir.is_dir():
        return set()
    refs: set[str] = set()
    for path in sorted(templates_dir.rglob("*.yaml")):
        if path.is_file():
            refs.update(re.findall(r"\.Subcharts\.([A-Za-z0-9_-]+)", path.read_text(encoding="utf-8")))
    return refs


# Error when an own template `include`s a named template of a dependency that isn't
# vendored into the render; names the dependency _make_own_scope must add.
_MISSING_TEMPLATE_RE = re.compile(r'no template "([A-Za-z0-9_-]+)\.[A-Za-z0-9_.-]*" associated')


def _build_own_scope_chart(chart_dir: Path, chart_yaml: ChartYaml, kept_deps: list[ChartDependency]):
    """A temp copy of chart_dir without "charts/", with only kept_deps vendored and declared."""
    temp_dir = Path(tempfile.mkdtemp(prefix="dead-values-own-"))
    shutil.copytree(chart_dir, temp_dir, ignore=shutil.ignore_patterns("charts"), dirs_exist_ok=True)
    own_chart_yaml = {k: v for k, v in chart_yaml.items() if k != "dependencies"}
    if kept_deps:
        own_chart_yaml["dependencies"] = kept_deps
        (temp_dir / "charts").mkdir(exist_ok=True)
        for dep in kept_deps:
            tgz_name = f"{dep['name']}-{dep['version']}.tgz"
            src = chart_dir / "charts" / tgz_name
            if src.is_file():
                shutil.copy2(src, temp_dir / "charts" / tgz_name)
    (temp_dir / "Chart.yaml").write_text(yaml.safe_dump(own_chart_yaml), encoding="utf-8")
    (temp_dir / "values.yaml").write_text("{}\n", encoding="utf-8")
    return temp_dir


def _make_own_scope(chart_dir: Path, coalesced_values: YamlMapping) -> RenderScope | None:
    """Scope rendering podiumd's own templates/ alone, for keys matching no dependency.

    base_overlay is the whole coalesced_values tree (own templates can read any key);
    the caller must pass _coalesced_values output or dependency defaults are missing.

    Kept dependencies start from _own_template_subchart_refs and grow on each "no
    template" error, then retry; bounded since the set only grows. None if a render
    still fails otherwise (callers fall back to the full chart). Caller removes
    "temp_dir" once the whole check is done.
    """
    chart_yaml = load_chart_yaml(chart_dir / "Chart.yaml")
    all_deps = chart_dependencies(chart_yaml)
    dep_by_name_or_alias = {values_key_of(dep): dep for dep in all_deps}

    keep = set(_own_template_subchart_refs(chart_dir)) & set(dep_by_name_or_alias)
    while True:
        kept_deps = [dep for dep in all_deps if values_key_of(dep) in keep]
        temp_dir = _build_own_scope_chart(chart_dir, chart_yaml, kept_deps)

        # B023 false positive: render_fn is called synchronously within this iteration.
        result = _with_overlay_file(
            coalesced_values,
            lambda overlay_path: _helm_template(CHART_NAME, temp_dir, [], overlay_path),  # noqa: B023
        )
        if result.returncode == 0:
            return {
                "chart_name": CHART_NAME,
                "chart_path": temp_dir,
                "extra_args": [],
                "base_overlay": coalesced_values,
                "strip": 0,
                "temp_dir": temp_dir,
                "baseline_docs": _parsed_docs(result.stdout),
            }

        missing = (set(_MISSING_TEMPLATE_RE.findall(result.stderr)) & set(dep_by_name_or_alias)) - keep
        shutil.rmtree(temp_dir, ignore_errors=True)
        if not missing:
            print(
                "Note: own-templates-only scope render failed — falling back to full-chart scope "
                "for keys with no Chart.yaml dependency:",
                flush=True,
            )
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", flush=True)
            return None
        keep |= missing


@dataclass
class ScopeResolutionContext:
    """Per-run state shared by every _resolve_scope call (see _build_scan_context)."""

    chart_dir: Path
    merged_values: YamlMapping
    dep_by_key: dict[str, ChartDependency]
    own_scope: RenderScope | None
    full_scope: RenderScope


def _resolve_scope(context: ScopeResolutionContext, key: str) -> RenderScope:
    """The sub-chart scope for `key` if its baseline renders, own_scope if `key` matches no
    dependency, else full_scope. Never raises."""
    dep = context.dep_by_key.get(key)
    if dep is None:
        return context.own_scope if context.own_scope is not None else context.full_scope
    if dep.get("repository", "").startswith("file://"):
        return context.full_scope

    tgz_path = context.chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    if not tgz_path.is_file():
        return context.full_scope

    subtree = context.merged_values.get(key)
    if not isinstance(subtree, dict):
        return context.full_scope

    base_overlay = dict(subtree)
    if "global" in context.merged_values:
        base_overlay["global"] = context.merged_values["global"]

    scope: RenderScope = {
        "chart_name": dep["name"],
        "chart_path": tgz_path,
        "extra_args": [],
        "base_overlay": base_overlay,
        "strip": 1,
        "baseline_docs": None,
    }
    scope["baseline_docs"] = _render_with_null_overrides(scope, [])
    if scope["baseline_docs"] is None:
        return context.full_scope
    return scope


def _pending_subtrees(frontier: list[FrontierEntry], exempt_full_paths: AbstractSet[LeafPath]) -> list[PendingSubtree]:
    """(scope, path, node, leaf_paths) for every frontier entry with a leaf left to test."""
    pending: list[PendingSubtree] = []
    for scope, path, node in frontier:
        leaf_paths = list(_candidate_leaves(node, path, exempt_full_paths))
        if leaf_paths:
            pending.append((scope, path, node, leaf_paths))
    return pending


def _submit_level(
    executor: concurrent.futures.ThreadPoolExecutor, pending: list[PendingSubtree]
) -> dict[RenderFuture, PendingSubtree]:
    return {
        executor.submit(_render_with_null_overrides, scope, [p[scope["strip"] :] for p in leaf_paths]): (
            scope,
            path,
            node,
            leaf_paths,
        )
        for scope, path, node, leaf_paths in pending
    }


def _collect_level_results(
    futures: dict[RenderFuture, PendingSubtree], found: list[DeadCandidate]
) -> tuple[list[FrontierEntry], int]:
    """(next_frontier, resolved count) for one level; dead leaves go to `found`."""
    next_frontier: list[FrontierEntry] = []
    resolved = 0
    for future in concurrent.futures.as_completed(futures):
        scope, path, node, leaf_paths = futures[future]
        docs = future.result()
        if docs is not None and docs == scope["baseline_docs"]:
            found.extend((scope, p) for p in leaf_paths)
            resolved += len(leaf_paths)
        elif len(leaf_paths) > 1 and isinstance(node, dict):
            next_frontier.extend((scope, (*path, key), child) for key, child in node.items())
        else:
            resolved += 1  # single leaf that differed (or errored): not dead, done with it
    return next_frontier, resolved


def _run_dead_value_search(
    executor: concurrent.futures.ThreadPoolExecutor,
    roots: list[FrontierEntry],
    total: int | None = None,
    exempt_full_paths: AbstractSet[LeafPath] = frozenset(),
) -> list[DeadCandidate]:
    """(scope, full_path) for every leaf that looks dead in its scope, searched top-down from `roots`.

    Iterative BFS so workers never submit to the executor. `total` enables per-level
    progress lines; omit it to stay quiet.
    """
    found: list[DeadCandidate] = []
    resolved = 0
    frontier = list(roots)
    level = 0
    while frontier:
        level += 1
        pending = _pending_subtrees(frontier, exempt_full_paths)
        if not pending:
            break

        futures = _submit_level(executor, pending)
        next_frontier, resolved_this_level = _collect_level_results(futures, found)
        resolved += resolved_this_level
        if total is not None:
            print(
                f"  level {level}: {len(pending)} render(s) — {resolved}/{total} leaf(ves) resolved so far "
                f"({len(found)} dead, {len(next_frontier)} subtree(s) still being narrowed down)",
                flush=True,
            )
        frontier = next_frontier
    return found


def _tree_from_paths(paths: list[LeafPath]) -> YamlMapping:
    """A tree whose leaves are exactly `paths` (non-null placeholders), for re-searching them."""
    tree: YamlMapping = {}
    for path in paths:
        _set_path(tree, path, value=True)
    return tree


def _confirm_against_full_chart(
    executor: concurrent.futures.ThreadPoolExecutor, full_scope: RenderScope, candidates: list[LeafPath]
) -> list[LeafPath]:
    """Re-verify scoped candidates against the full chart; full-scope finds need no re-check."""
    if not candidates:
        return []
    tree = _tree_from_paths(candidates)
    roots = [(full_scope, (key,), node) for key, node in tree.items()]
    return [path for _scope, path in _run_dead_value_search(executor, roots, len(candidates))]


def _build_scan_context(chart_dir: Path, extra_args: list[str], full_scope: RenderScope):
    """The ScopeResolutionContext shared by this run's _resolve_scope calls."""
    merged_values = _load_merged_values(chart_dir, extra_args)
    # Use the pruned overlay so the own scope doesn't retry forced-enables already known to break.
    deep_merge(merged_values, full_scope["base_overlay"])
    dep_by_key = _dependency_by_key(chart_dir)

    own_scope = _make_own_scope(chart_dir, _coalesced_values(chart_dir, merged_values, dep_by_key))
    if own_scope is None:
        print("Own-templates-only scope unavailable — falling back to full-chart scope for those keys", flush=True)

    return ScopeResolutionContext(
        chart_dir=chart_dir,
        merged_values=merged_values,
        dep_by_key=dep_by_key,
        own_scope=own_scope,
        full_scope=full_scope,
    )


def _resolve_all_scopes(
    executor: concurrent.futures.ThreadPoolExecutor, context: ScopeResolutionContext, values: YamlMapping
) -> list[FrontierEntry]:
    """(scope, (key,), node) for every top-level values.yaml key,
    resolved concurrently via _resolve_scope."""
    scope_futures = {executor.submit(_resolve_scope, context, key): key for key in values}
    roots: list[FrontierEntry] = []
    for future in concurrent.futures.as_completed(scope_futures):
        key = scope_futures[future]
        roots.append((future.result(), (key,), values[key]))
    return roots


def _print_scope_summary(roots: list[FrontierEntry], context: ScopeResolutionContext):
    scoped_n = sum(1 for scope, _, _ in roots if scope is not context.full_scope and scope is not context.own_scope)
    own_n = sum(1 for scope, _, _ in roots if scope is context.own_scope)
    full_n = sum(1 for scope, _, _ in roots if scope is context.full_scope)
    print(f"  {scoped_n} sub-chart-scoped, {own_n} own-templates-scoped, {full_n} full-chart-scoped", flush=True)


def _search_and_confirm(
    executor: concurrent.futures.ThreadPoolExecutor,
    roots: list[FrontierEntry],
    total: int,
    condition_paths: set[LeafPath],
    full_scope: RenderScope,
) -> list[LeafPath]:
    print("Searching top-down for dead leaves...", flush=True)
    found = _run_dead_value_search(executor, roots, total, condition_paths)
    confirmed = [path for scope, path in found if scope is full_scope]
    to_confirm = [path for scope, path in found if scope is not full_scope]
    if to_confirm:
        print(f"Confirming {len(to_confirm)} candidate(s) against the real full-chart baseline...", flush=True)
    return confirmed + _confirm_against_full_chart(executor, full_scope, to_confirm)


def check_dead_values(chart_dir: Path, extra_args: list[str]):
    """The dead-values sweep. Always returns ok=True; skipped when the baseline render fails."""
    values = load_yaml_mapping(chart_dir / "values.yaml")
    condition_paths = _condition_leaf_paths(chart_dir)
    total = len(candidate_leaf_paths(values, condition_paths))

    print(
        f"Null-testing {total} values.yaml leaf(ves) against the baseline render "
        f"(top-down, per-subchart where possible, up to {DEAD_VALUES_MAX_WORKERS} in parallel)...",
        flush=True,
    )

    full_scope = _make_full_scope(chart_dir, extra_args, _enable_overlay(chart_dir))
    if full_scope["baseline_docs"] is None:
        return True, "skipped — baseline render failed"

    context = _build_scan_context(chart_dir, extra_args, full_scope)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=DEAD_VALUES_MAX_WORKERS) as executor:
            print(f"Resolving render scope for {len(values)} top-level key(s)...", flush=True)
            roots = _resolve_all_scopes(executor, context, values)
            _print_scope_summary(roots, context)

            dead = _search_and_confirm(executor, roots, total, condition_paths, full_scope)
    finally:
        if context.own_scope is not None:
            temp_dir = context.own_scope.get("temp_dir")
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    dead.sort()

    if not dead:
        print(f"OK: no dead values.yaml entries found ({total} checked)")
        return True, f"0/{total} dead"

    print(
        f"Found {len(dead)} values.yaml leaf(ves) whose value never surfaces in the "
        f"rendered chart (nulling it made no difference to the maximal render) — "
        f"report only, a human call whether it's genuinely removable:"
    )
    for path in dead:
        print(f"  {'.'.join(path)}")

    return True, f"{len(dead)}/{total} dead (report only)"
