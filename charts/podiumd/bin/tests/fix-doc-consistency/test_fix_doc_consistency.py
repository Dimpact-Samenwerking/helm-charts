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
    """Zero arguments is otherwise valid (falls back to release-baseline.
    yaml's upgrade_docs content) — only the combination of no argument AND
    no upgrade_docs baseline to fall back to is an error.
    read_upgrade_docs_baseline mocked directly (never CHART_YAML/DOC_DIR)
    so this can't accidentally read/touch the real chart's own
    release-baseline.yaml/docs if the mock were ever missed."""
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: None)
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
        text, None, target_deps, target_values, baseline_deps, baseline_values
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
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_unmatched_component_reported(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Totally Unknown Thing | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, [{"name": "zac", "version": "1.0.297"}], {}
    )
    assert changed == []
    assert unmatched == ["Totally Unknown Thing"]
    assert new_text == text


def test_fix_component_version_table_no_baseline_data_reported_unresolved(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, None, None
    )
    assert changed == []
    assert unresolved == ["ZAC (Zaakafhandelcomponent)"]
    assert new_text == text


def redis_sidecar_deps_and_values(target_chart="0.26.1", baseline_chart="0.25.0", target_tag="8.6.6"):
    target_deps = [{"name": "redis-operator", "version": target_chart}]
    baseline_deps = [{"name": "redis-operator", "version": baseline_chart}]
    target_values = {"redis-operator": {"redis-ha": {"image": {
        "repository": "quay.io/opstree/redis", "tag": f"{target_tag}@sha256:aaaa"}}}}
    baseline_values = {"redis-operator": {"redis-ha": {"image": {
        "repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}}}
    return target_deps, target_values, baseline_deps, baseline_values


def test_fix_component_version_table_leaves_a_correct_sidecar_row_untouched(cdb):
    """Regression test: a correctly-phrased canonical sidecar row (see
    lib.chart.canonical_sidecar_row_names) must never be "corrected"
    against its unrelated owning dependency's own chart/app version —
    match_dependency fuzzy-matches "redis-operator - redis" to the real
    "redis-operator" dependency on its leading word, which used to
    silently rewrite this row's Helm-chart cell from "-" to
    "0.25.0 → 0.26.1" (redis-operator's own chart bump, nothing to do
    with this sidecar row at all)."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_corrects_a_stale_sidecar_row_using_its_own_tag(cdb):
    """A sidecar row's App-version cell IS still corrected when stale —
    against its OWN resolved tag, never the owning dependency's. Its
    Helm-chart cell stays "-" regardless (never rewritten to the
    dependency's own chart version, the exact corruption this guards
    against)."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 9.9.9 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert len(changed) == 1
    assert "8.6.2 → 8.6.6" in new_text
    assert "9.9.9" not in new_text
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |" in new_text


def test_fix_component_version_table_unresolvable_canonical_row_reported_not_corrupted(cdb):
    """A row shaped like the canonical sidecar form but with no
    resolvable repository (e.g. "kiss - podiumd-adapter", commented out
    in real life) must be reported as unresolved — never fall through
    to match_dependency and get "corrected" against an unrelated real
    dependency's own actual version just because it shares a leading
    word."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - ghost | 0.6.6 → 0.6.7 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert unresolved == ["redis-operator - ghost"]
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


# --- main() integration: adding a missing "Component versions" row ---

@pytest.fixture
def repo_with_undocumented_component_bumps(tmp_path):
    """Three dependencies changed between the baseline tag and HEAD but
    none of them ever got a row in the upgrade doc's "Component
    versions" table at all — the real gap add_missing_component_rows
    exists to fill in. "openformulieren" and "keycloak-operator" both
    have a resolvable app image (the former via actual_app_version's
    default "<key>.image.tag" shape, the latter via its own registered
    lib.chart.COMPONENT_IMAGE_PATHS split-path entry); "redis-operator"
    is chart-only — no matching values.yaml image at all — the genuine
    case that forces a TODO-stub Changes section instead of full
    prose."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
            {"name": "openforms", "alias": "openformulieren", "version": "1.11.0", "repository": "@maykinmedia"},
            {"name": "keycloak-operator", "version": "1.12.1", "repository": "@adfinis"},
            {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
        "openformulieren": {"image": {"tag": "3.4.10@sha256:cccc"}},
        "keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.6.4", "sha": "eeee"}}}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
            {"name": "openforms", "alias": "openformulieren", "version": "1.12.0", "repository": "@maykinmedia"},
            {"name": "keycloak-operator", "version": "1.13.0", "repository": "@adfinis"},
            {"name": "redis-operator", "version": "0.27.0", "repository": "@opstree"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
        "openformulieren": {"image": {"tag": "3.5.6@sha256:dddd"}},
        "keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.7.3", "sha": "ffff"}}}},
    }))
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |\n\n"
          "## Changes\n\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump openformulieren + keycloak-operator + redis-operator, no doc rows added",
        cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_row_with_resolvable_app_version(cdb, repo_with_undocumented_component_bumps,
                                                             monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.11.0 → 1.12.0 | - |" in upgrade
    assert "### openformulieren 3.4.10 → 3.5.6 (chart 1.11.0 → 1.12.0)" in upgrade
    assert "TODO" not in upgrade.split("### openformulieren")[1].split("###")[0]
    out = capsys.readouterr().out
    assert "Adding missing component row(s)" in out
    assert "openformulieren" in out


def test_main_adds_missing_row_with_component_specific_image_path(
        cdb, repo_with_undocumented_component_bumps, monkeypatch, capsys):
    """keycloak-operator's real app version lives at its own registered
    lib.chart.COMPONENT_IMAGE_PATHS split-path — actual_app_version
    resolves it just like a plain "<key>.image.tag" component, so the
    new row gets a full app-version cell and Changes section, not a
    TODO stub."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| keycloak-operator | 26.6.4 → 26.7.3 | 1.12.1 → 1.13.0 | - |" in upgrade
    assert "### keycloak-operator 26.6.4 → 26.7.3 (chart 1.12.1 → 1.13.0)" in upgrade
    assert "TODO" not in upgrade.split("### keycloak-operator")[1].split("###")[0]
    out = capsys.readouterr().out
    assert "keycloak-operator" in out


def test_main_adds_missing_row_with_unresolvable_app_version_as_todo_stub(
        cdb, repo_with_undocumented_component_bumps, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator | - | 0.26.1 → 0.27.0 | - |" in upgrade
    assert "### redis-operator 0.26.1 → 0.27.0" in upgrade
    assert "TODO: describe this component's changes" in upgrade
    out = capsys.readouterr().out
    assert "redis-operator" in out


def test_main_leaves_existing_row_untouched_when_adding_missing_ones(
        cdb, repo_with_undocumented_component_bumps, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |" in upgrade


@pytest.fixture
def repo_with_undocumented_sidecar_bump(tmp_path):
    """redis-operator's own row already exists (unchanged, correct) —
    add_missing_component_rows has nothing to do at the top level. Its
    nested redis-ha sidecar image DID change vs baseline, but has no row
    of its own at all — the real gap add_missing_sidecar_rows exists to
    fill, mirroring the actual keycloak-operator/postgres case this
    feature was built for (a resolvable sidecar bumped alongside its
    already-documented parent, never given its own canonical row).
    "curl" lives under the shared "global.images" anchor — no owning
    Chart.yaml dependency at all — to exercise add_missing_sidecar_rows'
    OTHER shape (bare basename, no "<component> - " prefix) in the same
    fixture."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
            {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
        "redis-operator": {"redis-ha": {"image": {
            "repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}},
        "global": {"images": {"curlImage": {
            "repository": "curlimages/curl", "tag": "8.10.1@sha256:cccc"}}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
        "redis-operator": {"redis-ha": {"image": {
            "repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}},
        "global": {"images": {"curlImage": {
            "repository": "curlimages/curl", "tag": "8.11.0@sha256:dddd"}}},
    }))
    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |\n"
          "| redis-operator | - | 0.26.1 (unchanged) | n/a |\n\n"
          "## Changes\n\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump redis-ha's redis image + shared curl, no sidecar rows added", cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_sidecar_row_nested_under_a_dependency(
        cdb, repo_with_undocumented_sidecar_bump, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |" in upgrade
    assert "### redis-operator - redis 8.6.2 → 8.6.6" in upgrade
    assert "chart" not in upgrade.split("### redis-operator - redis")[1].split("###")[0].lower()
    out = capsys.readouterr().out
    assert "Adding missing sidecar/shared-image row(s)" in out
    assert "redis-operator - redis" in out


def test_main_adds_missing_sidecar_row_for_global_shared_image(
        cdb, repo_with_undocumented_sidecar_bump, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl | 8.10.1 → 8.11.0 | - | - |" in upgrade
    assert "### curl 8.10.1 → 8.11.0" in upgrade


def test_main_adds_missing_changes_section_for_an_existing_dependency_row(
        cdb, repo_with_undocumented_sidecar_bump, monkeypatch, capsys):
    """ZAC's own table row already existed (unchanged, correct) but had
    no "### ..." Changes section of its own at all — add_missing_
    changes_sections fills that in using the SAME make_changes_section
    template update-component-version/add_missing_component_rows
    themselves use, driven by the row's OWN cells (both unchanged here)
    rather than a fresh baseline lookup."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### ZAC (Zaakafhandelcomponent) 5.0.2 → 5.0.2 (chart 1.0.297, unchanged)" in upgrade
    out = capsys.readouterr().out
    assert "Adding missing '### ...' Changes section(s)" in out
    assert "ZAC (Zaakafhandelcomponent)" in out


def test_main_adds_todo_stub_section_when_row_has_no_app_version(
        cdb, repo_with_undocumented_sidecar_bump, monkeypatch):
    """redis-operator's own row app cell is "-" (nothing recorded there
    to build real prose from) — a short TODO-stub section is added
    instead of guessing, the same fallback add_missing_component_rows
    itself uses for the same reason."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### redis-operator 0.26.1\n" in upgrade
    assert "TODO: describe this component's changes" in upgrade


def test_main_updates_a_changes_heading_missing_its_app_version(cdb, tmp_path, monkeypatch):
    """Regression test: the real openbao case — a "### ..." heading
    written back when actual_app_version couldn't resolve anything yet
    (chart-only, add_missing_component_rows' own TODO-stub shape) is
    regenerated once that version DOES become resolvable (here: via the
    vendored-chart appVersion fallback for a component registered in
    COMPONENT_IMAGE_PATHS) — built from the row's own already-correct
    cells, same template add_missing_changes_sections itself uses. The
    old heading's own body text is discarded; there's no reliable way to
    tell which part of it was ever accurate."""
    import io
    import tarfile

    from lib.chart import COMPONENT_IMAGE_PATHS
    monkeypatch.setitem(COMPONENT_IMAGE_PATHS, "widget", ["image"])

    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [{"name": "widget", "version": "2.0.0", "repository": "@example"}],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "widget": {"image": {"repository": "example/widget", "tag": ""}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)

    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    with tarfile.open(charts_dir / "widget-2.0.0.tgz", "w:gz") as tar:
        chart_data = yaml.safe_dump({"apiVersion": "v2", "version": "2.0.0", "appVersion": "9.9.9"}).encode("utf-8")
        info = tarfile.TarInfo(name="widget/Chart.yaml")
        info.size = len(chart_data)
        tar.addfile(info, io.BytesIO(chart_data))

    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| widget | 9.9.9 (unchanged) | 2.0.0 (unchanged) | - |\n\n"
          "## Changes\n\n"
          "### widget 2.0.0\n\n"
          "TODO: describe this component's changes — its app version could not be resolved automatically.\n\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed doc with a stale chart-only heading", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### widget 9.9.9 → 9.9.9 (chart 2.0.0, unchanged)" in upgrade
    assert "TODO: describe this component's changes" not in upgrade
    assert "### widget 2.0.0\n" not in upgrade


def test_main_adds_sections_for_both_rows_named_by_a_two_component_heading(
        cdb, repo_with_undocumented_sidecar_bump, monkeypatch, capsys):
    """A "### ..." heading naming two components at once (real case:
    "### ECK Operator 3.4.0 -> 3.5.0 + ECK Stack (kiss-eck) 0.19.0 ->
    0.20.0") is assessed as a whole, never split — it credits NEITHER
    component's row (see find_changes_row_correspondence_gaps), so
    add_missing_changes_sections adds a proper section for EACH one from
    its own table row. The combined heading itself is left completely
    untouched — deciding what its shared prose was actually about, or
    how to rename/split it, needs a human, not a guess."""
    doc_dir = repo_with_undocumented_sidecar_bump
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    combined_heading = "### ZAC (Zaakafhandelcomponent) 5.0.2 (unchanged) + redis-operator 0.26.1 (unchanged)\n\n"
    doc.write_text(doc.read_text(encoding="utf-8").replace(
        "## Changes\n\n",
        "## Changes\n\n" + combined_heading + "Some shared prose that must not be touched.\n\n"
    ), encoding="utf-8")

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = doc.read_text(encoding="utf-8")
    assert combined_heading in upgrade
    assert "Some shared prose that must not be touched." in upgrade
    assert "### ZAC (Zaakafhandelcomponent) 5.0.2 → 5.0.2 (chart 1.0.297, unchanged)" in upgrade
    assert "### redis-operator 0.26.1\n" in upgrade
    out = capsys.readouterr().out
    assert "Adding missing '### ...' Changes section(s)" in out
    assert "ZAC (Zaakafhandelcomponent)" in out
    assert "redis-operator" in out


def test_main_adds_version_pin_bullet_for_a_version_paths_component(cdb, tmp_path, monkeypatch):
    """The section add_missing_changes_sections adds for a component
    registered in COMPONENT_VERSION_PATHS (e.g. eck-stack's bare
    "...version:" fields, the ECK operator's own CRD convention) must
    use a "Version pin" bullet, never the generic "Image tag pin
    `<key>.image.tag`" guess — that path doesn't even exist in
    values.yaml for a component shaped this way."""
    from lib.chart import COMPONENT_VERSION_PATHS
    monkeypatch.setitem(COMPONENT_VERSION_PATHS, "widget-b", ["version"])

    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "widget-a", "version": "1.0.0", "repository": "@example"},
            {"name": "widget-b", "version": "2.0.0", "repository": "@example"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "widget-a": {"image": {"tag": "1.1.0@sha256:aaaa"}},
        "widget-b": {"version": "2.1.0"},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({
        "widget-a": {"image": {"tag": "1.2.0@sha256:bbbb"}},
        "widget-b": {"version": "2.2.0"},
    }))
    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| widget-a | 1.1.0 → 1.2.0 | 1.0.0 (unchanged) | - |\n"
          "| widget-b | 2.1.0 → 2.2.0 | 2.0.0 (unchanged) | - |\n\n"
          "## Changes\n\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### widget-a 1.1.0 → 1.2.0 (chart 1.0.0, unchanged)" in upgrade
    assert "Image tag pin `widget-a.image.tag`" in upgrade
    assert "### widget-b 2.1.0 → 2.2.0 (chart 2.0.0, unchanged)" in upgrade
    assert "Version pin `widget-b.version`" in upgrade
    assert "Image tag pin `widget-b" not in upgrade


def test_main_does_not_duplicate_an_existing_sidecar_row(
        cdb, repo_with_undocumented_sidecar_bump, monkeypatch):
    doc_dir = repo_with_undocumented_sidecar_bump
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(
        "| redis-operator | - | 0.26.1 (unchanged) | n/a |\n",
        "| redis-operator | - | 0.26.1 (unchanged) | n/a |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | already documented by hand |\n"
    ), encoding="utf-8")

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = doc.read_text(encoding="utf-8")
    assert upgrade.count("| redis-operator - redis |") == 1
    assert "already documented by hand" in upgrade
    # The row already existed (hand-written), so add_missing_sidecar_rows
    # itself has nothing to add — but it still had no "### ..." section of
    # its own yet, which add_missing_changes_sections now fills in, using
    # the row's own hand-typed cells verbatim.
    assert "### redis-operator - redis 8.6.2 → 8.6.6" in upgrade


def test_main_leaves_unchanged_sidecar_with_no_row_alone(cdb, tmp_path, monkeypatch, capsys):
    """A sidecar whose tag never changed vs baseline must never get a
    row added just because it happens to have no row yet — only a real
    gap (tag actually changed) is worth documenting."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [{"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"}],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "redis-operator": {"redis-ha": {"image": {
            "repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(doc_dir / "4.8.5-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n\n"
          "## Changes\n\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "unrelated commit, redis-ha's own image untouched", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "redis-operator - redis" not in upgrade
    out = capsys.readouterr().out
    assert "Adding missing sidecar/shared-image row(s)" not in out


@pytest.fixture
def repo_with_short_alias_collision_risk(tmp_path):
    """Regression fixture: "mi" is a real Chart.yaml dependency alias
    short enough to be a literal mid-word substring of an unrelated
    EXISTING row's own Name — "ensurePodiumdAdminUser" contains "mi"
    (inside "ad-mi-n"). Before find_component_row's own word-boundary fix,
    add_missing_component_rows("mi") would silently overwrite that
    unrelated Python row's cells instead of inserting "mi"'s own new row."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "mi-data", "alias": "mi", "version": "1.0.0", "repository": "@dimpact"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({"mi": {"image": {"tag": "2.0.0@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({"mi": {"image": {"tag": "2.1.0@sha256:bbbb"}}}))
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| Python (ensurePodiumdAdminUser init image) | 3.14-slim (unchanged) | 1.0.0 (unchanged) | - |\n\n"
          "## Changes\n\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump mi, no doc row added", cwd=tmp_path)
    return doc_dir


def test_main_short_alias_does_not_corrupt_unrelated_row(cdb, repo_with_short_alias_collision_risk, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo_with_short_alias_collision_risk, "4.8.5")
    cdb.main()

    upgrade = (repo_with_short_alias_collision_risk / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert ("| Python (ensurePodiumdAdminUser init image) | 3.14-slim (unchanged) | 1.0.0 (unchanged) "
            "| - |") in upgrade
    assert "| mi | 2.0.0 → 2.1.0 | 1.0.0 (unchanged) | - |" in upgrade


# --- main() integration: values-deltas.md missing top-level component mention ---

@pytest.fixture
def repo_with_unmentioned_component_bump(tmp_path):
    """zaakbrug's own app image tag changed between the baseline tag and
    HEAD, but values-deltas.md never got a top-level "**zaakbrug**"
    bullet at all — a different gap than missing_key_change_lines (which
    is about NESTED schema keys under an already-mentioned component),
    the one add_missing_values_delta_bullets exists to fill in."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({"zaakbrug": {"image": {"tag": "1.26.14@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({"zaakbrug": {"image": {"tag": "1.26.15@sha256:bbbb"}}}))
    write(doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zaakbrug, no values-deltas mention", cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_values_delta_bullet(cdb, repo_with_unmentioned_component_bump, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_component_bump, "4.8.5")
    cdb.main()

    deltas = (repo_with_unmentioned_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8")
    assert "- **zaakbrug** app `1.26.14 → 1.26.15` (chart `2.3.28`, unchanged) — image tag only.\n" in deltas
    assert "No unrelated changes." in deltas  # existing content preserved
    out = capsys.readouterr().out
    assert "Adding missing component mention(s)" in out
    assert "zaakbrug" in out


def test_main_does_not_duplicate_already_mentioned_component_bullet(
        cdb, repo_with_unmentioned_component_bump, monkeypatch, capsys):
    doc = repo_with_unmentioned_component_bump / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "- **zaakbrug** app `1.26.14 → 1.26.15` (chart `2.3.28`, unchanged) — image tag only.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_component_bump, "4.8.5")
    cdb.main()

    deltas = (repo_with_unmentioned_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8")
    assert deltas.count("**zaakbrug**") == 1
    out = capsys.readouterr().out
    assert "Adding missing component mention(s)" not in out


def test_main_adds_todo_bullet_when_app_version_unresolvable(cdb, repo_with_undocumented_component_bumps,
                                                               monkeypatch):
    """redis-operator is chart-only — no matching values.yaml image at
    all — same fixture as the "Component versions" row tests, exercised
    here for the values-deltas bullet instead."""
    write(repo_with_undocumented_component_bumps / "4.8.3-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n")
    git("add", "-A", cwd=repo_with_undocumented_component_bumps)
    git("commit", "-q", "-m", "add values-deltas doc", cwd=repo_with_undocumented_component_bumps)
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8")
    assert "- **redis-operator** chart `0.26.1 → 0.27.0` — TODO: describe this component's changes" in deltas


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


def test_main_ignores_mention_inside_fenced_code_block_and_does_not_duplicate(
        cdb, repo_with_undocumented_schema_change, monkeypatch, capsys):
    """Regression: a fenced code block earlier in the doc (containing an
    unbalanced backtick, as real-world example snippets often do) used to
    desync backtick-span pairing for the REST of the document, making an
    already-mentioned key look unmentioned — main() would then re-add a
    duplicate mention right next to the real one instead of recognizing
    it (see lib.upgradedoc.strip_fenced_code_blocks)."""
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "```yaml\n"
        "some: `unbalanced backtick example\n"
        "```\n\n"
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
    assert cdb.resolve_entry_version({"name": "zac"}, paths) == "5.1.0"
    assert cdb.resolve_entry_version({"name": "zgw-office-addin-frontend"}, paths) == "v0.9.352"


def test_resolve_entry_version_none_when_unresolvable(cdb):
    assert cdb.resolve_entry_version({"name": "totally-unknown"}, {}) is None


def test_resolve_entry_version_uses_repo_map_for_strip_registry_names(cdb):
    """"infonl/zaakafhandelcomponent" doesn't fuzzy-word-match the "zac"
    values key at all — repo_map is what makes a current-convention
    manifest name resolve."""
    paths = {("zac",): "5.4.4@sha256:aaaa"}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    assert cdb.resolve_entry_version({"name": "infonl/zaakafhandelcomponent"}, paths) is None
    assert cdb.resolve_entry_version({"name": "infonl/zaakafhandelcomponent"}, paths, repo_map) == "5.4.4"


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


def test_fix_images_manifest_entries_resolves_strip_registry_name_via_repo_map(cdb):
    """"infonl/zaakafhandelcomponent" (the current strip-registry manifest
    naming convention) doesn't fuzzy-word-match the values.yaml key
    ("zac") at all — without repo_map this entry would be unresolved."""
    text = (
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image")}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, target_values, baseline_values, repo_map)
    assert unresolved == []
    assert changed == [("infonl/zaakafhandelcomponent", "5.0.2", "5.1.0")]
    assert "# ZAC — 5.0.2 -> 5.1.0" in new_text

    # without repo_map, the same entry is unresolved -- proves repo_map is
    # what makes the difference, not some other fixture quirk
    new_text2, changed2, unresolved2 = cdb.fix_images_manifest_entries(text, target_values, baseline_values)
    assert changed2 == []
    assert unresolved2 == ["infonl/zaakafhandelcomponent"]


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


# --- add_missing_images_manifest_entries ---

@pytest.fixture
def images_manifest_chart_dir(tmp_path):
    """A real Chart.yaml + values.yaml on disk (needed by
    lib.image_repository_check.find_images_without_repository, which
    reads them itself rather than taking already-loaded dicts) — zac's
    own "repository:" is set explicitly so its primary image resolves,
    matching lib.chart.paths_by_repository's own "no owning dependency
    needed for an own override" resolution."""
    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
    }))
    return tmp_path


def test_add_missing_images_manifest_entries_appends_new_entry(cdb, images_manifest_chart_dir):
    text = "# Baseline: podiumd 4.8.5.\n"
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent",
                                        "tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent",
                                          "tag": "5.0.2@sha256:bbbb"}}}

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values)

    assert skipped == []
    assert added == ["zac"]
    assert "# zac — 5.0.2 -> 5.1.0" in new_text
    assert "- name: infonl/zaakafhandelcomponent" in new_text
    assert "url: infonl/zaakafhandelcomponent" in new_text
    assert 'version: "5.1.0"' in new_text
    assert 'digest: "sha256:aaaa"' in new_text


