"""main(): values-deltas key-change detection against the real baseline:
split out of the former, monolithic test_update_component_version.py for
pylint's too-many-lines check."""

import subprocess

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


def setup_repo(tmp_path, monkeypatch, ucv):
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    # written as raw text (not yaml.safe_dump, which alphabetizes keys) so
    # "name:" is the block's first key — same convention as the real
    # Chart.yaml, which update_chart_yaml's line-scan depends on.
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


def mock_registry_passes(monkeypatch, ucv, digest_char="b"):
    """A component whose values.yaml image path has an explicit
    "repository:" (e.g. zac) delegates its tag update to
    lib.image.version.update_image_version, which resolves
    `registry_tag_exists` via ITS OWN globals — not ucv's — so a main()
    test mocking this avoids a real network call for the delegated-path
    write itself. The upfront verification gate (fallback-path digests
    included) is covered separately by mock_verify_passes."""
    digest = "sha256:" + digest_char * 64
    monkeypatch.setattr(image_version, "registry_tag_exists", lambda host, repo, tag: (True, digest))


def mock_verify_passes(monkeypatch, ucv, digest_char="b", calls=None):
    """Fakes update-component-version's own upfront verify_component_version
    step (a lib.chart.resolve_chart_values call + lib.chart.
    check_image_versions call) so main()'s tests don't need real
    helm/network access. resolve_chart_values/check_image_versions' own
    correctness is covered by tests/lib/test_chart.py — this only fakes
    "the chart version and its images exist", returning FOUND for every
    path passed in. If `calls` is given, each check_image_versions
    invocation's image_paths argument is appended to it — lets a test
    assert the upfront check ran exactly once (no second/fallback
    re-check)."""
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


# --- main(): values-deltas key-change detection against the real baseline ---


