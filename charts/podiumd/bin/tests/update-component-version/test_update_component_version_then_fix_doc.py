"""update-component-version end to end: the bump, then the real fix-doc-consistency that writes the docs.

The checker must accept the docs it leaves, and user text in them stays.
"""

import subprocess

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

import lib.image.docs as image_docs
import lib.image.version as image_version

from lib.docs_consistency import check_docs_consistency
from lib.fix_doc_consistency.run import FixDocPaths
from lib.fix_doc_consistency.run import fix_docs
from lib.image import baseline_refresh

DIGEST = {c: "sha256:" + c * 64 for c in "abcdef0"}
UPGRADE = "_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md"
MANIFEST = "images/images-4.9.0.yaml"
USER_NOTE = "USER NOTE: restart zac.\n"


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def chart_yaml(zac_chart: str, kiss_chart: str = "3.0.0") -> str:
    # Raw text, not yaml.safe_dump: update_chart_yaml's line scan needs "name:" first.
    return (
        "apiVersion: v2\nname: podiumd\nversion: 4.9.0\n"
        "dependencies:\n"
        f'  - name: zaakafhandelcomponent\n    version: {zac_chart}\n    repository: "@example"\n    alias: zac\n'
        f'  - name: kiss\n    version: {kiss_chart}\n    repository: "@example"\n'
    )


def values_yaml(zac: str, opa: str, kiss: str) -> str:
    return (
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "{zac}"\n'
        f'  opa:\n    image:\n      repository: openpolicyagent/opa\n      tag: "{opa}"\n'
        f'kiss:\n  image:\n    repository: ghcr.io/kiss/kiss-frontend\n    tag: "{kiss}"\n'
    )


def docs(chart_dir: Path) -> dict[str, str]:
    root = chart_dir / "docs"
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def rename(old: Path, new: Path) -> None:
    old.rename(new)


def run_fix_docs(chart_dir: Path) -> None:
    fix_docs(
        FixDocPaths(chart_dir, chart_dir / "docs" / "_UPGRADE_PATHS", chart_dir / "docs" / "images", rename),
        "4.9.0",
        "4.8.5",
    )


@pytest.fixture
def chart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType) -> Path:
    """Baseline 4.8.5 tagged; an earlier zac bump documented, with a user note in its section."""
    monkeypatch.setattr(image_docs, "cached_tag_exists", lambda chart_dir, repository, version: (True, DIGEST["0"]))
    monkeypatch.setattr(
        baseline_refresh,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "Chart.yaml").write_text(chart_yaml("1.0.290"), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(
        values_yaml(f"5.0.2@{DIGEST['a']}", f"1.4.1@{DIGEST['b']}", f"3.0.0@{DIGEST['c']}"), encoding="utf-8"
    )
    (tmp_path / "docs" / "_UPGRADE_PATHS").mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)
    (tmp_path / "Chart.yaml").write_text(chart_yaml("1.0.296"), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(
        values_yaml(f"5.1.0@{DIGEST['d']}", f"1.4.2@{DIGEST['e']}", f"3.0.0@{DIGEST['c']}"), encoding="utf-8"
    )
    run_fix_docs(tmp_path)
    upgrade = tmp_path / "docs" / UPGRADE
    text = upgrade.read_text(encoding="utf-8")
    heading = next(line for line in text.splitlines() if line.startswith("### zac "))
    upgrade.write_text(text.replace(f"{heading}\n\n", f"{heading}\n\n{USER_NOTE}\n"), encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "earlier bump", cwd=tmp_path)

    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", tmp_path / "Chart.yaml")
    monkeypatch.setattr(ucv, "VALUES_YAML", tmp_path / "values.yaml")
    monkeypatch.setattr(ucv, "complete_docs_and_finish", lambda: run_fix_docs(tmp_path))
    monkeypatch.setattr(
        ucv, "resolve_chart_values", lambda chart_dir, dep, version, allow_pull=True: ({}, "vendored", None)
    )
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, DIGEST["f"]))

    def check_image_versions(values, image_paths, app_version):
        return [
            {"path": p, "repository": "r", "host": "ghcr.io", "repo_path": "r", "exists": True, "digest": DIGEST["f"]}
            for p in image_paths
        ]

    monkeypatch.setattr(ucv, "check_image_versions", check_image_versions)
    return tmp_path


def bump(ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict[str, str]:
    """Run update-component-version, then require the checker to accept the docs."""
    monkeypatch.setattr("sys.argv", ["update-component-version", *argv])
    ucv.main()
    written = docs(chart)
    ok, detail = check_docs_consistency(chart, "4.8.5")
    assert ok, detail
    return written


def test_a_second_bump_is_documented_from_the_baseline(ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch):
    written = bump(ucv, chart, monkeypatch, "zac", "5.4.3", "1.0.297")

    assert "| zac | 5.0.2 → 5.4.3 | 1.0.290 → 1.0.297 | - |" in written[UPGRADE]
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.290 → 1.0.297)" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]
    assert "5.1.0" not in written[UPGRADE] + written[MANIFEST]
    assert "#   1. zac 5.0.2 -> 5.4.3 (chart 1.0.290 -> 1.0.297)." in written[MANIFEST]


def test_another_component_bump_leaves_the_first_ones_docs(
    ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    written = bump(ucv, chart, monkeypatch, "kiss", "3.1.0", "3.1.0")

    assert "| kiss | 3.0.0 → 3.1.0 | 3.0.0 → 3.1.0 | - |" in written[UPGRADE]
    assert "| zac | 5.0.2 → 5.1.0 | 1.0.290 → 1.0.296 | - |" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]


def test_a_chart_only_bump(ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch):
    written = bump(ucv, chart, monkeypatch, "kiss", "3.0.0", "3.0.1")

    assert "| kiss | 3.0.0 (unchanged) | 3.0.0 → 3.0.1 | - |" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]
