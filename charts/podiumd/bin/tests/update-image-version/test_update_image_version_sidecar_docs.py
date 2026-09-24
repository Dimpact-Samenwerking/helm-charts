"""update-image-version's main() doc-update path for a sidecar bump (not
a dependency's own primary image) -- gets the canonical "<values_key> -
<basename>" row/section name (lib.chart.repo_and_path_resolution.
doc_row_name) and chart column "-", the row check_docs_consistency
expects. No network needed: lib.registry.registry_tag_exists is
monkeypatched via the uiv module's own imported binding (update_image_
version lives in lib.image.version, which resolves `registry_tag_exists`
via ITS OWN globals — see lib.image.version's import — so tests patch
that module directly, same as tests/lib/test_image_version.py does)."""

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
    """redis-ha's own image lives under "redis-operator" but isn't that
    dependency's own registered primary image (image_paths_for defaults
    to just "image", which doesn't exist here) -- the row/section must
    be named "redis-operator - redis", not bare "redis-operator"."""
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

    # No git repo at all here, so the baseline (and any schema diff) can
    # never be resolved — no values-deltas.md section gets written.
    deltas = (uiv.DOC_DIR / "0.9.0-to-1.0.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## redis-operator - redis" not in deltas

    out = capsys.readouterr().out
    assert "(re)wrote '### redis-operator - redis ...' Changes section" in out


def test_main_sidecar_bump_does_not_corrupt_dependencys_own_row(
    uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A pre-existing "redis-operator" row (the dependency's own,
    unrelated bump) must be left completely untouched by a redis-ha
    sidecar bump -- before the disambiguated name, find_component_row
    would have matched and overwritten THIS row instead of inserting a
    new one, since both normalize to "redisoperator"."""
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
    """Resetting the sidecar bump back to its exact baseline version must
    still correctly detect "nothing left to document" -- reset_to_baseline
    is computed from compute_changed_components' own top-level-key set,
    which never contains the disambiguated "values_key (basename)" form,
    so it must be checked against the raw values_key, not `friendly`."""
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