def test_add_missing_images_manifest_entries_name_and_url_are_the_same_resolved_repository(
        cdb, images_manifest_chart_dir):
    """Both fields are set to the same repo_map key on purpose — the
    curated ACR mirror slug (docs/images/acr-mirror-naming.md) has no
    mechanical formula and stays a human's job to fix afterward."""
    text = ""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent",
                                        "tag": "5.1.0@sha256:aaaa"}}}

    _new_text, added, _skipped = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values={})
    assert added == ["zac"]


def test_add_missing_images_manifest_entries_noop_when_entry_already_covers_it(cdb, images_manifest_chart_dir):
    text = (
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent",
                                        "tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent",
                                          "tag": "5.0.2@sha256:bbbb"}}}

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values)
    assert added == []
    assert skipped == []
    assert new_text == text


def test_add_missing_images_manifest_entries_skips_when_no_digest_pinned(cdb, images_manifest_chart_dir):
    """A path whose current tag has no "@sha256:..." at all can't
    produce a valid entry (digest is a required field) — reported as
    skipped, not silently dropped or written incomplete."""
    write(images_manifest_chart_dir / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0"}},
    }))
    text = ""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    target_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0"}}}
    baseline_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent",
                                          "tag": "5.0.2@sha256:bbbb"}}}

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values)
    assert added == []
    assert skipped == ["zac"]
    assert new_text == text


