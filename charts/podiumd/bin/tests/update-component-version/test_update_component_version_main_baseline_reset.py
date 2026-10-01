"""main() integration: doc updates end-to-end, and main() against the true git
baseline (reset-to-baseline removal, collapsing repeated bumps into one entry).
Both share setup_docs()."""

import io
import subprocess
import tarfile

from pathlib import Path
from types import ModuleType

import pytest
import yaml

import lib.image.version as image_version

OLD_DIGEST = "a" * 64


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


def init_git_repo(root):
    git("init", "-q", cwd=root)
    git("config", "user.email", "test@example.com", cwd=root)
    git("config", "user.name", "Test", cwd=root)


def setup_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ucv: ModuleType):
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    # Raw text, not yaml.safe_dump (alphabetizes keys): update_chart_yaml's
    # line-scan needs "name:" first, as in the real Chart.yaml.
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        '    repository: "@example"\n'
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    return chart_yaml, values_yaml


def mock_registry_passes(monkeypatch: pytest.MonkeyPatch, ucv: ModuleType, digest_char="b"):
    """Mock registry_tag_exists in lib.image.version: the delegated tag update
    for explicit-repository images resolves it via that module's globals."""
    digest = "sha256:" + digest_char * 64
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, digest))


def mock_verify_passes(monkeypatch: pytest.MonkeyPatch, ucv: ModuleType, digest_char="b", calls=None):
    """Fake the upfront verify_component_version step (FOUND for every path)
    so tests need no helm/network. If `calls` is given, each
    check_image_versions image_paths argument is appended, to assert the
    check ran exactly once."""
    digest = "sha256:" + digest_char * 64

    def fake_check_image_versions(values, image_paths, app_version):
        if calls is not None:
            calls.append(image_paths)
        return [
            {
                "path": p,
                "repository": "ghcr.io/infonl/zaakafhandelcomponent",
                "host": "ghcr.io",
                "repo_path": "infonl/zaakafhandelcomponent",
                "exists": True,
                "digest": digest,
            }
            for p in image_paths
        ]

    monkeypatch.setattr(
        ucv, "resolve_chart_values", lambda chart_dir, dep, version, allow_pull=True: ({}, "vendored", None)
    )
    monkeypatch.setattr(ucv, "check_image_versions", fake_check_image_versions)


# --- main() integration: doc updates end-to-end ---


