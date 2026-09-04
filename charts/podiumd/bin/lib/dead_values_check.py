"""Report-only check for values.yaml leaf entries that no template — own
or vendored sub-chart — ever actually reads: "dead code" in values.yaml.
Unlike lib.digest_pinning_check's find_unresolved_subchart_images (which
answers "does a sub-chart default exist that podiumd doesn't override"),
this answers the reverse question: "does podiumd's OWN override of this
key ever change anything at all".

Rather than a static text grep against template sources — which can't
tell a key genuinely read via `.Values.foo.bar` apart from one only ever
reached through `index`/`tpl`/a whole-subtree `range`, and can't tell
whether a key is reachable at all under this chart's OWN condition/
enabled-flag wiring — this renders the real chart with `helm template`
and empirically observes whether a leaf's value ever surfaces in the
output. For every leaf path in podiumd's own values.yaml: override it to
`null` (via an extra `-f` overlay, never touching the real values.yaml
on disk) and re-render; if the rendered manifests come back structurally
IDENTICAL to the baseline render, nothing anywhere ever dereferenced
that value, so it's a dead-code candidate.

"Consider everything always enabled" (this check's own design brief) —
the actual question this check answers is "can this leaf EVER be read,
given what the charts' own templates do", not "does it happen to be
read under today's specific default toggle settings". So the baseline
this renders against is values.yaml + ci/lint-values.yaml (the same
"maximal" values check_lint/check_render/check_image_upgrades/check_cves
already use — every `required` guard satisfied) PLUS every Chart.yaml
dependency's own "condition:" forced to true (see _enable_overlay) —
deterministically, straight from Chart.yaml's own dependencies[].condition
fields, never a name-based guess at which values "look like" a toggle.
Without this, a dependency that's off by default (this chart has quite
a few — real, measured examples: openbao, zaakbrug are BOTH off unless
forced) would never even render, and every leaf under it would look
"dead" for that reason alone rather than because no template anywhere
could ever read it. The one deliberate exception: SUBCHART_VISIBILITY_
EXEMPT's zaakbrug.staging is NOT force-enabled — that's a narrower,
INTERNAL toggle inside the zaakbrug sub-chart's own values (not a
Chart.yaml dependency condition at all), permanently off by hard policy
regardless of what "everything enabled" means elsewhere (see
lib.digest_pinning_check's docstring), so its leaves are excluded from
this check's scope entirely rather than reported as a fresh "dead" find
every time (same exemption check_subchart_image_visibility already
applies, reused here via subchart_visibility_exempt_reason rather than
re-deriving the same prefix-match logic). Any OTHER internal, non-
Chart.yaml-condition toggle inside a sub-chart's own values (this repo
has a few, e.g. objecten's own demo-data flag) is deliberately left
alone — telling a real per-component feature flag apart from an
ordinary boolean config value with no name-based heuristic isn't
something this check tries to do; a leaf gated behind one of those is
the one remaining case the "human call" caveat below covers.

Cost control has two independent halves:

1. Top-down, not per-leaf (see _run_dead_value_search): a whole subtree
   (a top-level component key, or any dict node under it) is null-tested
   as ONE unit first. If that reproduces its own baseline exactly, every
   leaf anywhere under it is confirmed dead in that one render, however
   many there are and however deep — no further recursion needed. Only a
   subtree whose combined render errors (a `required`/schema guard
   tripped by one of its nulled leaves) or differs from baseline gets
   recursed into, one level at a time, narrowing down to just the live
   part of the tree.

2. Per-subchart scoping (see _resolve_scope): rendering the WHOLE
   podiumd chart (all ~25 vendored dependencies — measured at ~7s per
   render on the real chart, vs. ~0.1-0.3s for a single sub-chart alone)
   to test one leaf under, say, "zac" is wasteful — only the zac
   sub-chart's own templates can possibly read a zac.* value (with the
   one known exception below). Where a top-level key matches an actual
   Chart.yaml dependency with a vendored charts/<name>-<version>.tgz on
   disk, this renders THAT sub-chart alone (`helm template <name> <its
   .tgz>`) instead of the full umbrella chart, with a `-f` overlay built
   from podiumd's own merged values (values.yaml + ci/lint-values.yaml,
   replicated in Python via _load_merged_values/_deep_merge — Helm's own
   -f layering can't slice a subset of an already-merged tree, which is
   what a scoped render needs) sliced down to just that key's own
   subtree plus "global" (which Helm always propagates into every
   sub-chart). A sub-chart's own baseline render failing (its
   values.yaml schema, or any other reconstruction gap) just falls back
   to the full-chart scope for that key instead — never treated as
   evidence of anything.

   A top-level key that matches NO Chart.yaml dependency at all (e.g.
   "keycloak", "apiproxy", "global" — real, measured examples: together
   ~15% of this chart's own leaves) has nothing to scope TO the way
   above — but it's still wasteful to pull in all ~25 dependencies just
   to test whether podiumd's OWN templates/*.yaml reference it. See
   _make_own_scope: a temp chart directory — a copy of podiumd's own
   chart with "charts/" (the vendored .tgz's) excluded and Chart.yaml's
   own "dependencies:" list stripped, so Helm never touches any
   sub-chart at all — renders podiumd's OWN templates alone, with the
   FULL merged values as its overlay (not sliced to one key, since
   podiumd's own templates can reference any top-level key). Same
   fallback discipline: a failure here (e.g. a template that needs
   something only a real sub-chart provides) just falls back to the
   full-chart scope, same as a failed sub-chart scope does.

   SAFETY NET: neither scoped render above is ever trusted to make the
   final call, only to narrow the search faster. This matters because at
   least one top-level key in practice is a real, documented exception:
   e.g. "keycloak" — per this chart's own Bitnami-to-Hostzero-Operator
   migration notes — has values read directly by some of podiumd's OWN
   top-level templates/*.yaml (see lib.image_repository_check's
   docstring on "adapter"'s siblings) as well as (historically) a
   vendored dependency's own templates — a leaf like that could look
   "dead" to either scoped render while still being genuinely live in
   the real, full chart. So every candidate either scoped render finds
   is re-verified with one more pass against the REAL, authoritative
   full-chart baseline (_confirm_against_full_chart) before ever being
   reported — reusing the exact same top-down search, just seeded with
   only the candidates (as a small pruned tree) instead of the whole
   chart, and always via the full-chart scope. A candidate already found
   via the full-chart scope in the first place skips this re-check
   (nothing to re-confirm).

Parallelism: every render this module ever issues is fully independent —
its own throwaway temp overlay file, no shared state — so
_run_dead_value_search dispatches an entire level of the top-down walk
(every subtree currently pending a test, across every top-level key and
every scope at once) to a shared ThreadPoolExecutor concurrently, rather
than one `helm template` call at a time. This is an iterative,
level-by-level (BFS) walk driven from the calling thread — never a
worker recursively submitting further work to the same pool — so there
is no risk of the pool's own workers deadlocking waiting on each other.

Structural (parsed multi-doc YAML) comparison, not raw text, is used to
decide "identical to baseline" — Go's `range` over a map has no
guaranteed key order, so two otherwise-identical renders can differ in
map-derived ordering alone; comparing parsed Python objects (dict
equality is order-independent) avoids misreading that noise as a "used"
signal. A remaining, narrower version of the same issue survives this
fix: a template that builds a new LIST by ranging over a map (rather
than rendering the map itself) can still reorder that list's elements
between two otherwise-equivalent renders, and Python list equality does
care about order — so that specific shape can still cost a missed dead-
code finding, but only ever in the safe direction (never a live value
wrongly reported dead).

Progress: with real leaf counts in the thousands and this many render
phases, silence for minutes on end is its own problem — check_dead_values
prints a line at every phase transition (scope resolution, the top-down
search, the confirmation pass), and _run_dead_value_search itself prints
one line per BFS level (how many renders that level took, how many
leaves are resolved so far out of the total, how many are still being
narrowed down) rather than only a single line at the very end.

Never fails regardless of findings — same as check_subchart_image_
visibility/check_image_upgrades/check_cves: whether a candidate is truly
removable (vs. e.g. read only when some internal, non-Chart.yaml-
condition feature flag this check doesn't force on is itself turned on
— see above) is a human's call, not something this scan can decide on
its own."""
import concurrent.futures
import copy
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from lib.chart import load_yaml
from lib.digest_pinning_check import subchart_visibility_exempt_reason
from lib.procutil import run
from lib.render_scope import CHART_NAME

