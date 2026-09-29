"""Resolve a release-baseline.yaml value (upgrade_docs, release_table, or a
raw git ref) and read Chart.yaml/values.yaml as they were at that ref.

The single shared implementation for historical chart snapshots.
resolve_baseline_values is the values.yaml-only variant."""

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.gitutil import find_repo_root
from lib.gitutil import git_show_text
from lib.gitutil import resolve_baseline_ref
from lib.yaml_types import YamlMapping
from lib.yaml_types import parse_yaml_mapping


def resolve_baseline_chart_state(
    chart_dir: Path, baseline: str
) -> tuple[str | None, list[ChartDependency], YamlMapping, list[str], str | None]:
    """(baseline_ref, baseline_deps, baseline_values, baseline_lines, error) for `baseline`.

    error is a ready-to-print reason (no "error: " prefix or baseline label;
    callers prepend that) when chart_dir isn't in a git repo, the baseline
    doesn't resolve, or Chart.yaml can't be read at the ref. On any failure
    baseline_ref is None and the rest are []/{}/[], never None.

    A chart with zero dependencies, or no values.yaml at the ref, is not a
    failure. baseline_lines is values.yaml split without keepends, so
    raw-line scanners work the same on baseline and current."""
    repo_root = find_repo_root(chart_dir)
    if repo_root is None:
        return None, [], {}, [], f"{chart_dir} is not inside a git repository"

    baseline_ref, error = resolve_baseline_ref(repo_root, baseline)
    if baseline_ref is None:
        return None, [], {}, [], error

    rel_chart_dir = chart_dir.relative_to(repo_root)
    chart_yaml_text = git_show_text(repo_root, baseline_ref, f"{rel_chart_dir}/Chart.yaml")
    if chart_yaml_text is None:
        return None, [], {}, [], f"(ref {baseline_ref}): could not read Chart.yaml at that ref"
    baseline_deps = parse_chart_dependencies(chart_yaml_text, f"{baseline_ref}:{rel_chart_dir}/Chart.yaml")

    values_text = git_show_text(repo_root, baseline_ref, f"{rel_chart_dir}/values.yaml") or ""
    baseline_values = parse_yaml_mapping(values_text, f"{baseline_ref}:{rel_chart_dir}/values.yaml")
    baseline_lines = values_text.splitlines()

    return baseline_ref, baseline_deps, baseline_values, baseline_lines, None


def resolve_baseline_values(chart_dir: Path, baseline: str) -> tuple[str | None, YamlMapping, list[str], str | None]:
    """(baseline_ref, baseline_values, baseline_lines, error): values.yaml-only variant.

    Same ref resolution as resolve_baseline_chart_state, but Chart.yaml is
    not read, and an unreadable values.yaml IS a failure here (it's the only
    thing requested). Failure conventions otherwise match: no "error: "
    prefix, baseline_ref None, {}/[] never None."""
    repo_root = find_repo_root(chart_dir)
    if repo_root is None:
        return None, {}, [], f"{chart_dir} is not inside a git repository"

    baseline_ref, error = resolve_baseline_ref(repo_root, baseline)
    if baseline_ref is None:
        return None, {}, [], error

    rel_chart_dir = chart_dir.relative_to(repo_root)
    values_text = git_show_text(repo_root, baseline_ref, f"{rel_chart_dir}/values.yaml")
    if values_text is None:
        return None, {}, [], f"could not read {rel_chart_dir}/values.yaml at {baseline_ref}"
    baseline_values = parse_yaml_mapping(values_text, f"{baseline_ref}:{rel_chart_dir}/values.yaml")
    baseline_lines = values_text.splitlines()

    return baseline_ref, baseline_values, baseline_lines, None
