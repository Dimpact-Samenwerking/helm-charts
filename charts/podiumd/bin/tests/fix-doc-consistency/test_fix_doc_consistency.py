"""find_collisions, update_title_line, update_component_versions_heading,
remaining_mentions, main — pure logic plus a main() integration test
against a real, hermetic temp git repo (git mv shells out to git, so it
needs a real working tree). existing_doc_baselines itself is
lib.component_docs' own (see tests/lib/test_component_docs.py) — this
script only calls through it, exercised here via main()."""
import subprocess

import pytest
import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


# --- find_collisions ---

def test_find_collisions_detects_multiple_sources_for_same_suffix(cdb, tmp_path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md"), ("4.8.3", tmp_path / "b.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    collisions = cdb.find_collisions(by_suffix)
    assert set(collisions.keys()) == {"upgrade"}


def test_find_collisions_empty_when_all_unique(cdb, tmp_path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    assert cdb.find_collisions(by_suffix) == {}


# --- update_title_line ---

def test_update_title_line_replaces_arrow_form(cdb):
    text = "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\nbody\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert new_text.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"


def test_update_title_line_replaces_ascii_arrow(cdb):
    text = "# Upgrade guide: PodiumD 4.8.2 -> 4.9.0\nbody\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.3 -> 4.9.0" in new_text.splitlines()[0]


def test_update_title_line_only_touches_first_line(cdb):
    text = "# Title 4.8.2 → 4.9.0\nsome body mentioning 4.8.2 again\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.2 again" in new_text.splitlines()[1]  # body untouched


def test_update_title_line_no_match_returns_unchanged(cdb):
    text = "# Something else entirely\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- update_component_versions_heading ---

def test_update_component_versions_heading_replaces_match(cdb):
    text = "## Component versions (4.9.0 vs 4.8.2)\n\nmore\n"
    new_text, changed = cdb.update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "## Component versions (4.9.0 vs 4.8.3)" in new_text


def test_update_component_versions_heading_no_match(cdb):
    text = "no such heading here\n"
    new_text, changed = cdb.update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- remaining_mentions ---

def test_remaining_mentions_finds_all_lines(cdb):
    text = "line one 4.8.2\nline two\nline three 4.8.2 again\n"
    assert cdb.remaining_mentions(text, "4.8.2") == [1, 3]


def test_remaining_mentions_empty_when_absent(cdb):
    assert cdb.remaining_mentions("nothing here\n", "4.8.2") == []


# --- main() integration, against a real temp git repo ---

@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(doc_dir / "4.8.2-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
          "This is the upgrade guide for environments already on **4.8.2**.\n\n"
          "## Component versions (4.9.0 vs 4.8.2)\n")
    write(doc_dir / "4.8.2-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\nNo changes.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed docs", cwd=tmp_path)
    return doc_dir


def set_argv_and_dir(cdb, monkeypatch, doc_dir, new_baseline, target="4.9.0"):
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency", new_baseline])
    monkeypatch.setattr(cdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdb, "IMAGES_DIR", doc_dir.parent / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", doc_dir.parents[1] / "Chart.yaml")
    monkeypatch.setattr(cdb, "VALUES_YAML", doc_dir.parents[1] / "values.yaml")
    monkeypatch.setattr(cdb, "current_chart_version", lambda: target)


def test_main_renames_and_updates_title_and_heading(cdb, repo, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")
    cdb.main()  # success path must not raise

    assert not (repo / "4.8.2-to-4.9.0-upgrade.md").exists()
    upgrade = (repo / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"
    assert "## Component versions (4.9.0 vs 4.8.3)" in upgrade
    assert "already on **4.8.2**" in upgrade  # free-form prose left for manual review

    deltas = (repo / "4.8.3-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.splitlines()[0] == "# Values deltas — PodiumD 4.8.3 → 4.9.0"


def test_main_rewrites_sibling_doc_references_within_the_docs_themselves(cdb, repo, monkeypatch):
    """A values-deltas doc pointing at its sibling upgrade.md by the old
    baseline (e.g. a markdown link left over from the last rebase) must be
    rewritten too, not just flagged for manual review — this chart
    supports exactly one upgrade path per target, so every such reference
    always means the current baseline."""
    write(repo / "4.8.2-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\n"
          "Background and failure modes in "
          "[`4.8.2-to-4.9.0-upgrade.md`](4.8.2-to-4.9.0-upgrade.md).\n")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")

    cdb.main()

    deltas = (repo / "4.8.3-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "[`4.8.3-to-4.9.0-upgrade.md`](4.8.3-to-4.9.0-upgrade.md)" in deltas
    assert "4.8.2" not in deltas


def test_main_is_tracked_by_git_after_rename(cdb, repo, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")
    cdb.main()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo.parents[1],
                             capture_output=True, text=True).stdout
    assert "R  " in status or "renamed" in status.lower() or "4.8.3-to-4.9.0-upgrade.md" in status


def test_main_refuses_on_collision(cdb, repo, monkeypatch):
    write(repo / "4.8.3-to-4.9.0-upgrade.md", "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n")
    original = (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")

    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1
    # nothing renamed, not even the non-conflicting values-deltas doc (all-or-nothing)
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8") == original
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").exists()


def test_main_creates_all_three_stubs_when_target_has_no_docs(cdb, repo, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo, "1.0.0", target="9.9.9")
    cdb.main()  # must not raise — creating stubs is success, not an error

    for suffix in cdb.STANDARD_SUFFIXES:
        stub = repo / f"1.0.0-to-9.9.9-{suffix}.md"
        assert stub.is_file()
        assert "1.0.0" in stub.read_text(encoding="utf-8")
        assert "9.9.9" in stub.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "created (was missing)" in out


def test_main_creates_only_the_missing_standard_doc(cdb, repo, monkeypatch):
    # repo fixture already has upgrade + values-deltas for 4.9.0 baseline 4.8.2;
    # gemeente-specific is missing for this target.
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()

    assert (repo / "4.8.2-to-4.9.0-gemeente-specific.md").is_file()
    # the pre-existing docs were left alone (already at baseline 4.8.2)
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").is_file()
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").is_file()


def test_main_already_at_new_baseline_is_a_noop(cdb, repo, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").exists()
    out = capsys.readouterr().out
    assert "already baseline 4.8.2 — unchanged" in out


def test_main_already_at_new_baseline_still_fixes_a_stale_sibling_reference(cdb, repo, monkeypatch, capsys):
    """A doc already at the target baseline is otherwise a pure no-op
    (see test above) — except a stale sibling-doc reference left over
    from an earlier, incomplete rebase (the doc's OWN baseline already
    moved past it, but a link inside it didn't) must still be fixed, or
    nothing else in this script would ever touch that doc again."""
    write(repo / "4.8.2-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\n"
          "Background and failure modes in "
          "[`4.8.1-to-4.9.0-upgrade.md`](4.8.1-to-4.9.0-upgrade.md).\n")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    deltas = (repo / "4.8.2-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "[`4.8.2-to-4.9.0-upgrade.md`](4.8.2-to-4.9.0-upgrade.md)" in deltas
    assert "4.8.1" not in deltas
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-values-deltas.md: already baseline 4.8.2 — fixed stale sibling doc reference(s)" in out


def test_main_no_argument_and_no_release_baseline_errors(cdb, monkeypatch):
    """Zero arguments is otherwise valid (falls back to release-baseline's
    content — see set_argv_and_dir's own baseline-arg tests) — only the
    combination of no argument AND no release-baseline to fall back to is
    an error. release_baseline mocked directly (never CHART_YAML/DOC_DIR)
    so this can't accidentally read/touch the real chart's own
    release-baseline/docs if the mock were ever missed."""
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "release_baseline", lambda chart_dir: None)
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero_without_touching_anything(cdb, repo, monkeypatch, capsys, flag):
    """`--help` must never be treated as `new_baseline` — passing it used to
    run the whole bump for real with a literal baseline of "--help",
    renaming docs to "--help-to-<target>-*.md". It must instead print the
    module docstring and exit 0, leaving every doc untouched."""
    before = sorted(p.name for p in repo.iterdir())
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency", flag])
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == cdb.__doc__ + "\n"
    assert sorted(p.name for p in repo.iterdir()) == before


@pytest.mark.parametrize("bogus", ["4.8", "4.8.2-rc1", "v4.8.2", "latest", "4.8.2.1", ""])
def test_main_rejects_non_semver_baseline_without_touching_anything(cdb, repo, monkeypatch, capsys, bogus):
    """Anything that isn't a bare MAJOR.MINOR.PATCH — a two-part version, a
    pre-release suffix, a "v" prefix, "latest", four parts, or empty — must
    be rejected up front with a clear error, not silently treated as a
    literal baseline (see BASELINE_VERSION_RE). "--help"/"-h" are their own,
    earlier case (see test_main_help_flag_...), not part of this check."""
    before = sorted(p.name for p in repo.iterdir())
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency", bogus])
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1
    assert "not a valid MAJOR.MINOR.PATCH version" in capsys.readouterr().out
    assert sorted(p.name for p in repo.iterdir()) == before


def test_main_accepts_valid_semver_baseline(cdb, monkeypatch):
    assert cdb.BASELINE_VERSION_RE.match("4.8.2")
    assert cdb.BASELINE_VERSION_RE.match("10.20.300")


# --- canonical_version_cell ---

def test_canonical_version_cell_arrow_form(cdb):
    assert cdb.canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(cdb):
    assert cdb.canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


def test_canonical_version_cell_v_prefix_counts_as_unchanged(cdb):
    assert cdb.canonical_version_cell("v0.9.352", "0.9.352") == "0.9.352 (unchanged)"


# --- fix_component_version_table ---

def target_deps_and_values():
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    return deps, values


def test_fix_component_version_table_corrects_stale_source(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, target_deps, target_values, baseline_deps, baseline_values
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "5.0.2 → 5.1.0" in new_text
    assert "1.0.297 → 1.0.257" in new_text
    assert "5.0.1" not in new_text
    assert "1.0.251" not in new_text
    assert "ACR mirror only" in new_text  # notes column untouched


def test_fix_component_version_table_leaves_correct_row_untouched(cdb):
    text = (
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_unmatched_component_reported(cdb):
    text = (
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Totally Unknown Thing | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, target_deps, target_values, [{"name": "zac", "version": "1.0.297"}], {}
    )
    assert changed == []
    assert unmatched == ["Totally Unknown Thing"]
    assert new_text == text


def test_fix_component_version_table_no_baseline_data_reported_unresolved(cdb):
    text = (
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, target_deps, target_values, None, None
    )
    assert changed == []
    assert unresolved == ["ZAC (Zaakafhandelcomponent)"]
    assert new_text == text


# --- current_chart_version ---

def test_current_chart_version_reads_chart_yaml(cdb, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("version: 4.9.0\nname: podiumd\n", encoding="utf-8")
    monkeypatch.setattr(cdb, "CHART_YAML", chart_yaml)
    assert cdb.current_chart_version() == "4.9.0"


# --- extract_images_baseline / update_sibling_doc_refs / update_images_manifest_baseline ---

def test_extract_images_baseline_finds_version(cdb):
    text = "# Baseline: podiumd 4.8.2. Re-verify before release.\n"
    assert cdb.extract_images_baseline(text) == "4.8.2"


def test_extract_images_baseline_none_when_absent(cdb):
    assert cdb.extract_images_baseline("no header here\n") is None


def test_update_sibling_doc_refs_rewrites_whatever_baseline_is_named(cdb):
    text = "See docs/_UPGRADE_PATHS/4.8.3-to-4.9.0-upgrade.md for details.\n"
    new_text, changed = cdb.update_sibling_doc_refs(text, "4.9.0", "4.8.5")
    assert changed is True
    assert "4.8.5-to-4.9.0-upgrade.md" in new_text
    assert "4.8.3" not in new_text


def test_update_sibling_doc_refs_ignores_other_targets(cdb):
    text = "See docs/_UPGRADE_PATHS/4.7.8-to-4.8.0-upgrade.md for an older hop.\n"
    new_text, changed = cdb.update_sibling_doc_refs(text, "4.9.0", "4.8.5")
    assert changed is False
    assert new_text == text


def test_update_images_manifest_baseline_rewrites_both_lines(cdb):
    text = (
        "# Baseline: podiumd 4.8.2 (main @ abc1234). Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.2.\n"
    )
    new_text, changed = cdb.update_images_manifest_baseline(text, "4.9.0", "4.8.5")
    assert changed is True
    assert "Baseline: podiumd 4.8.5 (main @ abc1234)" in new_text
    assert "podiumd 4.9.0 vs 4.8.5" in new_text


def test_update_images_manifest_baseline_no_match_returns_unchanged(cdb):
    text = "no baseline lines here\n"
    new_text, changed = cdb.update_images_manifest_baseline(text, "4.9.0", "4.8.5")
    assert changed is False
    assert new_text == text


# --- main() integration: images-<target>.yaml handling ---

def test_main_creates_images_manifest_when_missing(cdb, repo, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")
    cdb.main()

    images_path = repo.parent / "images" / "images-4.9.0.yaml"
    assert images_path.is_file()
    text = images_path.read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.3" in text
    assert "podiumd 4.9.0 vs 4.8.3" in text
    assert "4.8.3-to-4.9.0-upgrade.md" in text
    assert text.strip().endswith("[]")


def test_main_bumps_existing_images_manifest(cdb, repo, monkeypatch):
    images_path = repo.parent / "images" / "images-4.9.0.yaml"
    write(images_path,
          "# Baseline: podiumd 4.8.2 (main @ abc1234). Re-verify before release.\n"
          "#\n"
          "# Images new or changed in podiumd 4.9.0 vs 4.8.2.\n"
          "#\n"
          "# See docs/_UPGRADE_PATHS/4.8.2-to-4.9.0-upgrade.md for the operator upgrade notes.\n\n"
          "- name: zac\n"
          '  url: ghcr.io/infonl/zaakafhandelcomponent\n'
          '  version: "5.1.0"\n'
          '  digest: "sha256:aaaa"\n')
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.5" in text
    assert "podiumd 4.9.0 vs 4.8.5" in text
    assert "4.8.5-to-4.9.0-upgrade.md" in text
    assert "- name: zac" in text  # entries untouched


def test_main_images_manifest_already_at_baseline_is_noop(cdb, repo, monkeypatch, capsys):
    images_path = repo.parent / "images" / "images-4.9.0.yaml"
    original = "# Baseline: podiumd 4.8.2 (main @ abc1234). Re-verify before release.\n"
    write(images_path, original)
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()

    assert images_path.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "images-4.9.0.yaml: already baseline 4.8.2 — unchanged" in out


# --- main() integration: end-to-end component-version-table correction ---

@pytest.fixture
def repo_with_baseline_tag(tmp_path):
    """A repo whose git history has a real "podiumd-4.8.5" tag at an older
    ZAC version, so load_baseline_state can resolve it for real."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}))
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, stale doc table", cwd=tmp_path)
    return doc_dir


def test_main_corrects_stale_table_using_real_baseline_tag(cdb, repo_with_baseline_tag, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_baseline_tag, "4.8.5")
    cdb.main()

    upgrade = (repo_with_baseline_tag / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "5.0.2 → 5.1.0" in upgrade
    assert "1.0.297 → 1.0.257" in upgrade
    assert "5.0.1" not in upgrade
    assert "1.0.251" not in upgrade
    out = capsys.readouterr().out
    assert "Correcting component version table" in out


# --- main() integration: values-deltas.md missing key-change mentions ---

@pytest.fixture
def repo_with_undocumented_schema_change(tmp_path):
    """zac's values.yaml drops the "brpApi.extendWithZaaktype" key between the
    baseline tag and HEAD, but values-deltas.md never mentions it — the real
    gap this feature exists to catch up on."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:bbbb"},
                "brpApi": {"protocollering": {"verwerking": {"extendWithZaaktype": False, "otherKey": True}}}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"},
                # extendWithZaaktype gone, otherKey remains — undocumented
                "brpApi": {"protocollering": {"verwerking": {"otherKey": True}}}},
    }))
    write(doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
          "No gemeente podiumd.yml changes are required for this hop.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, schema change undocumented", cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_key_change_mention(cdb, repo_with_undocumented_schema_change, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8")
    assert "- Key `zac.brpApi.protocollering.verwerking.extendWithZaaktype` was removed.\n" in deltas
    assert "No gemeente podiumd.yml changes are required" in deltas  # existing content preserved
    out = capsys.readouterr().out
    assert "Adding missing key-change mentions" in out


def test_main_does_not_duplicate_already_mentioned_key_change(cdb, repo_with_undocumented_schema_change,
                                                                monkeypatch, capsys):
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "Removed `zac.brpApi.protocollering.verwerking.extendWithZaaktype` — no longer needed.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8")
    assert deltas.count("extendWithZaaktype") == 1
    out = capsys.readouterr().out
    assert "Adding missing key-change mentions" not in out


# --- replace_version_pair ---

def test_replace_version_pair_arrow_form(cdb):
    assert cdb.replace_version_pair("# ZAC — 5.0.1 -> 5.1.0\n", "5.0.2", "5.1.0") == \
        "# ZAC — 5.0.2 -> 5.1.0\n"


def test_replace_version_pair_unicode_arrow_preserved(cdb):
    assert cdb.replace_version_pair("# ZAC — 5.0.1 → 5.1.0\n", "5.0.2", "5.1.0") == \
        "# ZAC — 5.0.2 → 5.1.0\n"


def test_replace_version_pair_no_match_returns_unchanged(cdb):
    line = "# no version pair here\n"
    assert cdb.replace_version_pair(line, "1.0.0", "2.0.0") == line


# --- resolve_entry_version ---

def test_resolve_entry_version_finds_matching_path(cdb):
    paths = {("zac",): "5.1.0@sha256:aaaa", ("zgw-office-addin", "frontend"): "v0.9.352@sha256:bbbb"}
    assert cdb.resolve_entry_version("zac", paths) == "5.1.0"
    assert cdb.resolve_entry_version("zgw-office-addin-frontend", paths) == "v0.9.352"


def test_resolve_entry_version_none_when_unresolvable(cdb):
    assert cdb.resolve_entry_version("totally-unknown", {}) is None


# --- fix_images_manifest_entries ---

def test_fix_images_manifest_entries_corrects_stale_source(cdb):
    text = (
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(text, target_values, baseline_values)
    assert unresolved == []
    assert changed == [("zac", "5.0.2", "5.1.0")]
    assert "# ZAC — 5.0.2 -> 5.1.0" in new_text
    assert "5.0.1" not in new_text


def test_fix_images_manifest_entries_leaves_correct_entry_untouched(cdb):
    text = (
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
    )
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(text, target_values, baseline_values)
    assert changed == []
    assert new_text == text


def test_fix_images_manifest_entries_reports_missing_comment(cdb):
    text = "- name: zgw-office-addin-backend\n  version: \"v0.9.352\"\n"
    target_values = {"zgw-office-addin": {"backend": {"image": {"tag": "v0.9.352@sha256:aaaa"}}}}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(text, target_values, {})
    assert changed == []
    assert unresolved == ["zgw-office-addin-backend"]
    assert new_text == text


def test_fix_images_manifest_entries_reports_unresolvable_baseline(cdb):
    text = "# ZAC — 5.0.1 -> 5.1.0\n- name: zac\n  version: \"5.1.0\"\n"
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(text, target_values, {})
    assert changed == []
    assert unresolved == ["zac"]
    assert new_text == text


def test_fix_images_manifest_entries_fixes_shared_group_comment_via_either_entry(cdb):
    """zgw-office-addin's frontend + backend share one comment (backend has
    none of its own, separated by a blank line) — backend must be fixed via
    that shared comment, not reported as unresolved just because there's no
    comment directly above it."""
    text = (
        "# ZGW Office Add-in — v0.9.300 -> v0.9.352\n"
        "- name: zgw-office-addin-frontend\n"
        '  version: "v0.9.352"\n'
        "\n"
        "- name: zgw-office-addin-backend\n"
        '  version: "v0.9.352"\n'
    )
    target_values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "v0.9.352@sha256:aaaa"}},
        "backend": {"image": {"tag": "v0.9.352@sha256:bbbb"}},
    }}
    baseline_values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "v0.9.313@sha256:cccc"}},
        "backend": {"image": {"tag": "v0.9.313@sha256:dddd"}},
    }}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(text, target_values, baseline_values)
    assert unresolved == []
    assert changed == [("zgw-office-addin-frontend", "v0.9.313", "v0.9.352")]
    assert "# ZGW Office Add-in — v0.9.313 -> v0.9.352" in new_text
    assert "v0.9.300" not in new_text


# --- main() integration: images-manifest entry-comment correction ---

def test_main_corrects_stale_images_manifest_entry_comment(cdb, repo_with_baseline_tag, monkeypatch):
    images_path = repo_with_baseline_tag.parent / "images" / "images-4.9.0.yaml"
    write(images_path,
          "# Baseline: podiumd 4.8.5. Re-verify before release.\n\n"
          "# ZAC — 5.0.1 -> 5.1.0\n"
          "- name: zac\n"
          "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
          '  version: "5.1.0"\n'
          '  digest: "sha256:aaaa"\n')
    set_argv_and_dir(cdb, monkeypatch, repo_with_baseline_tag, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "# ZAC — 5.0.2 -> 5.1.0" in text


# --- main() integration: reordering the table + Changes section ---

@pytest.fixture
def repo_with_out_of_order_doc(tmp_path):
    """Two components whose "Component versions" table row order and
    "## Changes" block order are both the OPPOSITE of values.yaml's own
    top-level key order (openzaak before openinwoner there, but the doc
    lists Open Inwoner first)."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"},
            {"name": "openinwoner", "version": "2.4.0", "repository": "@maykinmedia"},
        ],
    }, sort_keys=False))
    # sort_keys=False: values.yaml's own file order IS the ordering signal
    # this feature reads (values_key_order) -- yaml.safe_dump's default
    # alphabetical sort would silently reorder these two keys and defeat
    # the whole point of this fixture (openzaak deliberately BEFORE
    # openinwoner, opposite of the doc's row order below).
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "openzaak": {"image": {"tag": "1.27.4@sha256:aaaa"}},
        "openinwoner": {"image": {"tag": "2.4.2@sha256:bbbb"}},
    }, sort_keys=False))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.3)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| Open Inwoner | 2.4.2 | 2.4.0 | - |\n"
          "| Open Zaak | 1.27.4 | 1.14.2 | - |\n\n"
          "## Changes\n\n"
          "### Open Inwoner 2.4.2\n\n"
          "Inwoner details.\n\n"
          "### Open Zaak 1.27.4\n\n"
          "Zaak details.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed out-of-order doc", cwd=tmp_path)
    return doc_dir


def test_main_reorders_table_and_changes_to_match_values_yaml(cdb, repo_with_out_of_order_doc, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_out_of_order_doc, "4.8.3")
    cdb.main()

    upgrade = (repo_with_out_of_order_doc / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    lines = upgrade.splitlines()
    table_rows = [l for l in lines if l.startswith("| Open")]
    assert table_rows == ["| Open Zaak | 1.27.4 | 1.14.2 | - |", "| Open Inwoner | 2.4.2 | 2.4.0 | - |"]
    assert upgrade.index("### Open Zaak") < upgrade.index("### Open Inwoner")
    assert "Zaak details." in upgrade and "Inwoner details." in upgrade  # block content preserved

    out = capsys.readouterr().out
    assert "Reordering" in out
    assert "table row 'Open Zaak': position 2 -> 1" in out
    assert "changes block '### Open Zaak 1.27.4': position 2 -> 1" in out


def test_main_already_ordered_doc_reports_no_reordering(cdb, repo_with_out_of_order_doc, monkeypatch, capsys):
    doc = repo_with_out_of_order_doc / "4.8.3-to-4.9.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.3)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 | - |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 | - |\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_out_of_order_doc, "4.8.3")
    cdb.main()

    out = capsys.readouterr().out
    assert "Reordering" not in out
