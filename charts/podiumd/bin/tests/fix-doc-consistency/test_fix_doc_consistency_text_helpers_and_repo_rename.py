"""find_collisions, update_title_line, update_component_versions_heading,
remaining_mentions, collapse_multiple_blank_lines, ensure_blank_lines_around_headings,
main — pure logic plus a main() integration test against a real, hermetic temp git
repo (git mv shells out to git, so it needs a real working tree). The `repo` fixture
lives in conftest.py (shared with other test files in this directory)."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest


def write(path, text):
    path.write_text(text, encoding="utf-8")


# --- find_collisions ---


def test_find_collisions_detects_multiple_sources_for_same_suffix(cdb: ModuleType, tmp_path: Path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md"), ("4.8.3", tmp_path / "b.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    collisions = cdb.find_collisions(by_suffix)
    assert set(collisions.keys()) == {"upgrade"}


def test_find_collisions_empty_when_all_unique(cdb: ModuleType, tmp_path: Path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    assert cdb.find_collisions(by_suffix) == {}


# --- update_title_line ---


def test_update_title_line_replaces_arrow_form(cdb: ModuleType):
    text = "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\nbody\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert new_text.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"


def test_update_title_line_replaces_ascii_arrow(cdb: ModuleType):
    text = "# Upgrade guide: PodiumD 4.8.2 -> 4.9.0\nbody\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.3 -> 4.9.0" in new_text.splitlines()[0]


def test_update_title_line_only_touches_first_line(cdb: ModuleType):
    text = "# Title 4.8.2 → 4.9.0\nsome body mentioning 4.8.2 again\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.2 again" in new_text.splitlines()[1]  # body untouched


def test_update_title_line_no_match_returns_unchanged(cdb: ModuleType):
    text = "# Something else entirely\n"
    new_text, changed = cdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- update_component_versions_heading ---


def test_update_component_versions_heading_replaces_match(cdb: ModuleType):
    text = "## Component versions (4.9.0 vs 4.8.2)\n\nmore\n"
    new_text, changed = cdb.update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "## Component versions (4.9.0 vs 4.8.3)" in new_text


def test_update_component_versions_heading_no_match(cdb: ModuleType):
    text = "no such heading here\n"
    new_text, changed = cdb.update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- remaining_mentions ---


def test_remaining_mentions_finds_all_lines(cdb: ModuleType):
    text = "line one 4.8.2\nline two\nline three 4.8.2 again\n"
    assert cdb.remaining_mentions(text, "4.8.2") == [1, 3]


def test_remaining_mentions_empty_when_absent(cdb: ModuleType):
    assert cdb.remaining_mentions("nothing here\n", "4.8.2") == []


# --- collapse_multiple_blank_lines ---


def test_collapse_multiple_blank_lines_two_blanks_becomes_one(cdb: ModuleType):
    text = "line one\n\n\nline two\n"
    assert cdb.collapse_multiple_blank_lines(text) == "line one\n\nline two\n"


def test_collapse_multiple_blank_lines_many_blanks_becomes_one(cdb: ModuleType):
    text = "line one\n\n\n\n\n\nline two\n"
    assert cdb.collapse_multiple_blank_lines(text) == "line one\n\nline two\n"


def test_collapse_multiple_blank_lines_single_blank_untouched(cdb: ModuleType):
    text = "line one\n\nline two\n"
    assert cdb.collapse_multiple_blank_lines(text) == text


def test_collapse_multiple_blank_lines_no_blank_untouched(cdb: ModuleType):
    text = "line one\nline two\n"
    assert cdb.collapse_multiple_blank_lines(text) == text


def test_collapse_multiple_blank_lines_handles_multiple_separate_runs(cdb: ModuleType):
    text = "a\n\n\nb\n\n\n\nc\n"
    assert cdb.collapse_multiple_blank_lines(text) == "a\n\nb\n\nc\n"


def test_collapse_multiple_blank_lines_strips_single_trailing_blank_line_before_eof(cdb: ModuleType):
    """Regression test (real bug, real user session, confirmed against
    real pymarkdown): "content\n\n" — one syntactic blank line right
    before EOF, never 3+ consecutive newlines anywhere — still reports
    MD012 "Expected: 1, Actual: 2", since pymarkdown counts EOF itself
    as an implicit extra blank line. The mid-document collapse above
    never catches this (only 2 newlines, not 3+); a real upgrade.md kept
    reporting this exact violation across fix-doc-consistency runs that
    changed nothing else about the file."""
    text = "line one\n\n"
    assert cdb.collapse_multiple_blank_lines(text) == "line one\n"


def test_collapse_multiple_blank_lines_strips_many_trailing_blank_lines_before_eof(cdb: ModuleType):
    text = "line one\n\n\n\n"
    assert cdb.collapse_multiple_blank_lines(text) == "line one\n"


def test_collapse_multiple_blank_lines_single_trailing_newline_untouched(cdb: ModuleType):
    text = "line one\nline two\n"
    assert cdb.collapse_multiple_blank_lines(text) == text


# --- ensure_blank_lines_around_headings ---


def test_ensure_blank_lines_around_headings_adds_missing_blank_above(cdb: ModuleType):
    """Regression test (real bug, real doc): a "### ..." heading landing
    directly against non-blank content above it (real case: lib.
    component_docs.insert_changes_section relocating whatever block
    currently sorts last in a real upgrade.md, right after another
    block's own "- Image / digest: ..." line with nothing separating
    them) is exactly pymarkdown's MD022/MD032 — confirmed live against
    the real 4.9.0-to-4.9.1-upgrade.md, which had this precise shape."""
    text = "- Image / digest: see foo.\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert cdb.ensure_blank_lines_around_headings(text) == (
        "- Image / digest: see foo.\n\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    )


def test_ensure_blank_lines_around_headings_adds_missing_blank_below(cdb: ModuleType):
    text = "### curl 8.21.0 → 8.22.0\nSome prose.\n"
    assert cdb.ensure_blank_lines_around_headings(text) == "### curl 8.21.0 → 8.22.0\n\nSome prose.\n"


def test_ensure_blank_lines_around_headings_already_correct_untouched(cdb: ModuleType):
    text = "line one.\n\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert cdb.ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_never_adds_at_start_of_file(cdb: ModuleType):
    text = "### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert cdb.ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_never_adds_at_end_of_file(cdb: ModuleType):
    text = "Some prose.\n\n### curl 8.21.0 → 8.22.0\n"
    assert cdb.ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_ignores_hash_inside_fenced_code_block(cdb: ModuleType):
    """A "#" line inside a fenced ```...``` block (a shell/YAML comment in
    an example) is never a real heading and must never gain a blank
    line of its own."""
    text = "line one.\n```\n# not a heading\n```\nline two.\n"
    assert cdb.ensure_blank_lines_around_headings(text) == text


def test_ensure_blank_lines_around_headings_multiple_missing_in_one_doc(cdb: ModuleType):
    text = "line one.\n## Section A\nline two.\n## Section B\nline three.\n"
    assert cdb.ensure_blank_lines_around_headings(text) == (
        "line one.\n\n## Section A\n\nline two.\n\n## Section B\n\nline three.\n"
    )


def test_collapse_multiple_blank_lines_also_fixes_missing_blank_around_heading(cdb: ModuleType):
    """collapse_multiple_blank_lines itself (not just the standalone
    ensure_blank_lines_around_headings helper) must apply this fix too —
    every one of its own call sites in this script relies on it alone."""
    text = "- Image / digest: see foo.\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    assert cdb.collapse_multiple_blank_lines(text) == (
        "- Image / digest: see foo.\n\n### curl 8.21.0 → 8.22.0\n\nSome prose.\n"
    )


# --- main() integration, against a real temp git repo ---


def set_argv_and_dir(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch, doc_dir, new_baseline, target="4.9.0"):
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: new_baseline)
    monkeypatch.setattr(cdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdb, "IMAGES_DIR", doc_dir.parent / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", doc_dir.parents[1] / "Chart.yaml")
    monkeypatch.setattr(cdb, "VALUES_YAML", doc_dir.parents[1] / "values.yaml")
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
    """A values-deltas doc pointing at its sibling upgrade.md by the old
    baseline (e.g. a markdown link left over from the last rebase) must be
    rewritten too, not just flagged for manual review — this chart
    supports exactly one upgrade path per target, so every such reference
    always means the current baseline."""
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
    # nothing renamed, not even the non-conflicting values-deltas doc (all-or-nothing)
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8") == original
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").exists()


def test_main_creates_all_three_stubs_when_target_has_no_docs(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    set_argv_and_dir(cdb, monkeypatch, repo, "1.0.0", target="9.9.9")
    cdb.main()  # must not raise — creating stubs is success, not an error

    for suffix in cdb.STANDARD_SUFFIXES:
        stub = repo / f"1.0.0-to-9.9.9-{suffix}.md"
        assert stub.is_file()
        assert "1.0.0" in stub.read_text(encoding="utf-8")
        assert "9.9.9" in stub.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "created (was missing)" in out


def test_main_creates_only_the_missing_standard_doc(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    # repo fixture already has upgrade + values-deltas for 4.9.0 baseline 4.8.2;
    # gemeente-specific is missing for this target.
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
    """A doc already at the target baseline is otherwise a pure no-op
    (see test above) — except a stale sibling-doc reference left over
    from an earlier, incomplete rebase (the doc's OWN baseline already
    moved past it, but a link inside it didn't) must still be fixed, or
    nothing else in this script would ever touch that doc again."""
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
    """Regression test: a doc already at the target baseline whose
    sibling-doc reference is already correct (nothing stale to fix at
    all) must print "unchanged", not "fixed stale sibling doc
    reference(s)" — and must not rewrite the file. Before this fix,
    update_sibling_doc_refs reported "changed" whenever its own regex
    merely MATCHED a reference, even one already naming the current
    baseline, so this doc was falsely reported as "fixed" on every run
    with no actual file change (confirmed live: 4 real docs, real user
    session, no diff produced)."""
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
    """Regression test (real bug, real user session): a doc already at
    the target baseline, with no stale sibling reference to fix either,
    used to be treated as a pure no-op — "already baseline ... —
    unchanged" — even when it already had a double blank line (MD012).
    Since this is the ONLY write site that ever touches a doc like
    gemeente-specific.md at all (it never goes through upgrade.md/
    values-deltas.md's own separate content-fixing pass), that pre-
    existing violation could survive run after run with fix-doc-
    consistency reporting nothing wrong."""
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
    """Regression test (real bug, real doc): 4.9.1-to-4.9.2-upgrade.md's
    own "### eck-operator ..." block was inserted before insert_changes_
    section's own insertion-time fix existed, leaving "TODO" stranded
    beside it forever. This "already at baseline" no-rename path is the
    ONLY place a doc like this ever gets touched again — same reasoning
    as the sibling-reference/blank-line fixes right above."""
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
    """A "## Changes" section that STILL only has the bare TODO (no real
    "### ..." block yet) is the correct, expected state for a doc with
    nothing recorded yet — must never be touched, and must not appear in
    the "removed stale TODO placeholder" summary."""
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
    """Regression test (real bug, real doc): 4.9.1-to-4.9.2-values-
    deltas.md's own "## eck-operator ..." section was inserted before
    insert_values_delta_section's own insertion-time fix existed,
    leaving the stub TODO sentence stranded beside it forever."""
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
    """The writer (lib.component_docs.insert_changes_section/insert_
    values_delta_section), the retroactive fixer (this script), and the
    checker (lib.docs_consistency.check_docs_consistency) must all call
    the exact SAME function objects for "is a stub placeholder stranded
    alongside real content" -- not three independently hand-rolled
    copies of that same check."""
    import lib.component_docs.changes_section as changes_section
    import lib.component_docs.values_delta_sections as values_delta_sections
    import lib.docs_consistency as docs_consistency

    assert cdb.strip_stale_upgrade_placeholders is changes_section.strip_stale_upgrade_placeholders
    assert cdb.strip_stale_values_deltas_todo_stub is values_delta_sections.strip_stale_values_deltas_todo_stub
    assert docs_consistency.strip_stale_upgrade_placeholders is changes_section.strip_stale_upgrade_placeholders
    assert (
        docs_consistency.strip_stale_values_deltas_todo_stub
        is values_delta_sections.strip_stale_values_deltas_todo_stub
    )
    assert (
        docs_consistency.has_stale_gemeente_specific_placeholder
        is values_delta_sections.has_stale_gemeente_specific_placeholder
    )


def test_main_no_release_baseline_errors(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """No release-baseline.yaml upgrade_docs key to read (file or key
    missing) is an error — this script never takes the baseline as an
    argument, so there's nothing else to fall back to.
    read_upgrade_docs_baseline mocked directly (never CHART_YAML/DOC_DIR)
    so this can't accidentally read/touch the real chart's own
    release-baseline.yaml/docs if the mock were ever missed."""
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: None)
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero_without_touching_anything(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    """`--help` must print the module docstring and exit 0, leaving every
    doc untouched."""
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
    """This script never takes the baseline (or anything else) as an
    argument — any positional argument (other than -h/--help, its own
    earlier case) must be rejected with the usage docstring, not silently
    treated as a baseline the way it used to be."""
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
    """Anything release-baseline.yaml's own upgrade_docs key holds that
    isn't a bare MAJOR.MINOR.PATCH — a two-part version, a pre-release
    suffix, a "v" prefix, "latest", four parts, or empty — must be
    rejected up front with a clear error (see BASELINE_VERSION_RE), a
    defensive check against a hand-edited or corrupted file now that this
    can no longer come from a CLI argument."""
    before = sorted(p.name for p in repo.iterdir())
    set_argv_and_dir(cdb, monkeypatch, repo, bogus)
    with pytest.raises(SystemExit) as exc_info:
        cdb.main()
    assert exc_info.value.code == 1
    assert "not a valid MAJOR.MINOR.PATCH version" in capsys.readouterr().out
    assert sorted(p.name for p in repo.iterdir()) == before


def test_main_accepts_valid_semver_baseline(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch):
    assert cdb.BASELINE_VERSION_RE.match("4.8.2")
    assert cdb.BASELINE_VERSION_RE.match("10.20.300")