# Every render this module issues is an independent `helm template`
# subprocess (its own temp overlay file, no shared state) competing for
# real CPU like any other child process — bounded by actual cores, not
# an I/O-wait heuristic.
DEAD_VALUES_MAX_WORKERS = os.cpu_count() or 4


def flatten_leaves(node, path=()):
    """(path tuple, value) for every leaf under node — a dict is only a
    leaf itself when empty (nothing to descend into); a list is always
    treated as one leaf (its own elements are never individually
    null-tested — out of scope for this check, and Helm's own YAML merge
    can't override a single list element in isolation anyway); anything
    else (scalar, including None) is a leaf."""
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from flatten_leaves(value, path + (key,))
    else:
        yield path, node


def _candidate_leaves(node, path):
    """flatten_leaves(node, path), minus a value that's already null
    (nulling a null is a no-op — nothing to learn) and any path
    SUBCHART_VISIBILITY_EXEMPT already has a standing, reviewed answer
    for (see this module's docstring)."""
    for leaf_path, value in flatten_leaves(node, path):
        if value is None or not leaf_path:
            continue
        if subchart_visibility_exempt_reason(leaf_path[0], ".".join(leaf_path[1:])):
            continue
        yield leaf_path


def candidate_leaf_paths(values):
    """Every path _candidate_leaves finds in podiumd's own values.yaml
    worth null-testing — the full, flat list (used for the "N checked"
    count; the actual search walks the same candidates hierarchically,
    scope by scope, rather than through this flat list)."""
    return list(_candidate_leaves(values, ()))


