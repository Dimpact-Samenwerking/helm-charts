"""Text helpers plus main() integration against a real temp git repo (git mv
needs a working tree)."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest

from lib.fix_doc_consistency.text_helpers_and_repo_rename import collapse_multiple_blank_lines
from lib.fix_doc_consistency.text_helpers_and_repo_rename import ensure_blank_lines_around_headings
from lib.fix_doc_consistency.text_helpers_and_repo_rename import find_collisions
from lib.fix_doc_consistency.text_helpers_and_repo_rename import remaining_mentions
from lib.fix_doc_consistency.text_helpers_and_repo_rename import update_component_versions_heading
from lib.fix_doc_consistency.text_helpers_and_repo_rename import update_title_line
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES


def write(path, text):
    path.write_text(text, encoding="utf-8")


# --- find_collisions ---


def test_find_collisions_detects_multiple_sources_for_same_suffix(cdb: ModuleType, tmp_path: Path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md"), ("4.8.3", tmp_path / "b.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    collisions = find_collisions(by_suffix)
    assert set(collisions.keys()) == {"upgrade"}


def test_find_collisions_empty_when_all_unique(cdb: ModuleType, tmp_path: Path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    assert find_collisions(by_suffix) == {}


# --- update_title_line ---


def test_update_title_line_replaces_arrow_form(cdb: ModuleType):
    text = "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\nbody\n"
    new_text, changed = update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert new_text.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"


def test_update_title_line_replaces_ascii_arrow(cdb: ModuleType):
    text = "# Upgrade guide: PodiumD 4.8.2 -> 4.9.0\nbody\n"
    new_text, changed = update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.3 -> 4.9.0" in new_text.splitlines()[0]


def test_update_title_line_only_touches_first_line(cdb: ModuleType):
    text = "# Title 4.8.2 → 4.9.0\nsome body mentioning 4.8.2 again\n"
    new_text, changed = update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.2 again" in new_text.splitlines()[1]  # body untouched


def test_update_title_line_no_match_returns_unchanged(cdb: ModuleType):
    text = "# Something else entirely\n"
    new_text, changed = update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- update_component_versions_heading ---


def test_update_component_versions_heading_replaces_match(cdb: ModuleType):
    text = "## Component versions (4.9.0 vs 4.8.2)\n\nmore\n"
    new_text, changed = update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "## Component versions (4.9.0 vs 4.8.3)" in new_text


def test_update_component_versions_heading_no_match(cdb: ModuleType):
    text = "no such heading here\n"
    new_text, changed = update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- remaining_mentions ---


def test_remaining_mentions_finds_all_lines(cdb: ModuleType):
    text = "line one 4.8.2\nline two\nline three 4.8.2 again\n"
    assert remaining_mentions(text, "4.8.2") == [1, 3]


def test_remaining_mentions_empty_when_absent(cdb: ModuleType):
    assert remaining_mentions("nothing here\n", "4.8.2") == []


# --- collapse_multiple_blank_lines ---


def test_collapse_multiple_blank_lines_two_blanks_becomes_one(cdb: ModuleType):
    text = "line one\n\n\nline two\n"
    assert collapse_multiple_blank_lines(text) == "line one\n\nline two\n"


def test_collapse_multiple_blank_lines_many_blanks_becomes_one(cdb: ModuleType):
    text = "line one\n\n\n\n\n\nline two\n"
    assert collapse_multiple_blank_lines(text) == "line one\n\nline two\n"


def test_collapse_multiple_blank_lines_single_blank_untouched(cdb: ModuleType):
    text = "line one\n\nline two\n"
    assert collapse_multiple_blank_lines(text) == text


def test_collapse_multiple_blank_lines_no_blank_untouched(cdb: ModuleType):
    text = "line one\nline two\n"
    assert collapse_multiple_blank_lines(text) == text


def test_collapse_multiple_blank_lines_handles_multiple_separate_runs(cdb: ModuleType):
    text = "a\n\n\nb\n\n\n\nc\n"
    assert collapse_multiple_blank_lines(text) == "a\n\nb\n\nc\n"


def test_collapse_multiple_blank_lines_strips_single_trailing_blank_line_before_eof(cdb: ModuleType):
    """Regression: pymarkdown counts EOF as an implicit blank line, so a
    single trailing blank line ("content\n\n") is MD012 too, which the
    3+-newline collapse doesn't catch."""
    text = "line one\n\n"
    assert collapse_multiple_blank_lines(text) == "line one\n"