def test_add_missing_images_manifest_entries_skips_image_with_no_resolvable_repository(
        cdb, images_manifest_chart_dir):
    """kiss.adapter.image's own real-world case: no own override AND no
    vendored subchart default — not a real, referenceable image, so
    never auto-added (matches lib.image_repository_check.
    find_images_without_repository's own definition of "unresolvable",
    reused via find_images_manifest_list_diff)."""
    write(images_manifest_chart_dir / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
            {"name": "kiss-chart", "alias": "kiss", "version": "3.0.0", "repository": "@kiss"},
        ],
    }))
    write(images_manifest_chart_dir / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.7@sha256:cccc"}}},
    }))
    text = ""
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"},
        {"name": "kiss-chart", "alias": "kiss", "version": "3.0.0"},
    ]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.7@sha256:cccc"}}},
    }
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
        "kiss": {"adapter": {"image": {"tag": "0.6.6@sha256:dddd"}}},
    }

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, images_manifest_chart_dir, deps, target_values, baseline_values)
    assert added == ["zac"]
    assert skipped == []  # kiss.adapter.image is excluded entirely, not reported as skipped either
    assert "kiss" not in new_text


@pytest.fixture
def ordered_images_manifest_chart_dir(tmp_path):
    """Three dependencies, values.yaml top-level order openzaak ->
    keycloak-operator -> zac — keycloak-operator's own postgres sidecar
    resolves via an own override, no vendored subchart tgz needed."""
    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
            {"name": "keycloak-operator", "version": "1.12.1", "repository": "@adfinis"},
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.29.3@sha256:aaaa"}},
        "keycloak-operator": {
            "job": {"postgres": {"image": {"repository": "postgres", "tag": "16.15@sha256:bbbb"}}}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:cccc"}},
    }))
    return tmp_path