def _set_null(tree, path):
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = None


def _deep_merge(base, overlay):
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _load_merged_values(chart_dir, extra_args):
    """Python-side equivalent of what -f-layering `helm template` does to
    values.yaml: values.yaml deep-merged with every "-f <file>" in
    extra_args, in order. Needed only for building a sub-chart-scoped
    render's own overlay (see _resolve_scope) — slicing a subset of the
    merged tree as that sub-chart's OWN top-level values is something
    Helm's own -f layering can't do standalone; every other render in
    this module hands extra_args straight to helm as-is, same as every
    other check."""
    merged = copy.deepcopy(load_yaml(chart_dir / "values.yaml") or {})
    for i, arg in enumerate(extra_args):
        if arg == "-f":
            _deep_merge(merged, load_yaml(Path(extra_args[i + 1])) or {})
    return merged


def _dependency_by_key(chart_dir):
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    return {(dep.get("alias") or dep["name"]): dep for dep in chart_yaml.get("dependencies", [])}


def _enable_overlay(chart_dir):
    """A nested dict setting every Chart.yaml dependency's own
    "condition:" path to True — e.g. {"openbao": {"enabled": True}} —
    read straight from dependencies[].condition, never a name-based
    guess at which values.yaml keys "look like" a toggle. Skips
    zaakbrug.staging's own SUBCHART_VISIBILITY_EXEMPT entry (an
    internal, non-Chart.yaml-condition toggle this deliberately never
    force-enables — see this module's docstring)."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    overlay = {}
    for dep in chart_yaml.get("dependencies", []):
        condition = dep.get("condition")
        if not condition:
            continue
        path = tuple(condition.split("."))
        if subchart_visibility_exempt_reason(path[0], ".".join(path[1:])):
            continue
        _set_true(overlay, path)
    return overlay


def _set_true(tree, path):
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = True


def _parsed_docs(rendered_text):
    return [doc for doc in yaml.safe_load_all(rendered_text) if doc is not None]


def _render(chart_name, chart_path, extra_args, overlay_path):
    """Parsed multi-doc render (see _parsed_docs) of `chart_name` at
    `chart_path` (the full podiumd chart dir, or one vendored sub-chart's
    own .tgz — see _resolve_scope) with extra_args plus an extra "-f
    overlay_path" layered on top — None on a render failure (a schema/
    `required` guard tripped by the overlay, or a genuine setup problem)."""
    args = ["helm", "template", chart_name, str(chart_path), *extra_args, "-f", str(overlay_path)]
    result = run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return _parsed_docs(result.stdout)


def _render_with_null_overrides(scope, relative_paths):
    """Render `scope` with every one of relative_paths (leaf paths
    relative to whatever values `scope["chart_path"]` itself sees as its
    own top-level values — see _resolve_scope's "strip" for how a
    sub-chart-scoped path relates to its full, podiumd-rooted path)
    nulled on top of `scope["base_overlay"]` — a fresh deep copy each
    call, since every one of these calls can run concurrently."""
    overlay = copy.deepcopy(scope["base_overlay"])
    for path in relative_paths:
        _set_null(overlay, path)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(overlay, f)
        overlay_path = Path(f.name)
    try:
        return _render(scope["chart_name"], scope["chart_path"], scope["extra_args"], overlay_path)
    finally:
        overlay_path.unlink()


def _make_full_scope(chart_dir, extra_args, enable_overlay):
    """The whole-podiumd-chart scope — the always-safe fallback for a key
    neither other scope could handle, and the always-authoritative scope
    _confirm_against_full_chart re-verifies every scoped candidate
    against. base_overlay is enable_overlay (see _enable_overlay) rather
    than {}: this is the render that actually decides which Chart.yaml
    dependencies show up at all, so forcing every dependency condition
    true has to happen here to have any effect."""
    scope = {
        "chart_name": CHART_NAME,
        "chart_path": chart_dir,
        "extra_args": extra_args,
        "base_overlay": enable_overlay,
        "strip": 0,
    }
    scope["baseline_docs"] = _render_with_null_overrides(scope, [])
    return scope


def _make_own_scope(chart_dir, merged_values):
    """Render podiumd's OWN templates/ alone — a temp copy of the whole
    chart directory with "charts/" (the vendored .tgz's) excluded and
    Chart.yaml's own "dependencies:" list stripped, so Helm never
    touches any vendored sub-chart at all — for a top-level key that
    matches NO Chart.yaml dependency (keycloak, apiproxy, global, ...),
    which _resolve_scope has nothing to scope those to otherwise. Unlike
    a sub-chart scope, base_overlay is the WHOLE merged_values tree (not
    sliced to one key), since podiumd's own templates can read any
    top-level key, not just one. None if this doesn't work (e.g. a
    template needs something only a real sub-chart provides, like
    `.Subcharts` or an `include` on a sub-chart's own named template) —
    every caller falls back to the full-chart scope in that case, same
    as a failed sub-chart scope. Caller owns cleanup of the returned
    scope's "temp_dir" (rmtree once the whole check is done with it —
    every render against this scope needs it to keep existing)."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    temp_dir = Path(tempfile.mkdtemp(prefix="dead-values-own-"))
    shutil.copytree(chart_dir, temp_dir, ignore=shutil.ignore_patterns("charts"), dirs_exist_ok=True)
    own_chart_yaml = {k: v for k, v in chart_yaml.items() if k != "dependencies"}
    (temp_dir / "Chart.yaml").write_text(yaml.safe_dump(own_chart_yaml), encoding="utf-8")
    (temp_dir / "values.yaml").write_text("{}\n", encoding="utf-8")

    scope = {
        "chart_name": CHART_NAME,
        "chart_path": temp_dir,
        "extra_args": [],
        "base_overlay": merged_values,
        "strip": 0,
        "temp_dir": temp_dir,
    }
    scope["baseline_docs"] = _render_with_null_overrides(scope, [])
    if scope["baseline_docs"] is None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None
    return scope