def test_collapse_multiple_blank_lines_strips_many_trailing_blank_lines_before_eof(cdb: ModuleType):
    text = "line one\n\n\n\n"
    assert collapse_multiple_blank_lines(text) == "line one\n"


def test_collapse_multiple_blank_lines_single_trailing_newline_untouched(cdb: ModuleType):
    text = "line one\nline two\n"
    assert collapse_multiple_blank_lines(text) == text


# --- ensure_blank_lines_around_headings ---


def test_ensure_blank_lines_around_headings_adds_missing_blank_above(cdb: ModuleType):
    """Regression: a "### ..." heading directly after content (as
    insert_changes_section can produce) violates MD022/MD032."""
    text = "- Image / digest: see foo.\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert ensure_blank_lines_around_headings(text) == (
        "- Image / digest: see foo.\n\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    )


def test_ensure_blank_lines_around_headings_adds_missing_blank_below(cdb: ModuleType):
    text = "### curl 8.21.0 → 8.22.0\nSome prose.\n"
    assert ensure_blank_lines_around_headings(text) == "### curl 8.21.0 → 8.22.0\n\nSome prose.\n"


def test_ensure_blank_lines_around_headings_already_correct_untouched(cdb: ModuleType):
    text = "line one.\n\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_never_adds_at_start_of_file(cdb: ModuleType):
    text = "### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_never_adds_at_end_of_file(cdb: ModuleType):
    text = "Some prose.\n\n### curl 8.21.0 → 8.22.0\n"
    assert ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_ignores_hash_inside_fenced_code_block(cdb: ModuleType):
    """A "#" line inside a fenced block is not a heading."""
    text = "line one.\n```\n# not a heading\n```\nline two.\n"
    assert ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_multiple_missing_in_one_doc(cdb: ModuleType):
    text = "line one.\n## Section A\nline two.\n## Section B\nline three.\n"
    assert ensure_blank_lines_around_headings(text) == (
        "line one.\n\n## Section A\n\nline two.\n\n## Section B\n\nline three.\n"
    )


def test_collapse_multiple_blank_lines_also_fixes_missing_blank_around_heading(cdb: ModuleType):
    """collapse_multiple_blank_lines applies this too; its call sites rely on it alone."""
    text = "- Image / digest: see foo.\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert collapse_multiple_blank_lines(text) == (
        "- Image / digest: see foo.\n\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    )


# --- main() integration, against a real temp git repo ---