def _ordered_deps():
    return [
        {"name": "openzaak", "version": "1.14.2"},
        {"name": "keycloak-operator", "version": "1.12.1"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"},
    ]


def _ordered_target_values():
    return {
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.29.3@sha256:aaaa"}},
        "keycloak-operator": {
            "job": {"postgres": {"image": {"repository": "postgres", "tag": "16.15@sha256:bbbb"}}}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:cccc"}},
    }


def _ordered_baseline_values():
    return {
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.27.4@sha256:aaaa"}},
        "keycloak-operator": {
            "job": {"postgres": {"image": {"repository": "postgres", "tag": "16.0@sha256:eeee"}}}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:cccc"}},
    }


def test_add_missing_images_manifest_entries_inserts_at_correct_body_and_header_position(
        cdb, ordered_images_manifest_chart_dir):
    """A missing entry for the MIDDLE component (values.yaml order
    openzaak -> keycloak-operator -> zac) is inserted between the
    existing openzaak and zac blocks — both in the body and in the "#
    Changes:" header's own numbered list — not appended after zac just
    because zac happened to be added to the file first."""
    text = (
        "# Two changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   2. zac 5.0.2 -> 5.1.0.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, ordered_images_manifest_chart_dir, _ordered_deps(), _ordered_target_values(),
        _ordered_baseline_values())

    assert skipped == []
    assert added == ["keycloak-operator - postgres"]

    lines = new_text.splitlines()
    openzaak_idx = next(i for i, line in enumerate(lines) if line.startswith("# openzaak"))
    kc_idx = next(i for i, line in enumerate(lines) if line.startswith("# keycloak-operator - postgres"))
    zac_idx = next(i for i, line in enumerate(lines) if line.startswith("# zac"))
    assert openzaak_idx < kc_idx < zac_idx

    assert "#   2. keycloak-operator - postgres 16.0 -> 16.15." in new_text
    assert "#   3. zac 5.0.2 -> 5.1.0." in new_text
    assert "# Three changes:" in new_text
    # Both existing entries' own content stays exactly as it was.
    assert "#   1. openzaak 1.27.4 -> 1.29.3." in new_text
    assert "- name: openzaak/open-zaak" in new_text
    assert "- name: infonl/zaakafhandelcomponent" in new_text


def test_add_missing_images_manifest_entries_valid_yaml_after_middle_insertion(
        cdb, ordered_images_manifest_chart_dir):
    """The inserted block is properly blank-line-separated from its
    neighbors on both sides — the result parses as a valid, 3-entry
    manifest, not malformed or merged-together YAML."""
    text = (
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, ordered_images_manifest_chart_dir, _ordered_deps(), _ordered_target_values(),
        _ordered_baseline_values())

    assert skipped == []
    assert added == ["keycloak-operator - postgres"]
    entries = yaml.safe_load(new_text)
    assert [e["name"] for e in entries] == ["openzaak/open-zaak", "postgres", "infonl/zaakafhandelcomponent"]


def test_add_missing_images_manifest_entries_no_header_still_orders_body(
        cdb, ordered_images_manifest_chart_dir):
    """No "# Changes:" header at all in this file — the body still gets
    ordered correctly; nothing about header-handling is required for
    body ordering to work."""
    text = (
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped = cdb.add_missing_images_manifest_entries(
        text, ordered_images_manifest_chart_dir, _ordered_deps(), _ordered_target_values(),
        _ordered_baseline_values())

    assert skipped == []
    assert added == ["keycloak-operator - postgres"]
    lines = new_text.splitlines()
    openzaak_idx = next(i for i, line in enumerate(lines) if line.startswith("# openzaak"))
    kc_idx = next(i for i, line in enumerate(lines) if line.startswith("# keycloak-operator - postgres"))
    zac_idx = next(i for i, line in enumerate(lines) if line.startswith("# zac"))
    assert openzaak_idx < kc_idx < zac_idx


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


def test_main_corrects_strip_registry_named_entry_via_repo_map(cdb, tmp_path, monkeypatch):
    """Same as test_main_corrects_stale_images_manifest_entry_comment, but
    with the images-manifest entry under the CURRENT strip-registry name
    ("infonl/zaakafhandelcomponent") instead of the old short slug
    ("zac") — main() must build repo_map from the real Chart.yaml/
    values.yaml and pass it through for this to resolve at all."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
    }))
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | ACR mirror only |\n")
    images_path = images_dir / "images-4.9.0.yaml"
    write(images_path,
          "# Baseline: podiumd 4.8.5. Re-verify before release.\n\n"
          "# ZAC — 5.0.1 -> 5.1.0\n"
          "- name: infonl/zaakafhandelcomponent\n"
          "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
          '  version: "5.1.0"\n'
          '  digest: "sha256:aaaa"\n')
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, stale images-manifest comment", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "# ZAC — 5.0.2 -> 5.1.0" in text


def test_main_adds_missing_images_manifest_entry(cdb, tmp_path, monkeypatch):
    """A component that changed vs baseline but has NO images-manifest
    entry at all yet (the "changed vs ... but has no entry" gap verify-
    podiumd's own doc-consistency check reports) gets a new entry
    appended by main() — not just reported for manual review."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
    }))
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.5)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | ACR mirror only |\n")
    images_path = images_dir / "images-4.9.0.yaml"
    write(images_path, "# Baseline: podiumd 4.8.5. Re-verify before release.\n\n[]\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, no images-manifest entry yet", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "# zac — 5.0.2 -> 5.1.0" in text
    assert "- name: infonl/zaakafhandelcomponent" in text
    assert "url: infonl/zaakafhandelcomponent" in text
    assert 'version: "5.1.0"' in text
    assert 'digest: "sha256:aaaa"' in text


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
          "### Open Inwoner 2.4.2 → 2.4.2\n\n"
          "Inwoner details.\n\n"
          "### Open Zaak 1.27.4 → 1.27.4\n\n"
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
    assert "changes block '### Open Zaak 1.27.4 → 1.27.4': position 2 -> 1" in out


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


def test_main_reorders_a_sidecar_row_to_come_after_its_own_parent_row(cdb, tmp_path, monkeypatch, capsys):
    """A canonical sidecar row ("redis-operator - redis") resolves to the
    SAME values_key_index as its owning dependency's own row ("redis-
    operator") via match_dependency's fuzzy word-containment — before the
    " - " secondary tie-break, two same-key items just kept whatever
    relative order they already had (Python's sort is stable), silently
    tolerating a sidecar appearing BEFORE its own parent. Here the doc
    starts with the sidecar row first; it must end up after."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(tmp_path / "Chart.yaml", yaml.safe_dump({
        "dependencies": [{"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"}],
    }))
    write(tmp_path / "values.yaml", yaml.safe_dump({
        "redis-operator": {"redis-ha": {"image": {
            "repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}},
    }))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(doc_dir / "4.8.3-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.3)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |\n"
          "| redis-operator | 0.26.1 (unchanged) | 0.26.1 (unchanged) | - |\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed sidecar-before-parent doc", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.3")
    cdb.main()

    upgrade = (doc_dir / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    lines = upgrade.splitlines()
    table_rows = [l for l in lines if l.startswith("| redis-operator")]
    assert table_rows == [
        "| redis-operator | 0.26.1 (unchanged) | 0.26.1 (unchanged) | - |",
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |",
    ]
    out = capsys.readouterr().out
    assert "Reordering" in out


# --- main() print formatting: multi-item lists split one per line, not comma-joined ---

def test_main_reports_unmatched_components_one_per_line(cdb, repo, monkeypatch, capsys):
    write(repo / "4.8.2-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.2)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| Totally Unknown Thing A | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n"
          "| Totally Unknown Thing B | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    out = capsys.readouterr().out
    assert "Could not match 2 component(s) to a Chart.yaml dependency, left as-is:" in out
    assert "  Totally Unknown Thing A" in out
    assert "  Totally Unknown Thing B" in out
    assert "Totally Unknown Thing A, Totally Unknown Thing B" not in out


def test_main_reports_unresolved_source_versions_one_per_line(cdb, repo, monkeypatch, capsys):
    """Multiple components whose source (baseline) version can't be
    verified must each get their own line, not be crammed onto one
    comma-joined line — the header states the count, one name per line
    follows."""
    write(repo.parents[1] / "Chart.yaml", yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
            {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
        ],
    }))
    write(repo.parents[1] / "values.yaml", yaml.safe_dump({
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
        "openzaak": {"image": {"tag": "1.29.3@sha256:bbbb"}},
    }))
    write(repo / "4.8.2-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
          "## Component versions (4.9.0 vs 4.8.2)\n\n"
          "| Component | App version | Helm chart | Notes |\n"
          "| --- | --- | --- | --- |\n"
          "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | - |\n"
          "| Open Zaak | 1.27.4 → 1.29.3 | 1.14.2 (unchanged) | - |\n")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    out = capsys.readouterr().out
    assert "Could not verify source version for 2 component(s)" in out
    assert "  ZAC (Zaakafhandelcomponent)" in out
    assert "  Open Zaak" in out
    assert "ZAC (Zaakafhandelcomponent), Open Zaak" not in out


def test_main_reports_unresolved_image_entries_one_per_line(cdb, repo, monkeypatch, capsys):
    images_dir = repo.parent / "images"
    write(images_dir / "images-4.9.0.yaml",
          '- name: totally-unknown-a\n  version: "1.0.0"\n'
          '- name: totally-unknown-b\n  version: "1.0.0"\n')
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    out = capsys.readouterr().out
    assert "Could not verify source/target version for 2 entry(s) in images-4.9.0.yaml" in out
    assert "  totally-unknown-a" in out
    assert "  totally-unknown-b" in out
    assert "totally-unknown-a, totally-unknown-b" not in out