def setup_docs(
    ucv: ModuleType, monkeypatch: pytest.MonkeyPatch, upgrade_text, values_deltas_text=None, images_text=None
):
    (ucv.CHART_DIR / "etc").mkdir(exist_ok=True)
    write(ucv.CHART_DIR / "etc" / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n')
    doc_dir = ucv.DOC_DIR
    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md", upgrade_text)
    if values_deltas_text is not None:
        write(doc_dir / "4.8.5-to-4.9.0-values-deltas.md", values_deltas_text)
    if images_text is not None:
        write(ucv.IMAGES_DIR / "images-4.9.0.yaml", images_text)


def test_main_adds_new_component_mention_end_to_end(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup_repo(tmp_path, monkeypatch, ucv)
    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
            "## Per-environment checklist\n\nsteps\n"
        ),
        values_deltas_text=(
            "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
            "**No gemeente `podiumd.yml` changes are required for this hop.**\n"
        ),
        images_text=(
            "# One change:\n"
            "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
            "#\n"
            "# ZAC — 5.0.2 -> 5.1.0\n"
            "- name: zac\n"
            '  version: "5.1.0"\n'
            '  digest: "sha256:aaaa"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| zac | 5.0.2 → 5.4.3 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.296 → 1.0.297)" in upgrade
    assert "Helm chart `zaakafhandelcomponent` `1.0.296` → `1.0.297`" in upgrade
    assert "Image tag pin `zac.image.tag` `5.0.2` → `5.4.3`" in upgrade
    # inserted before the next "## " heading, not after it
    assert upgrade.index("### zac") < upgrade.index("## Per-environment checklist")

    # No git repo, so the baseline is unresolvable and whether zac's schema
    # changed is unknown: no section is written rather than guessing.
    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zac" not in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "1. zac 5.0.2 -> 5.4.3 (chart 1.0.296 -> 1.0.297)." in images
    assert '"5.4.3"' in images
    assert f'"sha256:{"c" * 64}"' in images


def test_main_fixes_a_preexisting_changes_numbering_gap_when_adding_an_item(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A pre-existing numbering gap in "# Changes:" is fully renumbered 1..N
    when a new item is added."""
    setup_repo(tmp_path, monkeypatch, ucv)
    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
        ),
        images_text=(
            "# Three changes:\n"
            "#   1. redis-operator v0.25.0 -> v0.26.0.\n"
            "#   3. openbao 0.28.4, unchanged.\n"
            "#\n"
            "# redis-operator — v0.25.0 -> v0.26.0\n"
            "- name: redis-operator\n"
            '  version: "v0.26.0"\n'
            '  digest: "sha256:eeee"\n'
            "# openbao — 0.28.4\n"
            "- name: openbao\n"
            '  version: "0.28.4"\n'
            '  digest: "sha256:ffff"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    # zac's item is appended and the whole list renumbered, closing the "1, 3" gap;
    # the (stubbed) closing fix-doc-consistency run sorts it.
    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "#   1. redis-operator v0.25.0 -> v0.26.0.\n" in images
    assert "#   2. openbao 0.28.4, unchanged.\n" in images
    assert "#   3. zac" in images
    assert "#   4." not in images


def test_main_updates_existing_component_mention_end_to_end(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    setup_repo(tmp_path, monkeypatch, ucv)
    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n"
            "| zac | 5.0.1 → 5.0.2 | 1.0.296 (unchanged) | - |\n\n"
            "## Changes\n\n"
            "### zac 5.0.1 → 5.0.2 (chart 1.0.296, unchanged)\n\nblah\n"
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "d")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| zac | 5.0.2 → 5.4.3 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "| zac | 5.0.1 → 5.0.2 |" not in upgrade  # old row content is gone
    # The Changes section is rewritten (not stale, not duplicated) to match
    # the row's new transition.
    assert upgrade.count("### zac") == 1
    assert "### zac 5.0.1 → 5.0.2" not in upgrade
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.296 → 1.0.297)" in upgrade


# --- main() vs the TRUE git baseline: reset-to-baseline removal, and
# collapsing repeated bumps into a single entry ---


def commit_baseline_tag(tmp_path: Path):
    init_git_repo(tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)


def test_main_removes_all_docs_when_reset_back_to_baseline(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A component reset back to its baseline version has nothing to report:
    its table row, Changes section, values-delta bullet and images-manifest
    item, entry and comment are all removed."""
    _chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    commit_baseline_tag(tmp_path)  # baseline: chart 1.0.296, zac 5.0.2@sha256:aaaa...

    # Simulate an earlier in-cycle bump to 5.5.0; chart stays at baseline.
    values_yaml.write_text(
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.5.0@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )
    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n"
            "| zac | 5.0.2 → 5.5.0 | 1.0.296 (unchanged) | - |\n\n"
            "## Changes\n\n"
            "### zac 5.0.2 → 5.5.0 (chart 1.0.296, unchanged)\n\n"
            "- Image tag pin `zac.image.tag` `5.0.2` → `5.5.0` in\n  `charts/podiumd/values.yaml`.\n"
        ),
        values_deltas_text=(
            "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
            "## zac 5.0.2 → 5.5.0 (chart 1.0.296, unchanged) — image tag only\n"
        ),
        images_text=(
            "# One change:\n"
            "#   1. zac 5.0.2 -> 5.5.0 (chart 1.0.296, unchanged).\n"
            "#\n\n"
            "# zac — 5.0.2 -> 5.5.0\n"
            "- name: zac\n"
            "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
            '  version: "5.5.0"\n'
            f'  digest: "sha256:{OLD_DIGEST}"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    # Released versions are immutable, so re-resolving 5.0.2 yields this digest.
    mock_registry_passes(monkeypatch, ucv, "a")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.0.2", "1.0.296"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| zac |" not in upgrade
    assert "### zac" not in upgrade

    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zac" not in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "Zero changes:" in images
    assert "zac 5.0.2" not in images  # the numbered "changes:" list item is gone
    assert "# zac —" not in images  # the entry's now-stale source comment is gone too
    assert "- name:" not in images  # the entry itself is gone: nothing changed vs baseline


def test_main_new_component_row_renders_new_ignoring_images_baseline(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: a dependency absent at the baseline git ref renders "(new)",
    even if images-baseline.yaml already knows its pin: source versions must
    come only from Chart.yaml/values.yaml at the baseline ref. Uses the
    fallback_paths (sub-chart default digest) route, the only one with no
    pre-existing pin to bump from."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    commit_baseline_tag(tmp_path)  # baseline: only zac, no brppersonenmock at all

    digest = "sha256:" + "b" * 64
    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        '    repository: "@example"\n'
        "    alias: zac\n"
        "  - name: brp-personen-mock\n"
        "    version: 1.2.9\n"
        '    repository: "@dimpact"\n'
        "    alias: brppersonenmock\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.0.2@sha256:{OLD_DIGEST}"\n'
        "brppersonenmock:\n"
        "  image:\n"
        '    tag: ""\n',
        encoding="utf-8",
    )
    write(
        ucv.IMAGES_DIR / "images-baseline.yaml",
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.7.0"\n'
        f'  digest: "{digest}"\n',
    )
    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n"
            "| zac | 5.0.2 (unchanged) | 1.0.296 (unchanged) | - |\n\n"
            "## Changes\n\n"
        ),
        images_text=("# Zero changes:\n#\n\n"),
    )

    def fake_check_image_versions(values, image_paths, app_version):
        return [
            {
                "path": p,
                "repository": "ghcr.io/brp-api/personen-mock",
                "host": "ghcr.io",
                "repo_path": "brp-api/personen-mock",
                "exists": True,
                "digest": digest,
            }
            for p in image_paths
        ]

    monkeypatch.setattr(
        ucv, "resolve_chart_values", lambda chart_dir, dep, version, allow_pull=True: ({}, "vendored", None)
    )
    monkeypatch.setattr(ucv, "check_image_versions", fake_check_image_versions)
    monkeypatch.setattr("sys.argv", ["update-component-version", "brppersonenmock", "2.7.0", "1.2.9"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| brppersonenmock | 2.7.0 (new) |" in upgrade


def test_main_collapses_repeated_bump_into_single_baseline_entry(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two bumps in one cycle (5.4.3 then 5.5.0) leave one entry per doc,
    baseline -> final, never an intermediate hop."""
    _chart_yaml, _values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    commit_baseline_tag(tmp_path)  # baseline: chart 1.0.296, zac 5.0.2@sha256:aaaa...
    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
        ),
        values_deltas_text="# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n",
        images_text=(
            "# Baseline: podiumd 4.8.5.\n"
            "#\n"
            "# Zero changes:\n"
            "#\n\n"
            "- name: zac\n"
            "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
            '  version: "5.0.2"\n'
            f'  digest: "sha256:{OLD_DIGEST}"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)

    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])
    ucv.main()

    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.5.0", "1.0.297"])
    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.count("| zac |") == 1
    assert "| zac | 5.0.2 → 5.5.0 | 1.0.296 → 1.0.297 | - |" in upgrade
    assert "5.4.3" not in upgrade
    assert upgrade.count("### zac") == 1
    assert "### zac 5.0.2 → 5.5.0 (chart 1.0.296 → 1.0.297)" in upgrade

    # zac has no schema beyond image.tag: no values-deltas.md section needed.
    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zac" not in deltas
    assert "5.4.3" not in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "One change:" in images
    assert "5.4.3" not in images
    assert "1. zac 5.0.2 -> 5.5.0 (chart 1.0.296 -> 1.0.297)." in images
    assert '"5.5.0"' in images
    assert f'"sha256:{"c" * 64}"' in images


def _make_vendored_tgz(charts_dir, name, version, chart_yaml):
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        data = yaml.safe_dump(chart_yaml).encode("utf-8")
        info = tarfile.TarInfo(name=f"{name}/Chart.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return tgz_path


def test_main_resolves_baseline_app_version_via_vendored_subchart_when_chart_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: openbao's baseline server.image.tag was blank (chart
    appVersion used), so old_app must resolve via the vendored-.tgz
    subchart_app_version fallback to "v2.5.0", not None, giving
    "v2.5.0 -> v2.6.0" instead of a false "(new)"."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        'version: 4.9.0\ndependencies:\n  - name: openbao\n    version: 0.28.4\n    repository: "@openbao"\n',
        encoding="utf-8",
    )
    values_yaml.write_text(
        'openbao:\n  server:\n    image:\n      tag: ""\n',
        encoding="utf-8",
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  image_paths:\n    openbao: ["server.image"]\n', encoding="utf-8"
    )
    _make_vendored_tgz(
        tmp_path / "charts", "openbao", "0.28.4", {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.0"}
    )
    commit_baseline_tag(tmp_path)  # baseline: chart 0.28.4, app version blank (subchart-only v2.5.0)

    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
        ),
        values_deltas_text="# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n",
        images_text=(
            "# Baseline: podiumd 4.8.5.\n"
            "#\n"
            "# Zero changes:\n"
            "#\n\n"
            "- name: openbao\n"
            "  url: quay.io/openbao/openbao\n"
            '  version: "v2.5.0"\n'
            f'  digest: "sha256:{OLD_DIGEST}"\n'
        ),
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "openbao", "v2.6.0", "0.28.4"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "None" not in upgrade
    assert "(new)" not in upgrade
    assert "| openbao | v2.5.0 → v2.6.0 | 0.28.4 (unchanged) | - |" in upgrade
    assert "### openbao v2.5.0 → v2.6.0 (chart 0.28.4, unchanged)" in upgrade

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "None" not in images
    assert "1. openbao v2.5.0 -> v2.6.0 (chart 0.28.4, unchanged)." in images


def test_main_renders_new_for_both_app_and_chart_version_when_never_baselined(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A dependency always has a baseline chart version, even when its image
    was never tracked there: the app renders "(new)", the chart its real
    "1.0.0 → 1.1.0", as the table row resolves it."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    chart_yaml.write_text(
        'version: 4.9.0\ndependencies:\n  - name: mi-data\n    version: 1.0.0\n    repository: "@mi"\n    alias: mi\n',
        encoding="utf-8",
    )
    values_yaml.write_text("mi:\n  enabled: false\n", encoding="utf-8")
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)
    commit_baseline_tag(tmp_path)  # baseline: chart 1.0.0, no image override at all

    # Simulate an earlier uncaptured in-cycle bump that added mi's image
    # override, moving both chart and app version.
    chart_yaml.write_text(
        'version: 4.9.0\ndependencies:\n  - name: mi-data\n    version: 1.1.0\n    repository: "@mi"\n    alias: mi\n',
        encoding="utf-8",
    )
    values_yaml.write_text(
        f'mi:\n  enabled: false\n  image:\n    repository: example/mi-data\n    tag: "2.71.0@sha256:{OLD_DIGEST}"\n',
        encoding="utf-8",
    )

    setup_docs(
        ucv,
        monkeypatch,
        upgrade_text=(
            "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
            "## Component versions (4.9.0 vs 4.8.5)\n\n"
            "| Component | App version | Helm chart | Notes |\n"
            "| --- | --- | --- | --- |\n\n"
            "## Changes\n\n"
        ),
        values_deltas_text="# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n",
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "b")
    monkeypatch.setattr("sys.argv", ["update-component-version", "mi", "2.90.0", "1.1.0"])

    ucv.main()

    upgrade = (ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "None" not in upgrade
    assert "2.71.0" not in upgrade
    assert "| mi | 2.90.0 (new) | 1.0.0 → 1.1.0 | - |" in upgrade
    assert "### mi 2.90.0 (new) (chart 1.0.0 → 1.1.0)" in upgrade


def test_main_skips_doc_updates_when_no_upgrade_doc_exists(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    setup_repo(tmp_path, monkeypatch, ucv)
    (tmp_path / "etc").mkdir(exist_ok=True)
    write(
        tmp_path / "etc" / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n'
    )  # baseline known, doc itself just missing
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # must not raise even though no docs exist

    out = capsys.readouterr().out
    assert "No upgrade doc found for target 4.9.0" in out


def test_main_skips_doc_updates_when_no_release_baseline(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # must not raise even though release-baseline.yaml doesn't exist

    out = capsys.readouterr().out
    assert "No release-baseline.yaml upgrade_docs key found" in out
