"""update-image-version end to end: the bump, then the real fix-doc-consistency that writes the docs.

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
USER_NOTE = "USER NOTE: check the OPA policies.\n"
CHART_YAML = (
    "apiVersion: v2\nname: podiumd\nversion: 4.9.0\n"
    "dependencies:\n"
    '  - name: zaakafhandelcomponent\n    version: 1.0.296\n    repository: "@example"\n    alias: zac\n'
)


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def values_yaml(opa: str, curl: str) -> str:
    return (
        f'global:\n  images:\n    curl:\n      repository: curlimages/curl\n      tag: "{curl}"\n'
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@{DIGEST["a"]}"\n'
        f'  opa:\n    image:\n      repository: openpolicyagent/opa\n      tag: "{opa}"\n'
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
def chart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uiv: ModuleType) -> Path:
    """Baseline 4.8.5 tagged; earlier opa and curl bumps documented, with a user note in the opa section."""
    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    monkeypatch.setattr(image_docs, "cached_tag_exists", lambda chart_dir, repository, version: (True, DIGEST["0"]))
    monkeypatch.setattr(
        baseline_refresh,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    git("init", "-q", cwd=chart_dir)
    git("config", "user.email", "test@example.com", cwd=chart_dir)
    git("config", "user.name", "Test", cwd=chart_dir)
    (chart_dir / "Chart.yaml").write_text(CHART_YAML, encoding="utf-8")
    (chart_dir / "values.yaml").write_text(
        values_yaml(f"1.4.1@{DIGEST['b']}", f"8.1.0@{DIGEST['c']}"), encoding="utf-8"
    )
    (chart_dir / "docs" / "_UPGRADE_PATHS").mkdir(parents=True)
    (chart_dir / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=chart_dir)
    git("commit", "-q", "-m", "baseline", cwd=chart_dir)
    git("tag", "podiumd-4.8.5", cwd=chart_dir)
    (chart_dir / "values.yaml").write_text(
        values_yaml(f"1.4.2@{DIGEST['e']}", f"8.2.0@{DIGEST['d']}"), encoding="utf-8"
    )
    run_fix_docs(chart_dir)
    upgrade = chart_dir / "docs" / UPGRADE
    text = upgrade.read_text(encoding="utf-8")
    heading = next(line for line in text.splitlines() if line.startswith("### zac - opa "))
    upgrade.write_text(text.replace(f"{heading}\n\n", f"{heading}\n\n{USER_NOTE}\n"), encoding="utf-8")
    git("add", "-A", cwd=chart_dir)
    git("commit", "-q", "-m", "earlier bumps", cwd=chart_dir)

    monkeypatch.setattr(uiv, "CHART_DIR", chart_dir)
    monkeypatch.setattr(uiv, "CHART_YAML", chart_dir / "Chart.yaml")
    monkeypatch.setattr(uiv, "VALUES_YAML", chart_dir / "values.yaml")
    monkeypatch.setattr(uiv, "complete_docs_and_finish", lambda: run_fix_docs(chart_dir))
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, DIGEST["f"]))
    return chart_dir


def bump(uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict[str, str]:
    """Run update-image-version, then require the checker to accept the docs."""
    monkeypatch.setattr("sys.argv", ["update-image-version", *argv])
    uiv.main()
    written = docs(chart)
    ok, detail = check_docs_consistency(chart, "4.8.5")
    assert ok, detail
    return written


def test_a_second_sidecar_bump_is_documented_from_the_baseline(
    uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    written = bump(uiv, chart, monkeypatch, "zac", "opa", "1.4.3")

    assert "| zac - opa | 1.4.1 → 1.4.3 | - | - |" in written[UPGRADE]
    assert "- `zac.opa.image.tag` `1.4.1` → `1.4.3`" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]
    assert "1.4.2" not in written[UPGRADE] + written[MANIFEST]


def test_a_second_shared_image_bump_is_documented_from_the_baseline(
    uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    written = bump(uiv, chart, monkeypatch, "MULTIPLE", "curl", "8.3.0")

    assert "| curl | 8.1.0 → 8.3.0 | - | - |" in written[UPGRADE]
    assert "#   1. curl 8.1.0 -> 8.3.0." in written[MANIFEST]
    assert "8.2.0" not in written[UPGRADE] + written[MANIFEST]


def test_a_shared_image_reset_to_its_baseline_leaves_no_docs(
    uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, DIGEST["c"]))

    written = bump(uiv, chart, monkeypatch, "MULTIPLE", "curl", "8.1.0")

    assert "curl" not in written[UPGRADE] + written[MANIFEST]
    assert "| zac - opa | 1.4.1 → 1.4.2 | - | - |" in written[UPGRADE]
