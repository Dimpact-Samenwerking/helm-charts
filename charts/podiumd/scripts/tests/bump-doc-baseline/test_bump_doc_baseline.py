"""find_target_docs, find_collisions, update_title_line,
update_component_versions_heading, remaining_mentions, main — pure logic
plus a main() integration test against a real, hermetic temp git repo (git
mv shells out to git, so it needs a real working tree)."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


# --- find_target_docs ---

def test_find_target_docs_groups_by_suffix(bdb, tmp_path, monkeypatch):
    monkeypatch.setattr(bdb, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.2-to-4.9.0-upgrade.md", "x")
    write(tmp_path / "4.8.2-to-4.9.0-values-deltas.md", "x")
    write(tmp_path / "4.7.8-to-4.8.0-upgrade.md", "x")  # different target, ignored

    by_suffix = bdb.find_target_docs("4.9.0")
    assert set(by_suffix.keys()) == {"upgrade", "values-deltas"}
    assert by_suffix["upgrade"] == [("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md")]


def test_find_target_docs_empty_when_no_match(bdb, tmp_path, monkeypatch):
    monkeypatch.setattr(bdb, "DOC_DIR", tmp_path)
    write(tmp_path / "4.7.8-to-4.8.0-upgrade.md", "x")
    assert bdb.find_target_docs("4.9.0") == {}


# --- find_collisions ---

def test_find_collisions_detects_multiple_sources_for_same_suffix(bdb, tmp_path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md"), ("4.8.3", tmp_path / "b.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    collisions = bdb.find_collisions(by_suffix)
    assert set(collisions.keys()) == {"upgrade"}


def test_find_collisions_empty_when_all_unique(bdb, tmp_path):
    by_suffix = {
        "upgrade": [("4.8.2", tmp_path / "a.md")],
        "values-deltas": [("4.8.2", tmp_path / "c.md")],
    }
    assert bdb.find_collisions(by_suffix) == {}


# --- update_title_line ---

def test_update_title_line_replaces_arrow_form(bdb):
    text = "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\nbody\n"
    new_text, changed = bdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert new_text.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"


def test_update_title_line_replaces_ascii_arrow(bdb):
    text = "# Upgrade guide: PodiumD 4.8.2 -> 4.9.0\nbody\n"
    new_text, changed = bdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.3 -> 4.9.0" in new_text.splitlines()[0]


def test_update_title_line_only_touches_first_line(bdb):
    text = "# Title 4.8.2 → 4.9.0\nsome body mentioning 4.8.2 again\n"
    new_text, changed = bdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "4.8.2 again" in new_text.splitlines()[1]  # body untouched


def test_update_title_line_no_match_returns_unchanged(bdb):
    text = "# Something else entirely\n"
    new_text, changed = bdb.update_title_line(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- update_component_versions_heading ---

def test_update_component_versions_heading_replaces_match(bdb):
    text = "## Component versions (4.9.0 vs 4.8.2)\n\nmore\n"
    new_text, changed = bdb.update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is True
    assert "## Component versions (4.9.0 vs 4.8.3)" in new_text


def test_update_component_versions_heading_no_match(bdb):
    text = "no such heading here\n"
    new_text, changed = bdb.update_component_versions_heading(text, "4.8.2", "4.9.0", "4.8.3")
    assert changed is False
    assert new_text == text


# --- remaining_mentions ---

def test_remaining_mentions_finds_all_lines(bdb):
    text = "line one 4.8.2\nline two\nline three 4.8.2 again\n"
    assert bdb.remaining_mentions(text, "4.8.2") == [1, 3]


def test_remaining_mentions_empty_when_absent(bdb):
    assert bdb.remaining_mentions("nothing here\n", "4.8.2") == []


# --- main() integration, against a real temp git repo ---

@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    write(doc_dir / "4.8.2-to-4.9.0-upgrade.md",
          "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
          "This is the upgrade guide for environments already on **4.8.2**.\n\n"
          "## Component versions (4.9.0 vs 4.8.2)\n")
    write(doc_dir / "4.8.2-to-4.9.0-values-deltas.md",
          "# Values deltas — PodiumD 4.8.2 → 4.9.0\n\nNo changes.\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed docs", cwd=tmp_path)
    return doc_dir


def set_argv_and_dir(bdb, monkeypatch, doc_dir, new_baseline, target="4.9.0"):
    monkeypatch.setattr("sys.argv", ["bump-doc-baseline.py", new_baseline])
    monkeypatch.setattr(bdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(bdb, "current_chart_version", lambda: target)


def test_main_renames_and_updates_title_and_heading(bdb, repo, monkeypatch):
    set_argv_and_dir(bdb, monkeypatch, repo, "4.8.3")
    bdb.main()  # success path must not raise

    assert not (repo / "4.8.2-to-4.9.0-upgrade.md").exists()
    upgrade = (repo / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert upgrade.splitlines()[0] == "# Upgrade guide: PodiumD 4.8.3 → 4.9.0"
    assert "## Component versions (4.9.0 vs 4.8.3)" in upgrade
    assert "already on **4.8.2**" in upgrade  # free-form prose left for manual review

    deltas = (repo / "4.8.3-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.splitlines()[0] == "# Values deltas — PodiumD 4.8.3 → 4.9.0"


def test_main_is_tracked_by_git_after_rename(bdb, repo, monkeypatch):
    set_argv_and_dir(bdb, monkeypatch, repo, "4.8.3")
    bdb.main()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo.parents[1],
                             capture_output=True, text=True).stdout
    assert "R  " in status or "renamed" in status.lower() or "4.8.3-to-4.9.0-upgrade.md" in status


def test_main_refuses_on_collision(bdb, repo, monkeypatch):
    write(repo / "4.8.3-to-4.9.0-upgrade.md", "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n")
    original = (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    set_argv_and_dir(bdb, monkeypatch, repo, "4.8.3")

    with pytest.raises(SystemExit) as exc_info:
        bdb.main()
    assert exc_info.value.code == 1
    # nothing renamed, not even the non-conflicting values-deltas doc (all-or-nothing)
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").read_text(encoding="utf-8") == original
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").exists()


def test_main_creates_all_three_stubs_when_target_has_no_docs(bdb, repo, monkeypatch, capsys):
    set_argv_and_dir(bdb, monkeypatch, repo, "1.0.0", target="9.9.9")
    bdb.main()  # must not raise — creating stubs is success, not an error

    for suffix in bdb.STANDARD_SUFFIXES:
        stub = repo / f"1.0.0-to-9.9.9-{suffix}.md"
        assert stub.is_file()
        assert "1.0.0" in stub.read_text(encoding="utf-8")
        assert "9.9.9" in stub.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "created (was missing)" in out


def test_main_creates_only_the_missing_standard_doc(bdb, repo, monkeypatch):
    # repo fixture already has upgrade + values-deltas for 4.9.0 baseline 4.8.2;
    # gemeente-specific is missing for this target.
    set_argv_and_dir(bdb, monkeypatch, repo, "4.8.2")
    bdb.main()

    assert (repo / "4.8.2-to-4.9.0-gemeente-specific.md").is_file()
    # the pre-existing docs were left alone (already at baseline 4.8.2)
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").is_file()
    assert (repo / "4.8.2-to-4.9.0-values-deltas.md").is_file()


def test_main_already_at_new_baseline_is_a_noop(bdb, repo, monkeypatch, capsys):
    set_argv_and_dir(bdb, monkeypatch, repo, "4.8.2")
    bdb.main()
    assert (repo / "4.8.2-to-4.9.0-upgrade.md").exists()
    out = capsys.readouterr().out
    assert "already baseline 4.8.2 — unchanged" in out


def test_main_requires_exactly_one_argument(bdb, monkeypatch):
    monkeypatch.setattr("sys.argv", ["bump-doc-baseline.py"])
    with pytest.raises(SystemExit) as exc_info:
        bdb.main()
    assert exc_info.value.code == 1


# --- current_chart_version ---

def test_current_chart_version_reads_chart_yaml(bdb, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("version: 4.9.0\nname: podiumd\n", encoding="utf-8")
    monkeypatch.setattr(bdb, "CHART_YAML", chart_yaml)
    assert bdb.current_chart_version() == "4.9.0"
