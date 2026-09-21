"""main() integration: doc updates end-to-end, and main() vs the TRUE git
baseline (reset-to-baseline removal, collapsing more than one bump in a
release cycle into a single entry): split out of the former, monolithic
test_update_component_version.py for pylint's too-many-lines check.
setup_docs() is shared by both banners' tests, which is why they stay
together in one file."""

import io
import subprocess
import tarfile

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


# --- main() integration: doc updates end-to-end ---


def setup_docs(ucv, monkeypatch, upgrade_text, values_deltas_text=None, images_text=None):
    (ucv.CHART_DIR / "etc").mkdir(exist_ok=True)
    write(ucv.CHART_DIR / "etc" / "release-baseline.yaml", 'upgrade_docs: "4.8.5"\n')
    doc_dir = ucv.DOC_DIR
    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md", upgrade_text)
    if values_deltas_text is not None:
        write(doc_dir / "4.8.5-to-4.9.0-values-deltas.md", values_deltas_text)
    if images_text is not None:
        write(ucv.IMAGES_DIR / "images-4.9.0.yaml", images_text)


def test_main_adds_new_component_mention_end_to_end(ucv, tmp_path, monkeypatch):
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

    # setup_repo never initializes a git repo — the baseline can never be
    # resolved, so whether zac's own values.yaml schema actually changed
    # can never be determined either; no section is written rather than
    # guessing (see sync_values_delta_sections' own docstring).
    deltas = (ucv.DOC_DIR / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zac" not in deltas

    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "1. zac 5.0.2 -> 5.4.3 (chart 1.0.296 -> 1.0.297)." in images
    assert '"5.4.3"' in images
    assert f'"sha256:{"c" * 64}"' in images


def test_main_missing_manifest_entry_instructions_show_fully_qualified_url(ucv, tmp_path, monkeypatch, capsys):
    """Regression test: zac's own repository ("curlimages/curl", stood
    in here for a Docker-Hub-hosted image) omits the registry host
    entirely, Docker Hub's own convention — the "add manually"
    instructions printed for a missing images-manifest entry must
    still show a fully host-qualified "url:" ("docker.io/curlimages/
    curl"), not the bare, hostless string values.yaml itself happens
    to spell it as (real bug, confirmed live in images-4.9.1.yaml —
    see lib.chart.full_repository_for_path)."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
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
        f'zac:\n  image:\n    repository: curlimages/curl\n    tag: "5.0.2@sha256:{OLD_DIGEST}"\n',
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
        images_text="# Zero changes:\n#\n\n",
    )
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "c")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()

    out = capsys.readouterr().out
    assert "No existing entry for the following" in out
    assert "url: docker.io/curlimages/curl" in out


def test_main_fixes_a_preexisting_changes_numbering_gap_when_adding_an_item(ucv, tmp_path, monkeypatch):
    """The images manifest already has a gap in its own "# Changes:"
    numbering (items "1." and "3." — a THIRD, unrelated item was
    apparently removed by hand at some point without renumbering) when
    update-component-version adds zac's own brand-new item — the whole
    list must come out fully renumbered 1..N, not just the new item
    slotted in with the pre-existing gap still there (see lib.
    component_docs.insert_images_manifest_header_item/renumber_images_
    manifest_changes_items)."""
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

    # zac is the only REAL Chart.yaml dependency among these three items
    # (redis-operator/openbao are free-form prose here, matching no
    # dependency at all) — a resolved item always sorts before an
    # unresolved one, so zac's own new item becomes "1.", pushing the
    # other two down to "2."/"3." (still 2 apart in the source, but now
    # correctly sequential instead of the original 1/3 gap).
    images = (ucv.IMAGES_DIR / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "#   2. redis-operator v0.25.0 -> v0.26.0.\n" in images
    assert "#   3. openbao 0.28.4, unchanged.\n" in images
    assert "#   4." not in images
    assert ". zac" in images


def test_main_updates_existing_component_mention_end_to_end(ucv, tmp_path, monkeypatch):
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
    # the existing Changes section is rewritten from scratch (not left
    # stale, not duplicated) to match the table row's own new transition —
    # the old "5.0.1 → 5.0.2" heading is gone entirely
    assert upgrade.count("### zac") == 1
    assert "### zac 5.0.1 → 5.0.2" not in upgrade
    assert "### zac 5.0.2 → 5.4.3 (chart 1.0.296 → 1.0.297)" in upgrade


# --- main() vs the TRUE git baseline: reset-to-baseline removal, and
# collapsing more than one bump in a release cycle into a single entry ---


def commit_baseline_tag(tmp_path):
    init_git_repo(tmp_path)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)


def test_main_removes_all_docs_when_reset_back_to_baseline(ucv, tmp_path, monkeypatch):
    """A component bumped once (baseline 5.0.2 -> 5.5.0, already fully
    documented) and then reset all the way back to its baseline version
    has nothing left to report: the table row, Changes section,
    values-delta bullet, and images-manifest 'changes:' entry/comment
    must all be removed, not left describing a transition that no longer
    happened net of baseline. The manifest ENTRY itself must still show
    the correct (baseline) version/digest -- it lists every image
    regardless of change-tracking."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
    commit_baseline_tag(tmp_path)  # baseline: chart 1.0.296, zac 5.0.2@sha256:aaaa...

    # Simulate "already bumped to 5.5.0 earlier in this release cycle" --
    # chart version stays at baseline (1.0.296), only the app tag moved.
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
            "### zac 5.0.2 → 5.5.0 (chart 1.0.296, unchanged)\n\nblah\n"
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
    # Same digest baseline already recorded -- re-resolving 5.0.2 (a real,
    # immutable released version) from the registry always returns this
    # same digest, exactly like it would outside this mocked test.
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
    assert '"5.0.2"' in images  # the entry itself still lists the correct (reset) version


def test_main_new_component_row_renders_new_ignoring_images_baseline(ucv, tmp_path, monkeypatch):
    """Regression test: brppersonenmock's own Chart.yaml dependency is
    brand new (it doesn't exist at all at the podiumd-4.8.5 baseline
    commit — zac is the only dependency there), so baseline_dep resolves
    to None and the git-baseline read has nothing for it. images-
    baseline.yaml is NOT a valid substitute for that (source-version
    resolution must come strictly from Chart.yaml/values.yaml AT the
    release baseline's own git ref — see lib.upgradedoc.resolve_
    baseline_component_versions) even though it happens to already know
    this exact (repository, version, digest) pin — that's a genuinely
    different, unrelated fact (ACR-mirror digest provenance), not "was
    this component tracked at the true baseline." A component the true
    baseline git ref has nothing for renders "(new)", full stop. No
    explicit "repository:" override in podiumd's own values.yaml here
    (the "fallback_paths" branch — a sub-chart default digest) since
    that's the only bootstrap route with no PRE-EXISTING digest pin to
    bump from at all — see check_image_versions, faked below to resolve
    brppersonenmock's own real repository."""
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


def test_main_collapses_repeated_bump_into_single_baseline_entry(ucv, tmp_path, monkeypatch):
    """Bumping zac to 5.4.3 and then, within the same release cycle,
    reconsidering to 5.5.0 instead must leave exactly ONE entry in each
    doc showing baseline -> final (5.0.2 -> 5.5.0) -- never two entries,
    and never an intermediate-hop transition like "5.4.3 -> 5.5.0"."""
    chart_yaml, values_yaml = setup_repo(tmp_path, monkeypatch, ucv)
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

    # zac's own values.yaml has no schema beyond image.tag — a pure
    # version/chart bump needs no values-deltas.md section at all (see
    # sync_values_delta_sections' own docstring).
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


def test_main_resolves_baseline_app_version_via_vendored_subchart_when_chart_unchanged(ucv, tmp_path, monkeypatch):
    """Regression test (real bug, real doc): openbao's own "server.image.
    tag" is deliberately left blank at the baseline too (see settings.
    yaml's component_resolution.image_paths["openbao"]'s own comment) —
    its real baseline
    app version only resolves via the vendored-.tgz subchart_app_version
    fallback, which the raw baseline_values.yaml tag read used to never
    attempt. Its chart version (0.28.4) isn't bumped by this run either,
    so the SAME vendored .tgz backs both baseline and target — old_app
    must resolve to the real "v2.5.0" baked into that file, not None,
    rendering a real "v2.5.0 -> v2.6.0" transition instead of a false
    "(new)" one purely because of this resolution gap (the exact same
    fix already made in lib.component_docs.resolve_component_own_
    version_change for fix-doc-consistency's own doc-sync path — this
    is the same gap in update-component-version's own doc-writing
    path)."""
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


def test_main_renders_new_for_both_app_and_chart_version_when_never_baselined(ucv, tmp_path, monkeypatch):
    """Regression test (same #5-class gap as update-image-version's own
    update_docs_single_component, in update-component-version's own
    baseline resolution): a Chart.yaml dependency ALWAYS has a "version"
    field, even one never really tracked at the baseline (no image
    override existed there at all) -- old_chart used to unconditionally
    trust that raw baseline_dep["version"] regardless of whether the
    component's own app version resolved to anything real, showing a
    misleading "1.0.0 -> 1.1.0" transition implying a real prior
    baseline value existed and moved. Both mi-data's chart version
    (1.0.0 -> 1.1.0) and app version (blank -> 2.90.0) moved together,
    mid-cycle, via an earlier separate run never captured in any prior
    baseline doc -- both fields must render "(new)" together (see lib.
    upgradedoc.resolve_baseline_component_versions's own docstring)."""
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

    # Simulate the earlier, separate in-cycle bump that first introduced
    # mi's own image override -- chart AND app version both moved, never
    # captured in any prior doc.
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
    assert "1.0.0" not in upgrade
    assert "2.71.0" not in upgrade
    assert "| mi | 2.90.0 (new) | 1.1.0 (new) | - |" in upgrade
    assert "### mi 2.90.0 (new) (chart 1.1.0, new)" in upgrade


def test_main_skips_doc_updates_when_no_upgrade_doc_exists(ucv, tmp_path, monkeypatch, capsys):
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


def test_main_skips_doc_updates_when_no_release_baseline(ucv, tmp_path, monkeypatch, capsys):
    setup_repo(tmp_path, monkeypatch, ucv)
    mock_verify_passes(monkeypatch, ucv)
    mock_registry_passes(monkeypatch, ucv, "e")
    monkeypatch.setattr("sys.argv", ["update-component-version", "zac", "5.4.3", "1.0.297"])

    ucv.main()  # must not raise even though release-baseline.yaml doesn't exist

    out = capsys.readouterr().out
    assert "No release-baseline.yaml upgrade_docs key found" in out