def _resolve_scope(chart_dir, merged_values, dep_by_key, key, own_scope, full_scope):
    """The fast, sub-chart-scoped render for `key` if one can be built
    (see this module's docstring) and its own baseline render actually
    succeeds; own_scope (see _make_own_scope) if `key` matches no
    Chart.yaml dependency at all; else full_scope, the always-safe
    fallback. Never raises and never returns something unusable: any
    reconstruction gap just means this key gets tested the slow (but
    correct) way, same as before this optimization existed."""
    dep = dep_by_key.get(key)
    if dep is None:
        return own_scope if own_scope is not None else full_scope
    if dep["repository"].startswith("file://"):
        return full_scope

    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    if not tgz_path.is_file():
        return full_scope

    subtree = merged_values.get(key)
    if not isinstance(subtree, dict):
        return full_scope

    base_overlay = dict(subtree)
    if "global" in merged_values:
        base_overlay["global"] = merged_values["global"]

    scope = {
        "chart_name": dep["name"],
        "chart_path": tgz_path,
        "extra_args": [],
        "base_overlay": base_overlay,
        "strip": 1,
    }
    scope["baseline_docs"] = _render_with_null_overrides(scope, [])
    if scope["baseline_docs"] is None:
        return full_scope
    return scope


def _run_dead_value_search(executor, roots, total=None):
    """(scope, full_path) for every candidate "looks dead within its own
    scope" leaf found by walking `roots` (a [(scope, path, node), ...]
    list, one entry per subtree to search) top-down — see this module's
    docstring for the batch-then-recurse-on-diff strategy and why this is
    an iterative, level-by-level walk (never a worker recursively
    submitting more work to the same executor). `total` is only for the
    progress line printed after each level — the denominator for "N/total
    resolved so far" — omit it (e.g. a small confirmation-pass re-run) to
    skip printing progress for that call."""
    found = []
    resolved = 0
    frontier = list(roots)
    level = 0
    while frontier:
        level += 1
        pending = []
        for scope, path, node in frontier:
            leaf_paths = list(_candidate_leaves(node, path))
            if leaf_paths:
                pending.append((scope, path, node, leaf_paths))
        if not pending:
            break

        futures = {
            executor.submit(_render_with_null_overrides, scope,
                             [p[scope["strip"]:] for p in leaf_paths]): (scope, path, node, leaf_paths)
            for scope, path, node, leaf_paths in pending
        }
        next_frontier = []
        for future in concurrent.futures.as_completed(futures):
            scope, path, node, leaf_paths = futures[future]
            docs = future.result()
            if docs is not None and docs == scope["baseline_docs"]:
                found.extend((scope, p) for p in leaf_paths)
                resolved += len(leaf_paths)
            elif len(leaf_paths) > 1:
                next_frontier.extend((scope, path + (key,), child) for key, child in node.items())
            else:
                resolved += 1  # single leaf that differed (or errored): not dead, done with it
        if total is not None:
            print(f"  level {level}: {len(pending)} render(s) — {resolved}/{total} leaf(ves) resolved so far "
                  f"({len(found)} dead, {len(next_frontier)} subtree(s) still being narrowed down)")
        frontier = next_frontier
    return found