def set_argv_and_dir(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch, doc_dir, new_baseline, target="4.9.0"):
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: new_baseline)
    monkeypatch.setattr(cdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdb, "IMAGES_DIR", doc_dir.parent / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", doc_dir.parents[1] / "Chart.yaml")
    monkeypatch.setattr(cdb, "current_chart_version", lambda: target)


def test_main_renames_and_updates_title_and_heading(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")
    cdb.main()  # success path must not raise

    assert not (repo / "4.8.2-to-4.9.0-upgrade.md").exists()
    upgrade = (repo / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"
    assert "## Component versions (4.9.0 vs 4.8.3)" in upgrade
    assert "already on **4.8.2**" in upgrade  # free-form prose left for manual review

    deltas = (repo / "4.8.3-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.splitlines()[0] == "# Values deltas — PodiumD 4.8.3 → 4.9.0"


def test_main_rewrites_sibling_doc_references_within_the_docs_themselves(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch
):
    """A sibling reference by the old baseline is rewritten, not just flagged:
    there is exactly one upgrade path per target."""
    write(
        repo / "4.8.2-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\n"
        "Background and failure modes in "
        "[`4.8.2-to-4.9.0-upgrade.md`](4.8.2-to-4.9.0-upgrade.md).\n",
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")

    cdb.main()

    deltas = (repo / "4.8.3-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "[`4.8.3-to-4.9.0-upgrade.md`](4.8.3-to-4.9.0-upgrade.md)" in deltas
    assert "4.8.2" not in deltas


def test_main_is_tracked_by_git_after_rename(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")
    cdb.main()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo.parents[1], capture_output=True, text=True
    ).stdout
    assert "R  " in status or "renamed" in status.lower() or "4.8.3-to-4.9.0-upgrade.md" in status


def test_main_refuses_on_collision(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    write(repo / "4.8.3-to-4.9.0-upgrade.md", "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n")
    original = (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")

    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1
    # all-or-nothing: not even the non-conflicting doc is renamed
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8") == original
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").exists()


def test_main_creates_all_three_stubs_when_target_has_no_docs(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    set_argv_and_dir(cdb, monkeypatch, repo, "1.0.0", target="9.9.9")
    cdb.main()  # must not raise — creating stubs is success, not an error

    for suffix in STANDARD_SUFFIXES:
        stub = repo / f"1.0.0-to-9.9.9-{suffix}.md"
        assert stub.is_file()
        assert "1.0.0" in stub.read_text(encoding="utf-8")
        assert "9.9.9" in stub.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "created (was missing)" in out


def test_main_creates_only_the_missing_standard_doc(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    # The fixture lacks only gemeente-specific for this target.
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()

    assert (repo / "4.8.2-to-4.9.0-gemeente-specific.md").is_file()
    # the pre-existing docs were left alone (already at baseline 4.8.2)
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").is_file()
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").is_file()


def test_main_already_at_new_baseline_is_a_noop(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").exists()
    out = capsys.readouterr().out
    assert "already baseline 4.8.2 — unchanged" in out


def test_main_already_at_new_baseline_still_fixes_a_stale_sibling_reference(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A doc already at the target baseline still gets stale sibling
    references fixed; nothing else would ever touch it again."""
    write(
        repo / "4.8.2-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\n"
        "Background and failure modes in "
        "[`4.8.1-to-4.9.0-upgrade.md`](4.8.1-to-4.9.0-upgrade.md).\n",
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    deltas = (repo / "4.8.2-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "[`4.8.2-to-4.9.0-upgrade.md`](4.8.2-to-4.9.0-upgrade.md)" in deltas
    assert "4.8.1" not in deltas
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-values-deltas.md: already baseline 4.8.2 — fixed stale sibling doc reference(s)" in out


def test_main_already_at_new_baseline_with_correct_sibling_ref_is_a_noop(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression: an already-correct sibling reference prints "unchanged"
    and doesn't rewrite the file (a regex match used to count as a change)."""
    write(
        repo / "4.8.2-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\n"
        "Background and failure modes in "
        "[`4.8.2-to-4.9.0-upgrade.md`](4.8.2-to-4.9.0-upgrade.md).\n",
    )
    original = (repo / "4.8.2-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-values-deltas.md: already baseline 4.8.2 — unchanged" in out
    assert "fixed stale sibling doc reference(s)" not in out


def test_main_already_at_new_baseline_collapses_pre_existing_double_blank_line(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression: a doc already at baseline still gets MD012 double blank
    lines fixed; this is the only write site for docs like
    gemeente-specific.md."""
    write(
        repo / "4.8.2-to-4.9.0-gemeente-specific.md", "# Gemeente-specific notes — PodiumD 4.8.2 → 4.9.0\n\n\nNone.\n"
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    text = (repo / "4.8.2-to-4.9.0-gemeente-specific.md").read_text(encoding="utf-8")
    assert "\n\n\n" not in text
    assert text == "# Gemeente-specific notes — PodiumD 4.8.2 → 4.9.0\n\nNone.\n"
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-gemeente-specific.md: already baseline 4.8.2 — collapsed multiple blank line(s)" in out


def test_main_already_at_new_baseline_strips_stale_changes_todo_stub(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression: a stranded "TODO" beside a real "### ..." block is removed
    on the already-at-baseline path, the only place such a doc is revisited."""
    write(
        repo / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.2)\n\n"
        "## Changes\n\n"
        "TODO\n\n"
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.0 introduces **eck-operator** at app version 3.5.0.\n",
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    text = (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "TODO" not in text
    assert "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)" in text
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-upgrade.md: already baseline 4.8.2 — removed stale TODO placeholder" in out
    assert "removed stale TODO placeholder from 1 doc(s): 4.8.2-to-4.9.0-upgrade.md" in out


def test_main_already_at_new_baseline_leaves_a_still_empty_changes_section_untouched(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A Changes section with only the bare TODO is the expected empty state:
    left alone and not reported."""
    write(
        repo / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n## Component versions (4.9.0 vs 4.8.2)\n\n## Changes\n\nTODO\n",
    )
    original = (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    assert (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-upgrade.md: already baseline 4.8.2 — unchanged" in out
    assert "removed stale TODO placeholder" not in out


def test_main_already_at_new_baseline_strips_stale_values_deltas_todo_stub(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression: a stub TODO stranded beside a real values-deltas section
    is removed."""
    write(
        repo / "4.8.2-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n\n"
        "## eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "- Key `eck-operator.image` was added.\n",
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    text = (repo / "4.8.2-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "TODO" not in text
    assert "## eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)" in text
    out = capsys.readouterr().out
    assert "4.8.2-to-4.9.0-values-deltas.md: already baseline 4.8.2 — removed stale TODO placeholder" in out
    assert "removed stale TODO placeholder from 1 doc(s): 4.8.2-to-4.9.0-values-deltas.md" in out


def test_stale_placeholder_functions_are_reused_not_reimplemented(cdb: ModuleType):
    """The writers and the checker share the same stranded-stub-placeholder function objects.

    fix-doc-consistency clears the TODO stubs (verify-podiumd reports that through its
    dry-run); only the gemeente-specific placeholder, which nothing clears, is checked."""
    import lib.component_docs.changes_section as changes_section
    import lib.component_docs.values_delta_sections as values_delta_sections
    import lib.docs_consistency as docs_consistency
    import lib.fix_doc_consistency.run as run

    assert run.strip_stale_upgrade_placeholders is changes_section.strip_stale_upgrade_placeholders
    assert run.strip_stale_values_deltas_todo_stub is values_delta_sections.strip_stale_values_deltas_todo_stub
    assert (
        docs_consistency.has_stale_gemeente_specific_placeholder
        is values_delta_sections.has_stale_gemeente_specific_placeholder
    )


def test_main_no_release_baseline_errors(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """A missing upgrade_docs key is an error: there is no CLI fallback.
    read_upgrade_docs_baseline is mocked so the real chart is never read."""
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: None)
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero_without_touching_anything(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    """`--help` prints the module docstring, exits 0 and touches no doc."""
    before = sorted(p.name for p in repo.iterdir())
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency", flag])
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{cdb.__doc__}\n"
    assert sorted(p.name for p in repo.iterdir()) == before


def test_main_rejects_any_argument(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Any positional argument other than -h/--help is rejected with usage."""
    before = sorted(p.name for p in repo.iterdir())
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency", "4.8.3"])
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == f"{cdb.__doc__}\n"
    assert sorted(p.name for p in repo.iterdir()) == before


@pytest.mark.parametrize("bogus", ["4.8", "4.8.2-rc1", "v4.8.2", "latest", "4.8.2.1", ""])
def test_main_rejects_non_semver_baseline_from_release_baseline_yaml(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bogus
):
    """A non-MAJOR.MINOR.PATCH upgrade_docs value is rejected up front,
    guarding against a hand-edited or corrupted file."""
    before = sorted(p.name for p in repo.iterdir())
    set_argv_and_dir(cdb, monkeypatch, repo, bogus)
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1
    assert "not a valid MAJOR.MINOR.PATCH version" in capsys.readouterr().out
    assert sorted(p.name for p in repo.iterdir()) == before
