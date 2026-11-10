"""update-image-version end to end: the bump, then the real fix-doc-consistency that writes the docs.

The checker must accept the docs it leaves, and user text in them stays.
"""

from pathlib import Path
from types import ModuleType

import pytest

import lib.image.version as image_version

from tests.chart_repo import commit_text_baseline
from tests.fix_doc_run import MANIFEST
from tests.fix_doc_run import UPGRADE
from tests.fix_doc_run import bump
from tests.fix_doc_run import document_earlier_bump
from tests.fix_doc_run import point_script_at
from tests.fix_doc_run import stub_registry_and_render
from tests.fixture_data import sha256_digest

DIGEST = {fill: sha256_digest(fill) for fill in "abcdef0"}
USER_NOTE = "USER NOTE: check the OPA policies.\n"
CHART_YAML = (
    "apiVersion: v2\nname: podiumd\nversion: 4.9.0\n"
    "dependencies:\n"
    '  - name: zaakafhandelcomponent\n    version: 1.0.296\n    repository: "@example"\n    alias: zac\n'
)


def values_yaml(opa: str, curl: str) -> str:
    return (
        f'global:\n  images:\n    curl:\n      repository: curlimages/curl\n      tag: "{curl}"\n'
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@{DIGEST["a"]}"\n'
        f'  opa:\n    image:\n      repository: openpolicyagent/opa\n      tag: "{opa}"\n'
    )


@pytest.fixture
def chart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uiv: ModuleType) -> Path:
    """Baseline 4.8.5 tagged; earlier opa and curl bumps documented, with a user note in the opa section."""
    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    stub_registry_and_render(monkeypatch, DIGEST["0"], DIGEST["f"])
    commit_text_baseline(
        chart_dir, CHART_YAML, values_yaml(f"1.4.1@{DIGEST['b']}", f"8.1.0@{DIGEST['c']}"), chart_subdir=""
    )
    (chart_dir / "values.yaml").write_text(
        values_yaml(f"1.4.2@{DIGEST['e']}", f"8.2.0@{DIGEST['d']}"), encoding="utf-8"
    )
    document_earlier_bump(chart_dir, "### zac - opa ", USER_NOTE, "earlier bumps")
    point_script_at(uiv, monkeypatch, chart_dir)
    return chart_dir


def test_a_second_sidecar_bump_is_documented_from_the_baseline(
    uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    written = bump(uiv, chart, monkeypatch, "update-image-version", "zac", "opa", "1.4.3")

    assert "| zac - opa | 1.4.1 → 1.4.3 | - | - |" in written[UPGRADE]
    assert "- `zac.opa.image.tag` `1.4.1` → `1.4.3`" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]
    assert "1.4.2" not in written[UPGRADE] + written[MANIFEST]


def test_a_second_shared_image_bump_is_documented_from_the_baseline(
    uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    written = bump(uiv, chart, monkeypatch, "update-image-version", "MULTIPLE", "curl", "8.3.0")

    assert "| curl | 8.1.0 → 8.3.0 | - | - |" in written[UPGRADE]
    assert "#   1. curl 8.1.0 -> 8.3.0." in written[MANIFEST]
    assert "8.2.0" not in written[UPGRADE] + written[MANIFEST]


def test_a_shared_image_reset_to_its_baseline_leaves_no_docs(
    uiv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, DIGEST["c"]))

    written = bump(uiv, chart, monkeypatch, "update-image-version", "MULTIPLE", "curl", "8.1.0")

    assert "curl" not in written[UPGRADE] + written[MANIFEST]
    assert "| zac - opa | 1.4.1 → 1.4.2 | - | - |" in written[UPGRADE]
