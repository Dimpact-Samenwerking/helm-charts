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

"Consider everything always enabled" (this check's own design brief):
uses the exact same baseline extra_args (values.yaml + ci/lint-values.yaml)
as check_lint/check_render/check_image_upgrades/check_cves — the one
render this repo already treats as "maximal" (frankgateway on, every
`required` guard satisfied) — rather than trying to enumerate every
values combination a real deployment might choose. The one deliberate
exception: SUBCHART_VISIBILITY_EXEMPT's zaakbrug.staging is NOT force-
enabled — that subtree is permanently, by hard policy, never going to be
on (see lib.digest_pinning_check's docstring) regardless of what
"everything enabled" means elsewhere, so its leaves are excluded from
this check's scope entirely rather than reported as a fresh "dead" find
every time (same exemption check_subchart_image_visibility already
applies, reused here via subchart_visibility_exempt_reason rather than
re-deriving the same prefix-match logic).

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
   podiumd chart (all ~25 vendored dependencies) to test one leaf under,
   say, "zac" is wasteful — only the zac sub-chart's own templates can
   possibly read a zac.* value (with the one known exception below).
   Where a top-level key matches an actual Chart.yaml dependency with a
   vendored charts/<name>-<version>.tgz on disk, this renders THAT
   sub-chart alone (`helm template <name> <its .tgz>`) instead of the
   full umbrella chart, with a `-f` overlay built from podiumd's own
   merged values (values.yaml + ci/lint-values.yaml, replicated in
   Python via _load_merged_values/_deep_merge — Helm's own -f layering
   can't slice a subset of an already-merged tree, which is what a
   scoped render needs) sliced down to just that key's own subtree plus
   "global" (which Helm always propagates into every sub-chart). A
   sub-chart's own baseline render failing (its values.yaml schema, or
   any other reconstruction gap) just falls back to the full-chart scope
   for that key instead — never treated as evidence of anything.

   SAFETY NET: a scoped render is only ever trusted to narrow the search
   faster, never to make the final call. This matters because at least
   one top-level key in practice is a real, documented exception: e.g.
   "keycloak" both maps to a vendored dependency AND is read directly by
   some of podiumd's OWN top-level templates/*.yaml (see
   lib.image_repository_check's docstring on "adapter"'s siblings) — a
   leaf like that could look "dead" to an isolated sub-chart render while
   still being genuinely live in the real, full chart. So every
   candidate a scoped render finds is re-verified with one more pass
   against the REAL, authoritative full-chart baseline
   (_confirm_against_full_chart) before ever being reported — reusing
   the exact same top-down search, just seeded with only the candidates
   (as a small pruned tree) instead of the whole chart, and always via
   the full-chart scope. A candidate already found via the full-chart
   scope in the first place skips this re-check (nothing to re-confirm).

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

Never fails regardless of findings — same as check_subchart_image_
visibility/check_image_upgrades/check_cves: whether a candidate is truly
removable (vs. e.g. read only by a disabled-by-default OWN feature this
chart's own "everything enabled" baseline doesn't happen to exercise
either) is a human's call, not something this scan can decide on its
own."""
import concurrent.futures
import copy
import os
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


def _make_full_scope(chart_dir, extra_args):
    """The whole-podiumd-chart scope — the only one used for a top-level
    key with no matching Chart.yaml dependency (e.g. "global", or one of
    podiumd's own directly-templated blocks), and the always-authoritative
    scope _confirm_against_full_chart re-verifies every scoped candidate
    against."""
    scope = {
        "chart_name": CHART_NAME,
        "chart_path": chart_dir,
        "extra_args": extra_args,
        "base_overlay": {},
        "strip": 0,
    }
    scope["baseline_docs"] = _render_with_null_overrides(scope, [])
    return scope


def _resolve_scope(chart_dir, merged_values, dep_by_key, key, full_scope):
    """The fast, sub-chart-scoped render for `key` if one can be built
    (see this module's docstring) and its own baseline render actually
    succeeds — else full_scope, the always-safe fallback. Never raises
    and never returns something unusable: any reconstruction gap just
    means this key gets tested the slow (but correct) way, same as
    before this optimization existed."""
    dep = dep_by_key.get(key)
    if dep is None or dep["repository"].startswith("file://"):
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


def _run_dead_value_search(executor, roots):
    """(scope, full_path) for every candidate "looks dead within its own
    scope" leaf found by walking `roots` (a [(scope, path, node), ...]
    list, one entry per subtree to search) top-down — see this module's
    docstring for the batch-then-recurse-on-diff strategy and why this is
    an iterative, level-by-level walk (never a worker recursively
    submitting more work to the same executor)."""
    found = []
    frontier = list(roots)
    while frontier:
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
            elif len(leaf_paths) > 1:
                next_frontier.extend((scope, path + (key,), child) for key, child in node.items())
            # a single leaf that differed (or errored): not dead, done with it
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
    """Re-verify every candidate that was found via some OTHER (sub-
    chart-scoped) scope against the real, authoritative full-chart
    render — a scoped render only ever narrows the search, never makes
    the final call (see this module's docstring's safety-net rationale).
    A candidate already found via full_scope itself needs no re-check."""
    if not candidates:
        return []
    tree = _tree_from_paths(candidates)
    roots = [(full_scope, (key,), node) for key, node in tree.items()]
    return [path for _scope, path in _run_dead_value_search(executor, roots)]


def check_dead_values(chart_dir, extra_args):
    values = load_yaml(chart_dir / "values.yaml") or {}
    total = len(candidate_leaf_paths(values))

    print(f"Null-testing {total} values.yaml leaf(ves) against the baseline render "
          f"(top-down, per-subchart where possible, up to {DEAD_VALUES_MAX_WORKERS} in parallel)...")

    full_scope = _make_full_scope(chart_dir, extra_args)
    if full_scope["baseline_docs"] is None:
        return True, "skipped — baseline render failed"

    merged_values = _load_merged_values(chart_dir, extra_args)
    dep_by_key = _dependency_by_key(chart_dir)

    with concurrent.futures.ThreadPoolExecutor(max_workers=DEAD_VALUES_MAX_WORKERS) as executor:
        scope_futures = {
            executor.submit(_resolve_scope, chart_dir, merged_values, dep_by_key, key, full_scope): key
            for key in values
        }
        roots = []
        for future in concurrent.futures.as_completed(scope_futures):
            key = scope_futures[future]
            roots.append((future.result(), (key,), values[key]))

        found = _run_dead_value_search(executor, roots)
        confirmed = [path for scope, path in found if scope is full_scope]
        to_confirm = [path for scope, path in found if scope is not full_scope]
        dead = confirmed + _confirm_against_full_chart(executor, full_scope, to_confirm)

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
