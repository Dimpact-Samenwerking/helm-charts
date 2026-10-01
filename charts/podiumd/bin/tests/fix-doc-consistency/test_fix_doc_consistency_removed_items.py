"""main() writes the rows and sections of removed components and images, and check_docs_consistency accepts them."""

import importlib.util
import subprocess

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest
import yaml

VERIFY_PODIUMD = Path(__file__).resolve().parents[2] / "verify-podiumd"
ZAC = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"}
KISS = {"name": "kiss", "version": "3.1.1", "repository": "@kiss"}


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write_chart(chart_dir: Path, version: str, deps: list[dict[str, str]], values: dict[str, object]) -> None:
    (chart_dir / "Chart.yaml").write_text(
        yaml.safe_dump(
            {"apiVersion": "v2", "name": "podiumd", "version": version, "dependencies": deps}, sort_keys=False
        )
    )
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False))


def zac_values(tag: str, *, with_opa: bool) -> dict[str, object]:
    zac: dict[str, object] = {
        "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": f"{tag}@sha256:aaaa"}
    }
    if with_opa:
        zac["opa"] = {"image": {"repository": "openpolicyagent/opa", "tag": "1.4.2@sha256:bbbb"}}
    return {"zac": zac}


@pytest.fixture
def vp() -> ModuleType:
    loader = SourceFileLoader("verify_podiumd", str(VERIFY_PODIUMD))
    spec = importlib.util.spec_from_file_location("verify_podiumd", VERIFY_PODIUMD, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_main_writes_removed_items_that_the_checker_accepts(
    cdb: ModuleType, vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    kiss_values = {"kiss": {"image": {"repository": "ghcr.io/kiss/kiss-frontend", "tag": "3.1.1@sha256:cccc"}}}
    write_chart(tmp_path, "4.8.5", [ZAC, KISS], {**zac_values("5.4.4", with_opa=True), **kiss_values})
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write_chart(tmp_path, "4.9.0", [ZAC], zac_values("5.4.5", with_opa=False))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir()
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "remove kiss and the opa sidecar", cwd=tmp_path)

    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: "4.8.5")
    monkeypatch.setattr(cdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdb, "IMAGES_DIR", doc_dir.parent / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", tmp_path / "Chart.yaml")
    monkeypatch.setattr(cdb, "VALUES_YAML", tmp_path / "values.yaml")
    monkeypatch.setattr(cdb, "current_chart_version", lambda: "4.9.0")
    cdb.main()

    doc = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text()
    assert (
        "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n"
        "| zac - opa | 1.4.2 (removed) | - | - |\n"
        "| kiss | 3.1.1 (removed) | 3.1.1 (removed) | - |\n"
    ) in doc
    assert "### zac - opa 1.4.2 (removed)\n\nPodiumD 4.9.0 removes **zac - opa** (was 1.4.2).\n" in doc
    assert "### kiss 3.1.1 (removed)\n\nPodiumD 4.9.0 removes **kiss** (was 3.1.1).\n" in doc
    assert "kiss" not in (doc_dir.parent / "images" / "images-4.9.0.yaml").read_text()
    capsys.readouterr()

    ok, detail = vp.check_docs_consistency(tmp_path, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert "kiss" not in out and "opa" not in out, out
    assert ok is True, detail
