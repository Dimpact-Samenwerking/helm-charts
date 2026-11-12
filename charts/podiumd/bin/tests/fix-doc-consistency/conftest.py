"""Loads fix-doc-consistency (hyphenated, not importable) as module `cdb`; the writer-then-checker harness."""

import importlib.util

from collections.abc import Sequence
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Protocol
from typing import Required
from typing import TypedDict

import pytest
import yaml

from lib.docs_consistency.check import check_docs_consistency
from lib.image import baseline_refresh
from tests.chart_repo import docs_text
from tests.chart_repo import make_doc_dirs
from tests.chart_repo import seed_chart_repo
from tests.chart_repo import tagged_baseline_repo
from tests.fixture_data import sha256_digest
from tests.git_repo import commit_all
from tests.git_repo import commit_tagged
from tests.git_repo import init_git_repo

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


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

    Patched on lib.image.docs, where regenerate_images_baseline looks it up (not cdb's binding).
    """
    import lib.image.docs as image_docs

    monkeypatch.setattr(
        image_docs, "cached_tag_exists", lambda chart_dir, repository, version: (True, sha256_digest("0"))
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
    doc_dir = seed_chart_repo(
        tmp_path,
        [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
        ],
        {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}},
    )
    write(
        doc_dir / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
        "This is the upgrade guide for environments already on **4.8.2**.\n\n"
        "## Component versions (4.9.0 vs 4.8.2)\n",
    )
    write(doc_dir / "4.8.2-to-4.9.0-values-deltas.md", "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\nNo changes.\n")
    commit_all(tmp_path, "seed docs")
    return doc_dir


@pytest.fixture
def repo_with_baseline_tag(tmp_path: Path):
    """A repo with a real "podiumd-4.8.5" tag at an older ZAC version, for load_baseline_state."""
    doc_dir = tagged_baseline_repo(
        tmp_path,
        [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ],
        {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}},
    )

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
    commit_all(tmp_path, "bump zac, stale doc table")
    return doc_dir


@pytest.fixture
def repo_with_undocumented_component_bumps(tmp_path: Path):
    """Three dependencies changed vs baseline with no "Component versions" row.

    openformulieren (default "<key>.image.tag") and keycloak-operator (registered operator.image, split
    "tag:"/"sha:") resolve an app image; redis-operator is chart-only, forcing a TODO-stub Changes section.
    """
    doc_dir = tagged_baseline_repo(
        tmp_path,
        [
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
        {
            "zac": {"image": {"tag": "5.0.1@sha256:bbbb"}},
            "openformulieren": {"image": {"tag": "3.4.10@sha256:cccc"}},
            "keycloak-operator": {"operator": {"image": {"tag": "26.6.4", "sha": "eeee"}}},
        },
    )

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
    commit_all(tmp_path, "bump openformulieren + keycloak-operator + redis-operator, no doc rows added")
    return doc_dir


@pytest.fixture
def repo_with_undocumented_sidecar_bump(tmp_path: Path):
    """redis-operator's row exists, but its bumped nested redis-ha sidecar has no row of its own.

    "curl" under "global.images" (no owning dependency) covers the bare-basename row shape.
    """
    doc_dir = tagged_baseline_repo(
        tmp_path,
        [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
            {"name": "redis-operator", "version": "0.26.0", "repository": "@opstree"},
        ],
        {
            "zac": {"image": {"tag": "5.0.1@sha256:bbbb"}},
            "redis-operator": {
                "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}
            },
            "global": {"images": {"curlImage": {"repository": "curlimages/curl", "tag": "8.10.1@sha256:cccc"}}},
        },
    )

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
    commit_all(tmp_path, "bump redis-ha's redis image + shared curl, no sidecar rows added")
    return doc_dir


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """No-op ensure_vendored_dependencies: main()-level tests use a fake chart with no vendored sub-charts."""
    monkeypatch.setattr(cdb, "ensure_vendored_dependencies", lambda chart_dir: None)


class ChartState(TypedDict, total=False):
    """One podiumd release state for writer_then_checker: Chart.yaml version and dependencies, values.yaml.

    `files` are extra files (path relative to the chart dir: text), e.g. a
    hand-written doc or a past images manifest.
    """

    version: Required[str]
    deps: Required[list[dict[str, str]]]
    values: Required[dict[str, object]]
    files: dict[str, str]


def _write_state(chart_dir: Path, state: ChartState) -> None:
    write(
        chart_dir / "Chart.yaml",
        yaml.safe_dump(
            {"apiVersion": "v2", "name": "podiumd", "version": state["version"], "dependencies": state["deps"]},
            sort_keys=False,
        ),
    )
    write(chart_dir / "values.yaml", yaml.safe_dump(state["values"], sort_keys=False))
    for rel_path, text in state.get("files", {}).items():
        (chart_dir / rel_path).parent.mkdir(parents=True, exist_ok=True)
        write(chart_dir / rel_path, text)


def _commit_baselines(chart_dir: Path, baseline: ChartState, side: ChartState | None) -> list[str]:
    """A new repository with `side` (when given) and `baseline` each tagged podiumd-<version>; returns the side paths."""
    init_git_repo(chart_dir)
    side_paths: list[str] = []
    if side is not None:
        _write_state(chart_dir, side)
        commit_tagged(chart_dir, "side path", side["version"])
        side_paths.append(side["version"])
    _write_state(chart_dir, baseline)
    commit_tagged(chart_dir, "baseline", baseline["version"])
    return side_paths


def _patch_chart_paths(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch, chart_dir: Path) -> None:
    """Make fix-doc-consistency read and write the test chart's files instead of the real ones."""
    make_doc_dirs(chart_dir)
    monkeypatch.setattr(cdb, "DOC_DIR", chart_dir / "docs" / "_UPGRADE_PATHS")
    monkeypatch.setattr(cdb, "IMAGES_DIR", chart_dir / "docs" / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", chart_dir / "Chart.yaml")
    # Settings read without an explicit chart dir (native_components()) come from the test chart too.
    monkeypatch.setattr("lib.chart.registered_paths.CHART_DIR", chart_dir)


def _point_script_at_chart(
    cdb: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    chart_dir: Path,
    baseline_version: str,
    side_paths: list[str],
    target_version: str,
) -> None:
    """Run fix-doc-consistency on the test chart, from `baseline_version` to `target_version`."""
    _patch_chart_paths(cdb, monkeypatch, chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: baseline_version)
    monkeypatch.setattr(cdb, "read_upgrade_docs_side_paths", lambda chart_dir: side_paths)
    monkeypatch.setattr(cdb, "current_chart_version", lambda: target_version)


def _run_writer_on(cdb: ModuleType, chart_dir: Path, state: ChartState) -> None:
    """Write `state` uncommitted and run fix-doc-consistency on it, as an earlier bump in the same cycle."""
    _write_state(chart_dir, state)
    cdb.main()


def _assert_checker_agrees(
    chart_dir: Path,
    baseline_version: str,
    side_paths: list[str],
    by_hand: Sequence[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """check_docs_consistency reports nothing, or exactly the `by_hand` findings, after the writer ran."""
    capsys.readouterr()
    ok, detail = check_docs_consistency(chart_dir, baseline_version, side_paths)
    out = capsys.readouterr().out
    if by_hand:
        assert detail == f"{len(by_hand)} to fix by hand", f"{detail}\n{out}"
        assert all(text in out for text in by_hand), out
    else:
        assert ok, f"{detail}\n{out}"


class WriterThenChecker(Protocol):
    def __call__(
        self,
        baseline: ChartState,
        target: ChartState,
        *,
        earlier: ChartState | None = None,
        by_hand: Sequence[str] = (),
        side: ChartState | None = None,
    ) -> dict[str, str]: ...


@pytest.fixture
def writer_then_checker(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> WriterThenChecker:
    """Run fix-doc-consistency from `baseline` (tagged podiumd-<version>) to `target`; return the docs it wrote.

    With `earlier`, the docs of that state are written first, as for an
    earlier bump in the same release cycle. Fails unless
    check_docs_consistency then reports nothing and a second
    fix-doc-consistency run changes nothing: writers and checker must agree.
    With `by_hand`, the checker must instead report exactly that many
    fix-by-hand findings, each containing one of the given texts, and
    nothing fix-doc-consistency would change.
    With `side`, that state is tagged podiumd-<version> too and declared as
    the only side path.
    """

    def run(
        baseline: ChartState,
        target: ChartState,
        *,
        earlier: ChartState | None = None,
        by_hand: Sequence[str] = (),
        side: ChartState | None = None,
    ) -> dict[str, str]:
        side_paths = _commit_baselines(tmp_path, baseline, side)
        _point_script_at_chart(cdb, monkeypatch, tmp_path, baseline["version"], side_paths, target["version"])
        if earlier is not None:
            _run_writer_on(cdb, tmp_path, earlier)
        _write_state(tmp_path, target)
        commit_all(tmp_path, "target")

        cdb.main()
        written = docs_text(tmp_path)
        _assert_checker_agrees(tmp_path, baseline["version"], side_paths, by_hand, capsys)
        cdb.main()
        assert docs_text(tmp_path) == written, "a second fix-doc-consistency run changed the docs"
        return written

    return run
