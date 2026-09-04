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
`null` (via an extra `-f` overlay layered on top of `extra_args`, same
mechanism check_lint/check_render/check_image_upgrades already use for
the CI placeholder values — never touches the real values.yaml on disk)
and re-render; if the rendered manifests come back structurally
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

Cost control: naively re-rendering once per leaf (podiumd's own
values.yaml has on the order of a thousand of them) would mean a
thousand-plus `helm template` calls. Instead of a flat, arbitrary batch
size, this walks values.yaml's own tree top-down (see
_find_dead_in_subtree): a whole subtree (e.g. one top-level component
key, or any dict node under it) is null-tested as ONE unit first: every
leaf under it nulled together in a single render. If that reproduces
the baseline exactly, every leaf anywhere under that subtree is
confirmed dead in that one render, however many there are and however
deep — no further recursion needed. Only when a subtree's combined
render either errors (a `required`/values-schema guard tripped by one
of its nulled leaves) or comes back different from baseline does this
recurse into that subtree's own immediate children and repeat the same
test on each of them, narrowing down one level at a time until it
bottoms out at individual leaves. A real, wholly-unused block (a whole
disabled feature, an orphaned override) collapses to one render
regardless of size; a live subtree costs one render per node actually
walked down to reach its live leaves, plus one for each dead sibling
pruned along the way — never more than testing every leaf individually
would have anyway.

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
import tempfile
from pathlib import Path

import yaml

from lib.chart import load_yaml
from lib.digest_pinning_check import subchart_visibility_exempt_reason
from lib.procutil import run
from lib.render_scope import CHART_NAME


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
    count; _find_dead_in_subtree walks the same candidates hierarchically
    rather than through this flat list)."""
    return list(_candidate_leaves(values, ()))


def _set_null(tree, path):
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = None


def _parsed_docs(rendered_text):
    return [doc for doc in yaml.safe_load_all(rendered_text) if doc is not None]


def _render(chart_dir, extra_args, overlay_path=None):
    """Parsed multi-doc render (see _parsed_docs) with extra_args, plus an
    extra "-f overlay_path" layered on top if given — None on a render
    failure (a schema/`required` guard tripped by the overlay)."""
    args = ["helm", "template", CHART_NAME, str(chart_dir), *extra_args]
    if overlay_path is not None:
        args += ["-f", str(overlay_path)]
    result = run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return _parsed_docs(result.stdout)


def _render_with_null_overrides(chart_dir, extra_args, paths):
    overlay = {}
    for path in paths:
        _set_null(overlay, path)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(overlay, f)
        overlay_path = Path(f.name)
    try:
        return _render(chart_dir, extra_args, overlay_path)
    finally:
        overlay_path.unlink()


def _find_dead_in_subtree(chart_dir, extra_args, baseline_docs, path, node):
    """Dead-code candidates within node (rooted at path) — see this
    module's docstring for the top-down/recurse-on-diff strategy. Only
    ever recurses into node.items() when node is a dict with more than
    one candidate leaf under it: flatten_leaves treats a list, an empty
    dict, or a scalar as exactly one leaf each, so leaf_paths having more
    than one entry already guarantees node is a non-empty dict here."""
    leaf_paths = list(_candidate_leaves(node, path))
    if not leaf_paths:
        return []

    docs = _render_with_null_overrides(chart_dir, extra_args, leaf_paths)
    if docs is not None and docs == baseline_docs:
        return leaf_paths
    if len(leaf_paths) == 1:
        return []

    dead = []
    for key, child in node.items():
        dead.extend(_find_dead_in_subtree(chart_dir, extra_args, baseline_docs, path + (key,), child))
    return dead


def check_dead_values(chart_dir, extra_args):
    values = load_yaml(chart_dir / "values.yaml") or {}
    total = len(candidate_leaf_paths(values))

    print(f"Null-testing {total} values.yaml leaf(ves) against the baseline render "
          f"(top-down, whole subtrees at a time)...")
    baseline_docs = _render(chart_dir, extra_args)
    if baseline_docs is None:
        return True, "skipped — baseline render failed"

    dead = []
    for key, child in values.items():
        dead.extend(_find_dead_in_subtree(chart_dir, extra_args, baseline_docs, (key,), child))
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