def _tree_from_paths(paths):
    """A nested dict whose leaves are exactly `paths` (each set to a
    non-null placeholder — _candidate_leaves only cares that it isn't
    None) — lets _run_dead_value_search's own top-down walk be reused to
    re-verify a small, specific set of candidates (see
    _confirm_against_full_chart) instead of needing a separate
    confirmation algorithm."""
    tree = {}
    for path in paths:
        node = tree
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = True
    return tree


def _confirm_against_full_chart(executor, full_scope, candidates):
    """Re-verify every candidate that was found via some OTHER (scoped)
    scope against the real, authoritative full-chart render — a scoped
    render only ever narrows the search, never makes the final call (see
    this module's docstring's safety-net rationale). A candidate already
    found via full_scope itself needs no re-check."""
    if not candidates:
        return []
    tree = _tree_from_paths(candidates)
    roots = [(full_scope, (key,), node) for key, node in tree.items()]
    return [path for _scope, path in _run_dead_value_search(executor, roots, len(candidates))]


def check_dead_values(chart_dir, extra_args):
    values = load_yaml(chart_dir / "values.yaml") or {}
    total = len(candidate_leaf_paths(values))

    print(f"Null-testing {total} values.yaml leaf(ves) against the baseline render "
          f"(top-down, per-subchart where possible, up to {DEAD_VALUES_MAX_WORKERS} in parallel)...")

    enable_overlay = _enable_overlay(chart_dir)
    full_scope = _make_full_scope(chart_dir, extra_args, enable_overlay)
    if full_scope["baseline_docs"] is None:
        return True, "skipped — baseline render failed"

    merged_values = _load_merged_values(chart_dir, extra_args)
    _deep_merge(merged_values, enable_overlay)
    dep_by_key = _dependency_by_key(chart_dir)

    own_scope = _make_own_scope(chart_dir, merged_values)
    if own_scope is None:
        print("Own-templates-only scope unavailable — falling back to full-chart scope for those keys")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=DEAD_VALUES_MAX_WORKERS) as executor:
            print(f"Resolving render scope for {len(values)} top-level key(s)...")
            scope_futures = {
                executor.submit(_resolve_scope, chart_dir, merged_values, dep_by_key, key, own_scope, full_scope): key
                for key in values
            }
            roots = []
            for future in concurrent.futures.as_completed(scope_futures):
                key = scope_futures[future]
                roots.append((future.result(), (key,), values[key]))

            scoped_n = sum(1 for scope, _, _ in roots if scope is not full_scope and scope is not own_scope)
            own_n = sum(1 for scope, _, _ in roots if scope is own_scope)
            full_n = sum(1 for scope, _, _ in roots if scope is full_scope)
            print(f"  {scoped_n} sub-chart-scoped, {own_n} own-templates-scoped, {full_n} full-chart-scoped")

            print("Searching top-down for dead leaves...")
            found = _run_dead_value_search(executor, roots, total)
            confirmed = [path for scope, path in found if scope is full_scope]
            to_confirm = [path for scope, path in found if scope is not full_scope]
            if to_confirm:
                print(f"Confirming {len(to_confirm)} candidate(s) against the real full-chart baseline...")
            dead = confirmed + _confirm_against_full_chart(executor, full_scope, to_confirm)
    finally:
        if own_scope is not None:
            shutil.rmtree(own_scope["temp_dir"], ignore_errors=True)

    dead.sort()

    if not dead:
        print(f"OK: no dead values.yaml entries found ({total} checked)")
        return True, f"0/{total} dead"

    print(f"Found {len(dead)} values.yaml leaf(ves) whose value never surfaces in the "
          f"rendered chart (nulling it made no difference to the maximal render) — "
          f"report only, a human call whether it's genuinely removable:")
    for path in dead:
        print(f"  {'.'.join(path)}")

    return True, f"{len(dead)}/{total} dead (report only)"
