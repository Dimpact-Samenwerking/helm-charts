"""update-component-version end to end: the bump, then the real fix-doc-consistency that writes the docs.

The checker must accept the docs it leaves, and user text in them stays.
"""

from pathlib import Path
from types import ModuleType

import pytest

from lib.chart import repo_and_path_resolution
from tests.chart_repo import commit_text_baseline
from tests.fix_doc_run import MANIFEST
from tests.fix_doc_run import UPGRADE
from tests.fix_doc_run import bump
from tests.fix_doc_run import document_earlier_bump
from tests.fix_doc_run import point_script_at
from tests.fix_doc_run import stub_registry_and_render
from tests.fixture_data import sha256_digest

DIGEST = {fill: sha256_digest(fill) for fill in "abcdef0"}
USER_NOTE = "USER NOTE: restart zac.\n"
REDIS_OPERATOR_TAG = f"v0.26.0@{DIGEST['a']}"


def chart_yaml(zac_chart: str, kiss_chart: str = "3.0.0", redis_operator_chart: str = "0.26.1") -> str:
    # Raw text, not yaml.safe_dump: update_chart_yaml's line scan needs "name:" first.
    return (
        "apiVersion: v2\nname: podiumd\nversion: 4.9.0\n"
        "dependencies:\n"
        f'  - name: zaakafhandelcomponent\n    version: {zac_chart}\n    repository: "@example"\n    alias: zac\n'
        f'  - name: kiss\n    version: {kiss_chart}\n    repository: "@example"\n'
        f'  - name: redis-operator\n    version: {redis_operator_chart}\n    repository: "@example"\n'
    )


def values_yaml(zac: str, opa: str, kiss: str, redis_operator: str = REDIS_OPERATOR_TAG) -> str:
    return (
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "{zac}"\n'
        f'  opa:\n    image:\n      repository: openpolicyagent/opa\n      tag: "{opa}"\n'
        f'kiss:\n  image:\n    repository: ghcr.io/kiss/kiss-frontend\n    tag: "{kiss}"\n'
        # Split "imageName:"/"imageTag:" fields, no "image:" block; the init
        # container's tag aliases imageTag's anchor, as in the real chart.
        f"redis-operator:\n  redisOperator:\n    imageName: quay.io/opstree/redis-operator\n"
        f'    imageTag: &redisOperatorImageTag "{redis_operator}"\n'
        "    initContainerImageTag: *redisOperatorImageTag\n"
    )


@pytest.fixture
def chart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType) -> Path:
    """Baseline 4.8.5 tagged; an earlier zac bump documented, with a user note in its section."""
    stub_registry_and_render(monkeypatch, DIGEST["0"], DIGEST["f"])
    commit_text_baseline(
        tmp_path,
        chart_yaml("1.0.290"),
        values_yaml(f"5.0.2@{DIGEST['a']}", f"1.4.1@{DIGEST['b']}", f"3.0.0@{DIGEST['c']}"),
        chart_subdir="",
    )
    (tmp_path / "Chart.yaml").write_text(chart_yaml("1.0.296"), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(
        values_yaml(f"5.1.0@{DIGEST['d']}", f"1.4.2@{DIGEST['e']}", f"3.0.0@{DIGEST['c']}"), encoding="utf-8"
    )
    document_earlier_bump(tmp_path, "### zac ", USER_NOTE, "earlier bump")
    point_script_at(ucv, monkeypatch, tmp_path)
    monkeypatch.setattr(
        "lib.chart.pull_and_subchart_resolution.resolve_chart_values",
        lambda chart_dir, dep, version, allow_pull=True: ({}, "vendored", None),
    )

    def check_image_versions(_chart_dir, _dep, values, pins, app_version):
        image_paths = [pin.path for pin in pins]
        return [
            {"path": p, "repository": "r", "host": "ghcr.io", "repo_path": "r", "tag": app_version}
            | {"exists": True, "digest": DIGEST["f"]}
            for p in image_paths
        ]

    monkeypatch.setattr(ucv, "check_image_versions", check_image_versions)
    return tmp_path


def test_a_second_bump_is_documented_from_the_baseline(ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch):
    written = bump(ucv, chart, monkeypatch, "update-component-version", "zac", "5.4.3", "1.0.297")

    assert "| zac | 5.0.2 → 5.4.3 | 1.0.290 → 1.0.297 | - |" in written[UPGRADE]
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.290 → 1.0.297)" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]
    assert "5.1.0" not in written[UPGRADE] + written[MANIFEST]
    assert "#   1. zac 5.0.2 -> 5.4.3 (chart 1.0.290 -> 1.0.297)." in written[MANIFEST]


def test_another_component_bump_leaves_the_first_ones_docs(
    ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    written = bump(ucv, chart, monkeypatch, "update-component-version", "kiss", "3.1.0", "3.1.0")

    assert "| kiss | 3.0.0 → 3.1.0 | 3.0.0 → 3.1.0 | - |" in written[UPGRADE]
    assert "| zac | 5.0.2 → 5.1.0 | 1.0.290 → 1.0.296 | - |" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]


def test_a_chart_only_bump(ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch):
    written = bump(ucv, chart, monkeypatch, "update-component-version", "kiss", "3.0.0", "3.0.1")

    assert "| kiss | 3.0.0 (unchanged) | 3.0.0 → 3.0.1 | - |" in written[UPGRADE]
    assert USER_NOTE in written[UPGRADE]


def test_a_split_version_field_bump_is_written_checked_and_stable(
    ucv: ModuleType, chart: Path, monkeypatch: pytest.MonkeyPatch
):
    """redis-operator: the real version check finds the repository in imageName, both tag fields are bumped,
    the checker accepts the docs, and a second run changes nothing."""
    checked: list[tuple[str, str, str]] = []

    def exists(host: str, repo: str, tag: str) -> tuple[bool, str | None]:
        checked.append((host, repo, tag))
        return True, DIGEST["f"]

    monkeypatch.setattr(ucv, "check_image_versions", repo_and_path_resolution.check_image_versions)
    monkeypatch.setattr("lib.registry.registry_tag_exists", exists)

    written = bump(ucv, chart, monkeypatch, "update-component-version", "redis-operator", "v0.27.0", "0.27.0")

    # imageTag and initContainerImageTag share one repository, and the digest writer reuses the check: one lookup.
    assert checked == [("quay.io", "opstree/redis-operator", "v0.27.0")]
    values = (chart / "values.yaml").read_text(encoding="utf-8")
    assert values.count(f'"v0.27.0@{DIGEST["f"]}"') == 1
    assert "initContainerImageTag: *redisOperatorImageTag\n" in values
    assert "v0.26.0" not in values
    assert "version: 0.27.0" in (chart / "Chart.yaml").read_text(encoding="utf-8")
    assert "| redis-operator | v0.26.0 → v0.27.0 | 0.26.1 → 0.27.0 | - |" in written[UPGRADE]

    before = (values, (chart / "Chart.yaml").read_text(encoding="utf-8"), written)
    again = bump(ucv, chart, monkeypatch, "update-component-version", "redis-operator", "v0.27.0", "0.27.0")
    after = (
        (chart / "values.yaml").read_text(encoding="utf-8"),
        (chart / "Chart.yaml").read_text(encoding="utf-8"),
        again,
    )
    assert after == before
