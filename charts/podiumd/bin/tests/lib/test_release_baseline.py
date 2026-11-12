"""lib.release_baseline against a hermetic temp git repo."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests.git_repo import commit_all
from tests.git_repo import commit_tagged
from tests.git_repo import git
from tests.git_repo import init_git_repo


@pytest.fixture
def repo(tmp_path: Path):
    init_git_repo(tmp_path)

    (tmp_path / "Chart.yaml").write_text(
        yaml.safe_dump(
            {
                "dependencies": [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}],
            }
        )
    )
    (tmp_path / "values.yaml").write_text('zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n')
    commit_all(tmp_path, "baseline")
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (tmp_path / "Chart.yaml").write_text(
        yaml.safe_dump(
            {
                "dependencies": [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}],
            }
        )
    )
    (tmp_path / "values.yaml").write_text('zac:\n  image:\n    tag: "5.1.0@sha256:bbbb"\n')
    commit_all(tmp_path, "bump zac")
    return tmp_path


def test_resolve_baseline_chart_state_resolves_real_baseline(librelease_baseline: ModuleType, repo):
    assert librelease_baseline.resolve_baseline_chart_state(repo, "4.8.5") == (
        "podiumd-4.8.5",
        [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}],
        {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}},
        ["zac:", "  image:", '    tag: "5.0.2@sha256:aaaa"'],
        None,
    )


def test_resolve_baseline_chart_state_lines_match_current_values_yaml_convention(librelease_baseline: ModuleType, repo):
    """`lines` has the splitlines() shape used for the current side, so raw-line scanners match both."""
    lines = librelease_baseline.resolve_baseline_chart_state(repo, "4.8.5")[3]
    text = (repo / "values.yaml").read_text(encoding="utf-8")
    # Compare with the ref's own content, not today's.
    shown = subprocess.run(
        ["git", "-C", str(repo), "show", "podiumd-4.8.5:values.yaml"], capture_output=True, text=True, check=True
    ).stdout
    assert lines == shown.splitlines()
    assert text != shown  # sanity: current values.yaml really did move on


def test_resolve_baseline_chart_state_error_when_ref_unresolvable(librelease_baseline: ModuleType, repo):
    *empty_state, error = librelease_baseline.resolve_baseline_chart_state(repo, "9.9.9")
    assert empty_state == [None, [], {}, []]
    assert "could not resolve baseline '9.9.9' to a git ref" in error


def test_resolve_baseline_chart_state_error_outside_git_repo(librelease_baseline: ModuleType, tmp_path: Path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    *empty_state, error = librelease_baseline.resolve_baseline_chart_state(outside, "4.8.5")
    assert empty_state == [None, [], {}, []]
    assert "is not inside a git repository" in error


def test_resolve_baseline_chart_state_error_when_chart_yaml_unreadable_at_ref(
    librelease_baseline: ModuleType, tmp_path: Path
):
    """A resolvable ref whose Chart.yaml can't be read returns baseline_ref None too (overall failure)."""
    init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("nothing chart-shaped here yet\n")
    commit_tagged(tmp_path, "no chart yet", "4.8.5")

    *empty_state, error = librelease_baseline.resolve_baseline_chart_state(tmp_path, "4.8.5")
    assert empty_state == [None, [], {}, []]
    assert "could not read Chart.yaml at that ref" in error


def test_resolve_baseline_values_resolves_real_baseline(librelease_baseline: ModuleType, repo):
    baseline = librelease_baseline.resolve_baseline_values(repo, "4.8.5")
    ref, values = baseline.ref, baseline.values
    lines, error = baseline.lines, baseline.error
    assert error is None
    assert ref == "podiumd-4.8.5"
    assert values == {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    assert lines == ["zac:", "  image:", '    tag: "5.0.2@sha256:aaaa"']


def test_resolve_baseline_values_error_when_ref_unresolvable(librelease_baseline: ModuleType, repo):
    baseline = librelease_baseline.resolve_baseline_values(repo, "9.9.9")
    ref, values = baseline.ref, baseline.values
    lines, error = baseline.lines, baseline.error
    assert ref is None
    assert values == {}
    assert lines == []
    assert "could not resolve baseline '9.9.9' to a git ref" in error


def test_resolve_baseline_values_error_outside_git_repo(librelease_baseline: ModuleType, tmp_path: Path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    baseline = librelease_baseline.resolve_baseline_values(outside, "4.8.5")
    ref, values = baseline.ref, baseline.values
    lines, error = baseline.lines, baseline.error
    assert ref is None
    assert values == {}
    assert lines == []
    assert "is not inside a git repository" in error


def test_resolve_baseline_values_error_when_values_yaml_unreadable_at_ref(
    librelease_baseline: ModuleType, tmp_path: Path
):
    """An unreadable values.yaml is a failure here: unlike resolve_baseline_chart_state, no fallback."""
    init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("no values.yaml here yet\n")
    commit_tagged(tmp_path, "no values.yaml yet", "4.8.5")

    baseline = librelease_baseline.resolve_baseline_values(tmp_path, "4.8.5")
    ref, values = baseline.ref, baseline.values
    lines, error = baseline.lines, baseline.error
    assert ref is None
    assert values == {}
    assert lines == []
    assert error == "could not read ./values.yaml at podiumd-4.8.5"


def test_resolve_baseline_values_never_requires_chart_yaml(librelease_baseline: ModuleType, tmp_path: Path):
    """A ref with values.yaml but no Chart.yaml still resolves."""
    init_git_repo(tmp_path)
    (tmp_path / "values.yaml").write_text('zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n')
    commit_tagged(tmp_path, "values.yaml, no Chart.yaml", "4.8.5")

    baseline = librelease_baseline.resolve_baseline_values(tmp_path, "4.8.5")
    ref, values, error = baseline.ref, baseline.values, baseline.error
    assert error is None
    assert ref == "podiumd-4.8.5"
    assert values == {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}


def test_resolve_baseline_chart_state_empty_dependencies_is_not_a_failure(
    librelease_baseline: ModuleType, tmp_path: Path
):
    """Zero Chart.yaml dependencies at the baseline ref is valid, not an error."""
    init_git_repo(tmp_path)
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"apiVersion": "v2", "name": "podiumd"}))
    (tmp_path / "values.yaml").write_text("{}\n")
    commit_tagged(tmp_path, "no deps yet", "4.8.5")

    *ref_deps_values, _lines, error = librelease_baseline.resolve_baseline_chart_state(tmp_path, "4.8.5")
    assert error is None
    assert ref_deps_values == ["podiumd-4.8.5", [], {}]
