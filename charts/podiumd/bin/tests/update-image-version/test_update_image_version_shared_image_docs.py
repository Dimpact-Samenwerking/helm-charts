"""Shared-image (key=MULTIPLE, global.images anchor) doc updates: its own
pseudo-component row/Changes block, not one per aliasing component.
registry_tag_exists is patched on lib.image.version, whose globals it
resolves through."""

from pathlib import Path
from types import ModuleType

import pytest


def write_values(tmp_path: Path, text):
    path = tmp_path / "values.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def write_chart_yaml(chart_dir, deps):
    """`deps`: [(name, alias_or_none), ...]."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    (chart_dir / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_doc(doc_dir, name, text):
    (doc_dir / name).write_text(text, encoding="utf-8")


def test_main_shared_image_creates_pseudo_component_row_and_changes_block(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """curl gets its own table row (chart "-") and "### curl ..." Changes
    block, not a row/section for either aliasing component."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None), ("zac", None)])
    values_path = write_values(
        tmp_path,
        (
            "global:\n"
            "  images:\n"
            "    curl: &curlImage\n"
            "      repository: curlimages/curl\n"
            f'      tag: "8.20.0@sha256:{"a" * 64}"\n'
            "keycloak-operator:\n"
            "  jobs:\n"
            "    ensureOperatorSa:\n"
            "      image: *curlImage\n"
            "zac:\n"
            "  global:\n"
            "    curlImage: *curlImage\n"
        ),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n",
    )
    write_doc(
        uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n"
    )
    write_doc(
        uiv.IMAGES_DIR,
        "images-1.0.0.yaml",
        "# Baseline: podiumd 0.9.0.\n#\n# One change:\n#   1. curl 8.20.0 -> 8.20.0.\n#\n\n"
        "# curl — 8.20.0 -> 8.20.0\n"
        "- name: curlimages/curl\n"
        "  url: docker.io/curlimages/curl\n"
        '  version: "8.20.0"\n'
        f'  digest: "sha256:{"a" * 64}"\n',
    )
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.21.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl | 8.20.0 → 8.21.0 | - | - |" in upgrade
    assert "### curl 8.20.0 → 8.21.0" in upgrade
    assert "`global.images.curl.tag` `8.20.0` → `8.21.0`" in upgrade

    # A shared-image bump changes no values.yaml schema: no values-deltas.md section.
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## curl" not in deltas

    manifest = (uiv.IMAGES_DIR / "images-1.0.0.yaml").read_text(encoding="utf-8")
    assert "#   1. curl 8.20.0 -> 8.21.0." in manifest
    assert "# curl — 8.20.0 -> 8.21.0" in manifest
    assert '"8.21.0"' in manifest

    out = capsys.readouterr().out
    assert "added table row" in out
    assert "(re)wrote '### curl ...' Changes section" in out
    assert "updated entry for curlimages/curl" in out


def test_main_shared_image_sorts_at_its_real_values_yaml_position_not_last(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: a shared-image row/section sorts at the "global" key's
    values.yaml position (before keycloak-operator), not at the end."""
    write_chart_yaml(tmp_path, [("keycloak-operator", None)])
    values_path = write_values(
        tmp_path,
        (
            "global:\n"
            "  images:\n"
            "    curl: &curlImage\n"
            "      repository: curlimages/curl\n"
            f'      tag: "8.20.0@sha256:{"a" * 64}"\n'
            "keycloak-operator:\n"
            "  jobs:\n"
            "    ensureOperatorSa:\n"
            "      image: *curlImage\n"
        ),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| keycloak-operator | 1.0.0 (unchanged) | 1.0.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### keycloak-operator 1.0.0 (unchanged)\n\n"
        "Some existing prose about keycloak-operator.\n\n"
        "- Image / digest: see [`images-1.0.0.yaml`](../images/images-1.0.0.yaml).\n",
    )
    write_doc(
        uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n"
    )
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "MULTIPLE", "curl", "8.21.0"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.index("| curl |") < upgrade.index("| keycloak-operator |")
    assert upgrade.index("### curl") < upgrade.index("### keycloak-operator")


def test_main_shared_image_insertion_gets_blank_line_when_preceding_content_has_none(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: a new section inserted after one ending without a blank
    line before EOF still gets a separating blank line (MD022/MD032)."""
    write_chart_yaml(tmp_path, [("aaa-dep", None), ("zzz-dep", None)])
    values_path = write_values(
        tmp_path,
        (
            "aaa-dep:\n"
            "  image:\n"
            "    repository: example/aaa-dep\n"
            f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
            "zzz-dep:\n"
            "  image:\n"
            "    repository: example/zzz-dep\n"
            f'    tag: "1.0.0@sha256:{"b" * 64}"\n'
        ),
    )
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "0.9.0"\n', encoding="utf-8")
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| aaa-dep | 1.0.0 (unchanged) | 1.0.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### aaa-dep 1.0.0 (unchanged)\n\n"
        "Some existing prose about aaa-dep.\n\n"
        "- Image / digest: see [`images-1.0.0.yaml`](../images/images-1.0.0.yaml).\n",
    )
    write_doc(
        uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n"
    )
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "zzz-dep", "zzz-dep", "1.0.1"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "- Image / digest: see [`images-1.0.0.yaml`](../images/images-1.0.0.yaml).\n\n### zzz-dep" in upgrade
    assert "\n\n\n" not in upgrade
