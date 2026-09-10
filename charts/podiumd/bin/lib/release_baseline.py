"""Resolve any release-baseline.yaml value (upgrade_docs, release_table,
or a raw git ref) against a chart's own git history — the ONE shared
"pull Chart.yaml/values.yaml as they were at that baseline" primitive
every caller needing a historical chart snapshot builds on top of, so a
real bug in this resolution (or a drift in its own error-message
wording) only ever needs fixing in one place. Consolidates what used to
be three near-identical implementations: lib.docs_consistency's own
inline block (check_docs_consistency), lib.component_docs' own load_
baseline_state/load_baseline_values, and (new) verify-release-table-
with-podiumd's own release_table_baseline lookup, plus (also new)
lib.chart.component_state_at_baseline (show-component-baseline-version).

Built on lib.gitutil's own generic git plumbing (find_repo_root/
resolve_baseline_ref/git_show_text) — this is the chart-schema-aware
layer on top of it: it knows Chart.yaml/values.yaml's own relative
paths and how to pull dependencies/parsed values/raw text lines out of
them; lib.gitutil knows none of that and stays untouched.

resolve_baseline_values (below resolve_baseline_chart_state) is the
values.yaml-ONLY sibling for a caller (show-image-baseline-version)
that never needs Chart.yaml's own dependency list at all — it shares
resolve_baseline_ref, the actual error-prone/ref-resolution part, with
resolve_baseline_chart_state, but never requires Chart.yaml to be
readable at all (unlike resolve_baseline_chart_state, which fails hard
if IT can't be read, precisely because every ITS OWN caller does need
it) — see resolve_baseline_values' own docstring for exactly how its
failure semantics differ."""
import yaml

from lib.gitutil import find_repo_root, git_show_text, resolve_baseline_ref


def resolve_baseline_chart_state(chart_dir, baseline):
    """(baseline_ref, baseline_deps, baseline_values, baseline_lines,
    error) for `baseline` (any release-baseline.yaml value — upgrade_
    docs, release_table, or a raw git ref) resolved against chart_dir's
    own git history.

    error is a ready-to-print reason (no "error: " prefix, and no
    leading baseline-name label of its own — a caller that names WHICH
    baseline key this is for in its own message, same as lib.docs_
    consistency.check_docs_consistency's own 'upgrade_docs_baseline
    "X": ...' convention, prepends that itself) on any failure:
    chart_dir isn't inside a git repository, `baseline` doesn't resolve
    to a ref at all (see lib.gitutil.resolve_baseline_ref — its own
    error message names every candidate ref tried), or Chart.yaml can't
    be read at the ref that WAS resolved (a real ref that just doesn't
    have this chart at that path, e.g. before the chart was added at
    all). baseline_ref is None on any failure, INCLUDING the last one
    (a real, resolved ref whose own Chart.yaml still can't be read is
    still an overall failure — nothing usable came out of it, so
    callers gating on "did this resolve at all" must see it that way
    too, not just the two earlier failure modes).

    baseline_deps/baseline_values/baseline_lines are []/{}/[] on ANY
    failure — never None — matching lib.docs_consistency.check_docs_
    consistency's own pre-existing convention for this exact
    resolution (safe to iterate/index into with no extra None-check);
    lib.component_docs' own load_baseline_state/load_baseline_values
    instead return (None, None)/None to their OWN callers on failure —
    a DIFFERENT, already-established external contract those two thin
    wrappers still honor themselves, translating this function's own
    []/{}/[] into their own None as needed, never the other way around.

    baseline_deps is Chart.yaml's own "dependencies" list at that ref
    (possibly [] there too on success — a chart with zero dependencies
    at that baseline is a real, valid state, not a failure). baseline_
    values is values.yaml parsed (yaml.safe_load) — {} if the file
    genuinely doesn't exist at that ref (also not itself a failure).
    baseline_lines is values.yaml's own raw text split into lines (no
    keepends — matching verify-release-table-with-podiumd's own
    `VALUES_YAML.read_text().splitlines()` convention for the CURRENT
    side), so a caller needing lib.image_version's own raw-line
    scanners (basenames_under_scope/find_matches) resolves the
    baseline side exactly the same way it already resolves the current
    one, rather than re-deriving equivalent dict-walking logic a
    second time."""
    repo_root = find_repo_root(chart_dir)
    if repo_root is None:
        return None, [], {}, [], f"{chart_dir} is not inside a git repository"

    baseline_ref, error = resolve_baseline_ref(repo_root, baseline)
    if error:
        return None, [], {}, [], error

    rel_chart_dir = chart_dir.relative_to(repo_root)
    chart_yaml_text = git_show_text(repo_root, baseline_ref, f"{rel_chart_dir}/Chart.yaml")
    if chart_yaml_text is None:
        return None, [], {}, [], f"(ref {baseline_ref}): could not read Chart.yaml at that ref"
    baseline_chart_yaml = yaml.safe_load(chart_yaml_text) or {}
    baseline_deps = baseline_chart_yaml.get("dependencies", [])

    values_text = git_show_text(repo_root, baseline_ref, f"{rel_chart_dir}/values.yaml") or ""
    baseline_values = yaml.safe_load(values_text) or {}
    baseline_lines = values_text.splitlines()

    return baseline_ref, baseline_deps, baseline_values, baseline_lines, None


def resolve_baseline_values(chart_dir, baseline):
    """(baseline_ref, baseline_values, baseline_lines, error) for
    `baseline` resolved against chart_dir's own git history — the
    values.yaml-ONLY sibling of resolve_baseline_chart_state (see this
    module's own docstring for when to use which), for a caller
    (show-image-baseline-version) that never touches Chart.yaml or its
    dependency list at all.

    Shares resolve_baseline_ref (the exact same ref-resolution
    resolve_baseline_chart_state itself uses) so the two functions can
    never drift on what a given release-baseline.yaml value resolves
    to — only the Chart.yaml-vs-values.yaml-only difference in what
    each one goes on to read is unique to either.

    Deliberately DOES NOT share resolve_baseline_chart_state's own
    "missing values.yaml isn't itself a failure" convention: a bare
    values.yaml-only lookup with nothing else to fall back on (no
    Chart.yaml dependency to at least name in a partial success) has no
    remotely useful "success" to report if THIS, its only reason for
    being called, can't be read — so a values.yaml that can't be read
    at the ref that WAS resolved is a real failure here, unlike its
    sibling. error/baseline_ref follow resolve_baseline_chart_state's
    own conventions otherwise: error has no "error: " prefix; baseline_
    ref is None on any failure; baseline_values/baseline_lines are
    {}/[] on any failure too — never None."""
    repo_root = find_repo_root(chart_dir)
    if repo_root is None:
        return None, {}, [], f"{chart_dir} is not inside a git repository"

    baseline_ref, error = resolve_baseline_ref(repo_root, baseline)
    if error:
        return None, {}, [], error

    rel_chart_dir = chart_dir.relative_to(repo_root)
    values_text = git_show_text(repo_root, baseline_ref, f"{rel_chart_dir}/values.yaml")
    if values_text is None:
        return None, {}, [], f"could not read {rel_chart_dir}/values.yaml at {baseline_ref}"
    baseline_values = yaml.safe_load(values_text) or {}
    baseline_lines = values_text.splitlines()

    return baseline_ref, baseline_values, baseline_lines, None
