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
   chart with "charts/" (the vendored .tgz's) excluded, and Chart.yaml's
   own "dependencies:" list stripped down to just whatever podiumd's own
   templates actually need vendored to render at all — renders podiumd's
   OWN templates alone, with the FULL coalesced values (see
   _coalesced_values: each dependency's own vendored default merged in
   UNDER podiumd's own override — Helm does this same coalescing for
   `.Values.<dep>` from the parent chart's own templates too, which
   plain _load_merged_values alone can't replicate) as its overlay (not
   sliced to one key, since podiumd's own templates can reference any
   top-level key). Which dependencies (if any) stay vendored starts from
   a deterministic ".Subcharts.<name>" scan and grows on demand — a
   render whose error names a missing named template (an `include` on a
   vendored dependency's own _helpers.tpl) adds that one dependency and
   retries, same self-healing pattern _make_full_scope's own forced-
   enable degradation uses. Same fallback discipline throughout: a
   failure that can't be resolved this way just falls back to the
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

   One specific false positive is common enough, and cheap enough to
   know about upfront, that it's worth excluding before ever reaching
   the safety net at all rather than burning a slow full-chart
   confirmation on it every time: a dependency's own Chart.yaml
   "condition:" leaf (see _condition_leaf_paths) can never be honestly
   null-tested within that dependency's own sub-chart scope — a
   "condition:" only gates whether Helm includes the dependency AT THE
   PARENT level, so a standalone render of it (no parent to gate) always
   renders regardless of what this one leaf says. Real, measured
   examples: eck-operator.enabled, clamav.metrics.enabled, kiss-eck.enabled
   all looked "dead" to their own sub-chart scope purely for this reason
   (kiss-eck's own vendored chart is actually named "eck-stack" — a
   further-nested umbrella whose OWN dependencies have the identical
   issue one level down, not yet addressed). Excluded from every scope's
   candidate pool entirely (same mechanism as SUBCHART_VISIBILITY_EXEMPT,
   just a different, dependency-derived set of paths) rather than tested
   and then rejected — already known live by construction, since it's
   the exact same leaf _enable_overlay forces true.

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
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from lib.chart import load_yaml, subchart_values
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


def _candidate_leaves(node, path, exempt_full_paths=frozenset()):
    """flatten_leaves(node, path), minus a value that's already null
    (nulling a null is a no-op — nothing to learn), any path
    SUBCHART_VISIBILITY_EXEMPT already has a standing, reviewed answer
    for (see this module's docstring), and any path in exempt_full_paths
    (see _condition_leaf_paths — a dependency's own Chart.yaml
    "condition:" leaf, already known live by construction, never worth
    testing at all)."""
    for leaf_path, value in flatten_leaves(node, path):
        if value is None or not leaf_path:
            continue
        if subchart_visibility_exempt_reason(leaf_path[0], ".".join(leaf_path[1:])):
            continue
        if leaf_path in exempt_full_paths:
            continue
        yield leaf_path


def candidate_leaf_paths(values, exempt_full_paths=frozenset()):
    """Every path _candidate_leaves finds in podiumd's own values.yaml
    worth null-testing — the full, flat list (used for the "N checked"
    count; the actual search walks the same candidates hierarchically,
    scope by scope, rather than through this flat list)."""
    return list(_candidate_leaves(values, (), exempt_full_paths))


def _condition_leaf_paths(chart_dir):
    """Every Chart.yaml dependency's own "condition:" as a full leaf-path
    tuple (e.g. ("eck-operator", "enabled")) — the exact same set
    _enable_overlay forces true. Excluded from every scope's candidate
    pool entirely (see _candidate_leaves) rather than tested at all:
    this ONE specific leaf can never be honestly null-tested within a
    sub-chart's own standalone scope (see _resolve_scope) — a
    dependency's "condition:" only gates whether Helm includes it AT
    THE PARENT level, so a standalone render of that one dependency
    (no parent to gate) always renders it regardless of what this leaf
    says, making it look permanently "dead" there — a real, measured
    example: eck-operator.enabled, clamav.metrics.enabled, and
    kiss-eck.enabled (kiss-eck's own vendored chart is actually named
    "eck-stack" — a further-nested umbrella whose OWN dependencies have
    the exact same issue one level down, not yet addressed here) all
    showed up as false positives in the sub-chart scope before being
    correctly rejected by the full-chart confirmation pass — this
    exemption skips the wasted round-trip through that slow confirmation
    for the one leaf already known, by construction, to always survive
    it."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    paths = set()
    for dep in chart_yaml.get("dependencies", []):
        condition = dep.get("condition")
        if condition:
            paths.add(tuple(condition.split(".")))
    return paths


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


def _coalesced_values(chart_dir, merged_values, dep_by_key):
    """merged_values, but with each Chart.yaml dependency's OWN default
    values.yaml (from its vendored .tgz — see lib.chart.subchart_values)
    merged in UNDER podiumd's own override for that key — replicating
    what Helm itself does when resolving ".Values.<dep>" from the
    PARENT chart's own top-level templates, not just from within that
    dependency's own templates. A real, measured example this exists
    for: podiumd's own keycloak-operator-servicemonitor-rbac.yaml reads
    $kcOp.operator.serviceAccount (where $kcOp is
    `.Values["keycloak-operator"]`) — that field only exists because
    Helm coalesces keycloak-operator's own vendored default in, not
    because podiumd's own values.yaml sets it. Only _make_own_scope
    needs this: the sub-chart scope already gets this coalescing for
    free (rendering the dependency's own .tgz directly always loads its
    own values.yaml as the base), and the full-chart scope IS the real
    render Helm performs this coalescing in already."""
    coalesced = copy.deepcopy(merged_values)
    for key, dep in dep_by_key.items():
        defaults = subchart_values(chart_dir, dep)
        if defaults is None:
            continue
        with_defaults = copy.deepcopy(defaults)
        _deep_merge(with_defaults, coalesced.get(key) or {})
        coalesced[key] = with_defaults
    return coalesced


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


def _helm_template(chart_name, chart_path, extra_args, overlay_path):
    """The raw `helm template` subprocess result — every other render
    helper here derives its own return value from this; the raw result
    (with its stderr) is only needed where a caller must diagnose, or
    structurally react to, a failure rather than just detect one (see
    _make_full_scope)."""
    args = ["helm", "template", chart_name, str(chart_path), *extra_args, "-f", str(overlay_path)]
    return run(args, capture_output=True, text=True)


def _render(chart_name, chart_path, extra_args, overlay_path):
    """Parsed multi-doc render (see _parsed_docs) of `chart_name` at
    `chart_path` (the full podiumd chart dir, or one vendored sub-chart's
    own .tgz — see _resolve_scope) with extra_args plus an extra "-f
    overlay_path" layered on top — None on a render failure (a schema/
    `required` guard tripped by the overlay, or a genuine setup problem)."""
    result = _helm_template(chart_name, chart_path, extra_args, overlay_path)
    if result.returncode != 0:
        return None
    return _parsed_docs(result.stdout)


def _with_overlay_file(overlay, render_fn):
    """Dump `overlay` to a throwaway temp file and call
    render_fn(overlay_path) — the file is always cleaned up, even if
    render_fn raises."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(overlay, f)
        overlay_path = Path(f.name)
    try:
        return render_fn(overlay_path)
    finally:
        overlay_path.unlink()


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
    return _with_overlay_file(
        overlay, lambda overlay_path: _render(scope["chart_name"], scope["chart_path"],
                                               scope["extra_args"], overlay_path))


# Two different shapes of Helm error each name the offending chart
# differently — see _error_chart_names, which tries both:
#  - a values-schema-validation failure lists "<chart>:" lines, one per
#    offending chart, each followed by its own "- <field>: <reason>"
#    bullets.
#  - a template EXECUTION error (e.g. a `required` guard tripped by a
#    value this chart doesn't set) instead names the exact template
#    file: "execution error at (<path>/templates/<file>:<line>:<col>):
#    ...". <path> can be several "charts/" levels deep for a NESTED
#    (transitive) dependency's own template — the first "charts/<name>/"
#    segment is always the TOP-LEVEL Chart.yaml dependency (the only
#    kind _enable_overlay's own keys ever name), even when the actual
#    failing template lives deeper, inside a transitive dependency of
#    that one.
_SCHEMA_ERROR_CHART_RE = re.compile(r"^([A-Za-z0-9_.\-]+):$", re.MULTILINE)
_EXECUTION_ERROR_PATH_RE = re.compile(r"execution error at \(([^)]+)\):")
_TOP_LEVEL_CHART_PATH_RE = re.compile(r"charts/([A-Za-z0-9_.\-]+)/")


def _error_chart_names(stderr):
    names = set(_SCHEMA_ERROR_CHART_RE.findall(stderr))
    for path in _EXECUTION_ERROR_PATH_RE.findall(stderr):
        chart_match = _TOP_LEVEL_CHART_PATH_RE.search(path)
        if chart_match:
            names.add(chart_match.group(1))
    return names


def _make_full_scope(chart_dir, extra_args, enable_overlay):
    """The whole-podiumd-chart scope — the always-safe fallback for a key
    neither other scope could handle, and the always-authoritative scope
    _confirm_against_full_chart re-verifies every scoped candidate
    against. base_overlay starts as enable_overlay (see _enable_overlay)
    rather than {}: this is the render that actually decides which
    Chart.yaml dependencies show up at all, so forcing every dependency
    condition true has to happen here to have any effect.

    Forcing every dependency on isn't risk-free, though: at least two
    real, measured examples (omc, zaakbrug) are disabled by default
    specifically because this chart's current CI placeholder values
    don't satisfy them — a schema (omc's own values.schema.json) in one
    case, a `required` template guard (zaakbrug's own "DTAP stage") in
    the other — nobody's ever needed to before, since they were always
    off. A render failure here would otherwise take down the WHOLE check
    with no fallback left (unlike the scoped/own-templates renders, this
    IS the last resort) — so a failure parses Helm's own error (see
    _error_chart_names — both a schema-validation failure's "<chart>:"
    lines and a template execution error's file path name the offending
    chart, just differently) to know exactly which forced-on dependency
    condition(s) to drop (falling back to that one dependency's own
    natural, un-forced default — same graceful, per-dependency
    degradation the other scopes already have) and retries, rather than
    giving up on the entire render over one dependency's unrelated gap.
    Every dropped condition is reported once. Prints the real helm error
    (not just "failed") if the render still can't be attributed to a
    specific, droppable dependency — this IS the final fallback, so
    silence here would leave a genuine problem completely invisible."""
    overlay = copy.deepcopy(enable_overlay)
    dropped = []
    while True:
        result = _with_overlay_file(
            overlay, lambda overlay_path: _helm_template(CHART_NAME, chart_dir, extra_args, overlay_path))
        scope = {
            "chart_name": CHART_NAME,
            "chart_path": chart_dir,
            "extra_args": extra_args,
            "base_overlay": overlay,
            "strip": 0,
        }
        if result.returncode == 0:
            scope["baseline_docs"] = _parsed_docs(result.stdout)
            if dropped:
                print(f"Note: could not force-enable {', '.join(sorted(dropped))} (its own values "
                      f"aren't satisfied by this chart's current CI placeholder values) — tested at "
                      f"its natural, un-forced default instead", flush=True)
            return scope

        failing = (_error_chart_names(result.stderr) & set(overlay)) - set(dropped)
        if not failing:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", flush=True)
            scope["baseline_docs"] = None
            return scope
        for name in failing:
            del overlay[name]
            dropped.append(name)


def _own_template_subchart_refs(chart_dir):
    """The set of Chart.yaml dependency alias-or-name values podiumd's
    OWN templates/*.yaml reference via ".Subcharts.<name>" — Helm's
    mechanism for a parent template to reach into a dependency's own
    RENDERED context (as opposed to just its values — see
    _coalesced_values for that, more common, gap) directly. None
    currently do (this chart accesses a dependency's config the more
    common way, via ".Values.<dep>" — see _coalesced_values), but
    _make_own_scope still needs to know exactly which dependencies (if
    any) it must keep vendored for its own-templates-only render to
    work should this ever change, rather than either keeping none
    (breaks on a reference like this) or all ~25 (defeats the whole
    point of this scope). Deterministic — reads the literal
    ".Subcharts.X" text these templates already contain, never a
    name-based guess at which dependency "might" be needed."""
    templates_dir = chart_dir / "templates"
    if not templates_dir.is_dir():
        return set()
    refs = set()
    for path in sorted(templates_dir.rglob("*.yaml")):
        if path.is_file():
            refs.update(re.findall(r"\.Subcharts\.([A-Za-z0-9_-]+)", path.read_text(encoding="utf-8")))
    return refs


# A named-template `include "<chart>.<suffix>" .` call this chart's own
# templates make on a vendored dependency's own _helpers.tpl (e.g.
# "objecttypen.labels") fails this exact way when that dependency isn't
# vendored into the render at all — see _make_own_scope's retry loop,
# which parses this the same way _make_full_scope parses its own
# schema/execution errors: read exactly which dependency Helm itself
# says is missing, rather than guess.
_MISSING_TEMPLATE_RE = re.compile(r'no template "([A-Za-z0-9_-]+)\.[A-Za-z0-9_.-]*" associated')


def _build_own_scope_chart(chart_dir, chart_yaml, kept_deps):
    """A fresh temp copy of chart_dir with "charts/" excluded and
    Chart.yaml's "dependencies:" replaced by kept_deps (their own .tgz's
    copied back in) — the actual chart directory _make_own_scope tries
    rendering on each attempt of its retry loop."""
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


def _make_own_scope(chart_dir, coalesced_values):
    """Render podiumd's OWN templates/ alone — a temp copy of the whole
    chart directory with "charts/" (the vendored .tgz's) excluded, and
    Chart.yaml's own "dependencies:" list stripped down to just whatever
    podiumd's own templates actually need vendored to render at all — for
    a top-level key that matches NO Chart.yaml dependency (keycloak,
    apiproxy, global, ...), which _resolve_scope has nothing to scope
    those to otherwise. Unlike a sub-chart scope, base_overlay is the
    WHOLE coalesced_values tree (not sliced to one key), since podiumd's
    own templates can read any top-level key, not just one — the caller
    is expected to have already run this through _coalesced_values, not
    just _load_merged_values, or every dependency key would be missing
    its own vendored defaults here (this scope has no other way to pick
    those up, unlike the sub-chart scope, which gets them for free from
    Helm's own base-values loading).

    Which dependencies (if any) need to stay vendored starts from
    _own_template_subchart_refs's deterministic ".Subcharts.<name>" scan,
    then grows on demand: a failed render whose error names a missing
    named template ("no template \"<chart>.<suffix>\" associated" — an
    `include` on a vendored dependency's own _helpers.tpl, a real,
    measured example: podiumd's own create-required-objecttypen.yaml
    calls "objecttypen.labels") adds that one dependency and retries,
    same self-healing, error-message-driven pattern _make_full_scope
    uses for its own forced-enable degradation. Bounded by the real
    dependency count — each retry can only ever grow the kept set, never
    loop on the same gap twice. None if a render still fails for some
    OTHER, unparseable reason (e.g. a genuinely undetected `.Subcharts`
    field access) — every caller falls back to the full-chart scope in
    that case, same as a failed sub-chart scope. Caller owns cleanup of
    the returned scope's "temp_dir" (rmtree once the whole check is done
    with it — every render against this scope needs it to keep
    existing)."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    all_deps = chart_yaml.get("dependencies", [])
    dep_by_name_or_alias = {(dep.get("alias") or dep["name"]): dep for dep in all_deps}

    keep = set(_own_template_subchart_refs(chart_dir)) & set(dep_by_name_or_alias)
    while True:
        kept_deps = [dep for dep in all_deps if (dep.get("alias") or dep["name"]) in keep]
        temp_dir = _build_own_scope_chart(chart_dir, chart_yaml, kept_deps)

        result = _with_overlay_file(
            coalesced_values, lambda overlay_path: _helm_template(CHART_NAME, temp_dir, [], overlay_path))
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
            print("Note: own-templates-only scope render failed — falling back to full-chart scope "
                  "for keys with no Chart.yaml dependency:", flush=True)
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", flush=True)
            return None
        keep |= missing


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


def _run_dead_value_search(executor, roots, total=None, exempt_full_paths=frozenset()):
    """(scope, full_path) for every candidate "looks dead within its own
    scope" leaf found by walking `roots` (a [(scope, path, node), ...]
    list, one entry per subtree to search) top-down — see this module's
    docstring for the batch-then-recurse-on-diff strategy and why this is
    an iterative, level-by-level walk (never a worker recursively
    submitting more work to the same executor). `total` is only for the
    progress line printed after each level — the denominator for "N/total
    resolved so far" — omit it (e.g. a small confirmation-pass re-run) to
    skip printing progress for that call. exempt_full_paths is passed
    straight through to _candidate_leaves (see _condition_leaf_paths)."""
    found = []
    resolved = 0
    frontier = list(roots)
    level = 0
    while frontier:
        level += 1
        pending = []
        for scope, path, node in frontier:
            leaf_paths = list(_candidate_leaves(node, path, exempt_full_paths))
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
                  f"({len(found)} dead, {len(next_frontier)} subtree(s) still being narrowed down)", flush=True)
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
    condition_paths = _condition_leaf_paths(chart_dir)
    total = len(candidate_leaf_paths(values, condition_paths))

    print(f"Null-testing {total} values.yaml leaf(ves) against the baseline render "
          f"(top-down, per-subchart where possible, up to {DEAD_VALUES_MAX_WORKERS} in parallel)...",
          flush=True)

    enable_overlay = _enable_overlay(chart_dir)
    full_scope = _make_full_scope(chart_dir, extra_args, enable_overlay)
    if full_scope["baseline_docs"] is None:
        return True, "skipped — baseline render failed"

    merged_values = _load_merged_values(chart_dir, extra_args)
    # full_scope["base_overlay"] here, not the raw enable_overlay: it's
    # already been pruned down to whatever could actually be forced on
    # without breaking the full-chart render (see _make_full_scope) —
    # reusing it keeps _make_own_scope's own baseline from hitting the
    # exact same, already-known-bad forced-enable independently.
    _deep_merge(merged_values, full_scope["base_overlay"])
    dep_by_key = _dependency_by_key(chart_dir)

    own_scope = _make_own_scope(chart_dir, _coalesced_values(chart_dir, merged_values, dep_by_key))
    if own_scope is None:
        print("Own-templates-only scope unavailable — falling back to full-chart scope for those keys",
              flush=True)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=DEAD_VALUES_MAX_WORKERS) as executor:
            print(f"Resolving render scope for {len(values)} top-level key(s)...", flush=True)
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
            print(f"  {scoped_n} sub-chart-scoped, {own_n} own-templates-scoped, {full_n} full-chart-scoped",
                  flush=True)

            print("Searching top-down for dead leaves...", flush=True)
            found = _run_dead_value_search(executor, roots, total, condition_paths)
            confirmed = [path for scope, path in found if scope is full_scope]
            to_confirm = [path for scope, path in found if scope is not full_scope]
            if to_confirm:
                print(f"Confirming {len(to_confirm)} candidate(s) against the real full-chart baseline...",
                      flush=True)
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