def setup_git_repo_for_baseline_test(tmp_path, monkeypatch, ucv):
    """A real git repo with a baseline commit tagged podiumd-4.8.5, then a
    values.yaml schema key added on top — as if someone hand-edited it to
    prepare this hop, BEFORE running update-component-version. That
    ordering is exactly what the old before/after-this-script-run comparison
    could never see (the key was already present on both sides of that
    comparison); comparing against the real git baseline must catch it."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    init_git_repo(tmp_path)
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
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        '    tag: "5.0.2@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n',
        encoding="utf-8",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    # the schema edit, made BEFORE update-component-version ever runs
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        '    tag: "5.0.2@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        "  newFeature:\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "4.8.5"\n', encoding="utf-8")

    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)


def test_main_detects_key_added_before_running_against_real_baseline(ucv, tmp_path, monkeypatch):
    setup_git_repo_for_baseline_test(tmp_path, monkeypatch, ucv)
    write(
        ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n",
    )
    write(
        ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n**No gemeente `podiumd.yml` changes are required for this hop.**\n",
    )

    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "Key `zac.newFeature` was added." in deltas


def test_main_notes_when_baseline_unresolvable_for_key_detection(ucv, tmp_path, monkeypatch, capsys):
    """setup_repo's plain tmp_path (no git init) can't resolve any baseline —
    main() must say so and continue, not silently skip the note or crash.
    No values-deltas.md section gets written either — whether zac's own
    schema actually changed can never be determined without a baseline
    to compare against, and a heading with nothing under it (or worse, a
    guess) is not the answer (see sync_values_delta_sections' own
    docstring)."""
    setup_repo(tmp_path, monkeypatch, ucv)
    (tmp_path / "etc").mkdir(exist_ok=True)
    write(tmp_path / "etc" / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n')
    write(
        ucv.DOC_DIR / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n",
    )
    write(
        ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n**No gemeente `podiumd.yml` changes are required for this hop.**\n",
    )

    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "f")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    out = capsys.readouterr().out
    assert "could not resolve upgrade_docs_baseline 4.8.5" in out
    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zac" not in deltas  # no section written — schema diff couldn't be determined


def test_main_touches_only_the_target_component_end_to_end(ucv, tmp_path, monkeypatch):
    """Bumping zac must not modify anything belonging to a different
    component (openformulieren here) — its Chart.yaml entry, values.yaml
    subtree, upgrade.md row + Changes section, values-deltas.md mention,
    and images-manifest entry must all be byte-for-byte unchanged."""
    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    chart_yaml.write_text(
        "version: 4.9.0\n"
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.296\n"
        '    repository: "@example"\n'
        "    alias: zac\n"
        "  - name: openforms\n"
        "    version: 1.12.0\n"
        '    repository: "@maykinmedia"\n'
        "    alias: openformulieren\n",
        encoding="utf-8",
    )
    values_yaml.write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.0.2@sha256:{OLD_DIGEST}"\n'
        "openformulieren:\n"
        "  someFeature:\n"
        "    enabled: true\n"
        "  image:\n"
        "    repository: maykinmedia/open-forms\n"
        '    tag: "3.4.10@sha256:bbbb"\n',
        encoding="utf-8",
    )
    upgrade_text = (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openformulieren | 3.4.9 → 3.4.10 | 1.12.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### openformulieren 3.4.9 → 3.4.10 (chart 1.12.0, unchanged)\n\nblah\n"
    )
    values_deltas_text = (
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "## openformulieren 3.4.9 → 3.4.10 (chart 1.12.0, unchanged) — image tag only\n"
    )
    images_text = (
        "# One change:\n"
        "#   1. openformulieren 3.4.9 -> 3.4.10 (chart 1.12.0, unchanged).\n"
        "#\n"
        "# Open Formulieren — 3.4.9 -> 3.4.10\n"
        "- name: openformulieren\n"
        '  version: "3.4.10"\n'
        '  digest: "sha256:bbbb"\n'
    )
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(upgrade_text, encoding="utf-8")
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(values_deltas_text, encoding="utf-8")
    (images_dir / "images-4.9.0.yaml").write_text(images_text, encoding="utf-8")
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "4.8.5"\n', encoding="utf-8")

    monkeypatch.setattr(ucv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(ucv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(ucv, "IMAGES_DIR", images_dir)

    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    # zac itself changed, as expected
    assert "version: 1.0.297" in chart_yaml.read_text(encoding="utf-8")

    # openformulieren: untouched everywhere
    chart_after = chart_yaml.read_text(encoding="utf-8")
    assert "name: openforms" in chart_after
    assert "version: 1.12.0" in chart_after

    values_after = values_yaml.read_text(encoding="utf-8")
    assert "someFeature" in values_after
    assert '"3.4.10@sha256:bbbb"' in values_after

    upgrade_after = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| openformulieren | 3.4.9 → 3.4.10 | 1.12.0 (unchanged) | - |" in upgrade_after
    assert "### openformulieren 3.4.9 → 3.4.10 (chart 1.12.0, unchanged)" in upgrade_after
    assert upgrade_after.count("### openformulieren") == 1

    deltas_after = (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    # openformulieren's own section, verbatim, still there — zac (Chart.yaml's
    # FIRST dependency) gets its own brand new section inserted BEFORE it, in
    # values.yaml order, so it's no longer immediately after the doc's own H1.
    assert "## openformulieren 3.4.9 → 3.4.10 (chart 1.12.0, unchanged) — image tag only\n" in deltas_after
    assert deltas_after.count("## openformulieren") == 1

    images_after = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    # openformulieren's own header ITEM renumbers from "1." to "2." — zac's
    # own new item is correctly inserted BEFORE it (zac is Chart.yaml's
    # first dependency, openforms its second), not just appended after the
    # existing item the way an earlier, position-blind version of this
    # insertion used to. Its TEXT is still exactly what it was.
    assert "2. openformulieren 3.4.9 -> 3.4.10 (chart 1.12.0, unchanged)." in images_after
    assert "1. zac 5.0.2 -> 5.4.3 (chart 1.0.296 -> 1.0.297)." in images_after
    assert '"3.4.10"' in images_after
    assert "sha256:bbbb" in images_after
