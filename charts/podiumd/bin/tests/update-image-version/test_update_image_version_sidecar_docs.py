"""Sidecar-bump doc updates: row/section named "<values_key> - <image-basename>"
with chart "-", as check_docs_consistency expects. registry_tag_exists is
patched on lib.image.version, whose globals it resolves through."""

import subprocess

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


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit_baseline_tag(tmp_path: Path, baseline):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", f"podiumd-{baseline}", cwd=tmp_path)
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text(f'upgrade_docs: "{baseline}"\n', encoding="utf-8")


REDIS_VALUES_TMPL = (
    "redis-operator:\n"
    "  redis-ha:\n"
    "    image:\n"
    "      repository: quay.io/opstree/redis\n"
    '      tag: "{version}@sha256:{digest}"\n'
)


def test_main_sidecar_bump_gets_disambiguated_row_name(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """redis-ha's image lives under redis-operator but isn't its primary
    image, so the row is "redis-operator - redis"."""
    write_chart_yaml(tmp_path, [("redis-operator", None)])
    values_path = write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.2", digest="a" * 64))
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
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "redis-operator", "redis", "8.6.6"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |" in upgrade
    assert "### redis-operator - redis 8.6.2 → 8.6.6" in upgrade

    # No git repo, so no baseline: no values-deltas.md section.
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## redis-operator - redis" not in deltas

    out = capsys.readouterr().out
    assert "(re)wrote '### redis-operator - redis ...' Changes section" in out


def test_main_sidecar_bump_does_not_corrupt_dependencys_own_row(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A sidecar bump leaves the dependency's own "redis-operator" row alone;
    both names normalize to "redisoperator"."""
    write_chart_yaml(tmp_path, [("redis-operator", None)])
    values_path = write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.2", digest="a" * 64))
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
        "| redis-operator | 0.25.0 → 0.26.0 | 0.25.0 → 0.26.1 | ACR mirror only |\n\n"
        "## Changes\n",
    )
    write_doc(
        uiv.DOC_DIR, "0.9.0-to-1.0.0-values-deltas.md", "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\nNo changes.\n"
    )
    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "redis-operator", "redis", "8.6.6"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator | 0.25.0 → 0.26.0 | 0.25.0 → 0.26.1 | ACR mirror only |" in upgrade
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |" in upgrade


def test_main_sidecar_reset_to_baseline_uses_raw_values_key(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Reset to baseline is detected against the raw values_key, since
    compute_changed_components never holds the disambiguated name."""
    write_chart_yaml(tmp_path, [("redis-operator", None)])
    write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.2", digest="a" * 64))
    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "VALUES_YAML", tmp_path / "values.yaml")
    commit_baseline_tag(tmp_path, "0.9.0")  # baseline: redis-ha's redis image at 8.6.2

    write_values(tmp_path, REDIS_VALUES_TMPL.format(version="8.6.6", digest="a" * 64))
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-upgrade.md",
        "# Upgrade guide: PodiumD 0.9.0 → 1.0.0\n\n"
        "## Component versions (1.0.0 vs 0.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | 1.0.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### redis-operator - redis 8.6.2 → 8.6.6\n\nblah\n",
    )
    write_doc(
        uiv.DOC_DIR,
        "0.9.0-to-1.0.0-values-deltas.md",
        "# Values deltas — PodiumD 0.9.0 → 1.0.0\n\n"
        "## redis-operator - redis 8.6.2 → 8.6.6 (chart 1.0.0, unchanged) — image tag only\n",
    )

    import lib.image.version as image_version

    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "a" * 64))
    monkeypatch.setattr("sys.argv", ["update-image-version", "redis-operator", "redis", "8.6.2"])

    uiv.main()

    upgrade = (uiv.DOC_DIR / "0.9.0-to-1.0.0-upgrade.md").read_text(encoding="utf-8")
    assert "redis-operator - redis" not in upgrade

    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "redis-operator - redis" not in deltas
