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
thousand-plus `helm template` calls. Instead, leaves are nulled out in
batches (see DEAD_VALUES_BATCH_SIZE): if nulling an entire batch at once
still reproduces the baseline exactly, every leaf in that batch is
confirmed dead in a single render (the common case — most of this
chart's values ARE live, but the ones that aren't tend to cluster
harmlessly). Only when a batch's render either errors (a `required`/
values-schema guard tripped by one of its nulled leaves) or comes back
different from baseline does this fall back to re-rendering each of that
batch's leaves individually — the only way to attribute the effect to a
specific leaf. Worst case (every leaf in every batch turns out to be
load-bearing) costs one wasted batch render per batch on top of the
same one-per-leaf renders a naive approach would always pay — never
asymptotically worse.

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

# How many leaves get nulled out together in one render before falling
# back to one-render-per-leaf for just that batch — see this module's
# docstring for the cost/accuracy tradeoff.
DEAD_VALUES_BATCH_SIZE = 25


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


def candidate_leaf_paths(values):
    """Every flatten_leaves path in podiumd's own values.yaml worth
    null-testing: skips a value that's already null (nulling a null is a
    no-op — nothing to learn) and any path SUBCHART_VISIBILITY_EXEMPT
    already has a standing, reviewed answer for (see this module's
    docstring)."""
    paths = []
    for path, value in flatten_leaves(values):
        if value is None or not path:
            continue
        if subchart_visibility_exempt_reason(path[0], ".".join(path[1:])):
            continue
        paths.append(path)
    return paths


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


def _find_dead_in_batch(chart_dir, extra_args, baseline_docs, paths):
    """Dead-code candidates (a sublist of paths) within one batch — see
    this module's docstring for the batch/fallback strategy."""
    docs = _render_with_null_overrides(chart_dir, extra_args, paths)
    if docs is not None and docs == baseline_docs:
        return list(paths)
    if len(paths) == 1:
        return []
    dead = []
    for path in paths:
        docs = _render_with_null_overrides(chart_dir, extra_args, [path])
        if docs is not None and docs == baseline_docs:
            dead.append(path)
    return dead


def find_dead_values(chart_dir, extra_args, baseline_docs, paths):
    """Dead-code candidates across every path, batched DEAD_VALUES_BATCH_
    SIZE at a time (see _find_dead_in_batch)."""
    dead = []
    for start in range(0, len(paths), DEAD_VALUES_BATCH_SIZE):
        batch = paths[start:start + DEAD_VALUES_BATCH_SIZE]
        dead.extend(_find_dead_in_batch(chart_dir, extra_args, baseline_docs, batch))
    return sorted(dead)


def check_dead_values(chart_dir, extra_args):
    values = load_yaml(chart_dir / "values.yaml") or {}
    paths = candidate_leaf_paths(values)

    print(f"Null-testing {len(paths)} values.yaml leaf(ves) against the baseline render...")
    baseline_docs = _render(chart_dir, extra_args)
    if baseline_docs is None:
        return True, "skipped — baseline render failed"

    dead = find_dead_values(chart_dir, extra_args, baseline_docs, paths)

    if not dead:
        print(f"OK: no dead values.yaml entries found ({len(paths)} checked)")
        return True, f"0/{len(paths)} dead"

    print(f"Found {len(dead)} values.yaml leaf(ves) whose value never surfaces in the "
          f"rendered chart (nulling it made no difference to the maximal render) — "
          f"report only, a human call whether it's genuinely removable:")
    for path in dead:
        print(f"  {'.'.join(path)}")

    return True, f"{len(dead)}/{len(paths)} dead (report only)"
