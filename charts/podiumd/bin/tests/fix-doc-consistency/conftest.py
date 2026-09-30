"""Loads fix-doc-consistency (hyphenated, not importable) as module `cdb`."""

import importlib.util
import subprocess

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
import yaml

from lib.image import baseline_refresh

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="session")
def cdb() -> ModuleType:
    loader = SourceFileLoader("fix_doc_consistency", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_doc_consistency", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_registry_tag_exists(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub registry lookups so a fixture tag without "@sha256:" never makes a real, untimed network call.

    Patched on lib.image.docs, where regenerate_images_baseline_manifest looks it up (not cdb's binding).
    """
    import lib.image.docs as image_docs

    monkeypatch.setattr(
        image_docs, "cached_tag_exists", lambda chart_dir, repository, version: (True, "sha256:" + "0" * 64)
    )


@pytest.fixture(autouse=True)
def stub_render_chart(monkeypatch: pytest.MonkeyPatch):
    """Stub render_chart to an empty render so no real `helm template` runs against synthetic fixtures.

    Patched on lib.image.baseline_refresh, where refresh_images_baseline looks it up.
    """
    monkeypatch.setattr(
        baseline_refresh,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )


@pytest.fixture
def repo(tmp_path: Path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(
        doc_dir / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
        "This is the upgrade guide for environments already on **4.8.2**.\n\n"
        "## Component versions (4.9.0 vs 4.8.2)\n",
    )
    write(doc_dir / "4.8.2-to-4.9.0-values-deltas.md", "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\nNo changes.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed docs", cwd=tmp_path)
    return doc_dir


@pytest.fixture
def repo_with_baseline_tag(tmp_path: Path):
    """A repo with a real "podiumd-4.8.5" tag at an older ZAC version, for load_baseline_state."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}))
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, stale doc table", cwd=tmp_path)
    return doc_dir


@pytest.fixture
def repo_with_undocumented_component_bumps(tmp_path: Path):
    """Three dependencies changed vs baseline with no "Component versions" row.

    openformulieren (default "<key>.image.tag") and keycloak-operator (registered operator.image, split
    "tag:"/"sha:") resolve an app image; redis-operator is chart-only, forcing a TODO-stub Changes section.
    """
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {
                        "name": "openforms",
                        "alias": "openformulieren",
                        "version": "1.11.0",
                        "repository": "@maykinmedia",
                    },
                    {"name": "keycloak-operator", "version": "1.12.1", "repository": "@adfinis"},
                    {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.1@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.4.10@sha256:cccc"}},
                "keycloak-operator": {"operator": {"image": {"tag": "26.6.4", "sha": "eeee"}}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {
                        "name": "openforms",
                        "alias": "openformulieren",
                        "version": "1.12.0",
                        "repository": "@maykinmedia",
                    },
                    {"name": "keycloak-operator", "version": "1.13.0", "repository": "@adfinis"},
                    {"name": "redis-operator", "version": "0.27.0", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.5.6@sha256:dddd"}},
                "keycloak-operator": {"operator": {"image": {"tag": "26.7.3", "sha": "ffff"}}},
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.0.2 | 1.0.297 (unchanged) | n/a |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git(
        "commit",
        "-q",
        "-m",
        "bump openformulieren + keycloak-operator + redis-operator, no doc rows added",
        cwd=tmp_path,
    )
    return doc_dir


@pytest.fixture
def repo_with_undocumented_sidecar_bump(tmp_path: Path):
    """redis-operator's row exists, but its bumped nested redis-ha sidecar has no row of its own.

    "curl" under "global.images" (no owning dependency) covers the bare-basename row shape.
    """
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {"name": "redis-operator", "version": "0.26.0", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.1@sha256:bbbb"}},
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}
                },
                "global": {"images": {"curlImage": {"repository": "curlimages/curl", "tag": "8.10.1@sha256:cccc"}}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}
                },
                "global": {"images": {"curlImage": {"repository": "curlimages/curl", "tag": "8.11.0@sha256:dddd"}}},
            }
        ),
    )
    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.0.2 | 1.0.297 (unchanged) | n/a |\n"
        "| redis-operator | - | 0.26.0 → 0.26.1 | n/a |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump redis-ha's redis image + shared curl, no sidecar rows added", cwd=tmp_path)
    return doc_dir


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """No-op ensure_vendored_dependencies: main()-level tests use a fake chart with no vendored sub-charts."""
    monkeypatch.setattr(cdb, "ensure_vendored_dependencies", lambda chart_dir: None)
