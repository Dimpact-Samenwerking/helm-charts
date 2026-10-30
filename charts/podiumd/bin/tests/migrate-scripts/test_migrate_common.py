"""charts/podiumd/scripts/migrate_common.py: error text, per-file statuses and the shared command line."""

import argparse

from pathlib import Path
from types import ModuleType

import pytest


def rename_old(text: str, _args: argparse.Namespace) -> tuple[str, list[str]]:
    """A migration that renames key `old` to `new`."""
    if "old:" not in text:
        return text, []
    return text.replace("old:", "new:"), ["old renamed", "detail"]


def mode(*, dry_run: bool = False, check: bool = False) -> argparse.Namespace:
    return argparse.Namespace(dry_run=dry_run, check=check)


def write_env(root: Path, gemeente: str, env: str, text: str, file_name: str = "podiumd.yml") -> Path:
    """root/<gemeente>/<env>/<file_name> with `text`."""
    path = root / gemeente / env / file_name
    path.parent.mkdir(parents=True)
    # newline="": on Windows write_text would turn "\r\n" into "\r\r\n".
    path.write_text(text, encoding="utf-8", newline="")
    return path


def test_error_note_of_a_migration_error_is_its_text(common: ModuleType):
    assert common.error_note(common.MigrationError("fix it by hand")) == "fix it by hand"


def test_error_note_survives_an_empty_message(common: ModuleType):
    assert common.error_note(ValueError()) == "unexpected ValueError: "


def test_error_note_names_the_line_of_a_yaml_error(common: ModuleType):
    with pytest.raises(Exception) as caught:  # noqa: PT011 -- whichever ruamel error the parser raises
        common.load_safe("a: 1\nb: [\n")
    assert " at line " in common.error_note(caught.value)


def test_migrate_file_leaves_a_file_without_changes(common: ModuleType, tmp_path: Path):
    path = write_env(tmp_path, "g", "test", "keep: 1\n")
    assert common.migrate_file(str(path), rename_old, mode()) == ("unchanged", [])


def test_migrate_file_writes_the_migrated_file_with_lf(common: ModuleType, tmp_path: Path):
    path = write_env(tmp_path, "g", "test", "old: 1\r\nkeep: 2\r\n")
    assert common.migrate_file(str(path), rename_old, mode()) == ("migrated", ["old renamed", "detail"])
    assert path.read_bytes() == b"new: 1\nkeep: 2\n"


def test_migrate_file_dry_run_prints_a_diff_and_writes_nothing(
    common: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    path = write_env(tmp_path, "g", "test", "old: 1\n")
    assert common.migrate_file(str(path), rename_old, mode(dry_run=True))[0] == "migrated"
    assert path.read_text(encoding="utf-8") == "old: 1\n"
    assert f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old: 1\n+new: 1\n" in capsys.readouterr().out


def test_migrate_file_check_reports_the_chosen_notes_and_writes_nothing(common: ModuleType, tmp_path: Path):
    def first_note(notes: list[str]) -> list[str]:
        return notes[:1]

    path = write_env(tmp_path, "g", "test", "old: 1\n")
    assert common.migrate_file(str(path), rename_old, mode(check=True), first_note) == (
        "needs migration",
        ["old renamed"],
    )
    assert path.read_text(encoding="utf-8") == "old: 1\n"


def test_migrate_file_reports_an_error_and_writes_nothing(common: ModuleType, tmp_path: Path):
    message = "not a YAML mapping"

    def refuse(_text: str, _args: argparse.Namespace) -> tuple[str, list[str]]:
        raise common.MigrationError(message)

    path = write_env(tmp_path, "g", "test", "old: 1\n")
    assert common.migrate_file(str(path), refuse, mode()) == ("error", ["not a YAML mapping"])
    assert path.read_text(encoding="utf-8") == "old: 1\n"


def run(common: ModuleType, monkeypatch: pytest.MonkeyPatch, *argv: str, **kwargs: object) -> int:
    """common.run(rename_old) with command line `argv`."""
    monkeypatch.setattr("sys.argv", ["migrate-test.py", *argv])
    return common.run("Test migration.", rename_old, **kwargs)


def test_run_migrates_every_file_under_gemeenten_dir(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    migrated = write_env(tmp_path, "asse", "prod", "old: 1\n")
    write_env(tmp_path, "bode", "test", "keep: 1\n")

    assert run(common, monkeypatch, "--gemeenten-dir", str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert f"[migrated] {migrated}\n    - old renamed\n    - detail\n" in out
    assert out.endswith("\n1 migrated, 1 unchanged, 0 error\n")
    assert migrated.read_text(encoding="utf-8") == "new: 1\n"


def test_run_check_exits_1_when_a_file_needs_migrating(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    path = write_env(tmp_path, "asse", "prod", "old: 1\n")

    assert run(common, monkeypatch, "--check", str(path)) == 1
    assert capsys.readouterr().out.endswith("\n1 needs migration, 0 unchanged, 0 error\n")


def test_run_dry_run_keeps_stdout_for_the_diff(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    path = write_env(tmp_path, "asse", "prod", "old: 1\n")

    assert run(common, monkeypatch, "--dry-run", str(path)) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(f"--- a/{path}\n")
    assert captured.err.endswith("\n1 migrated, 0 unchanged, 0 error\n")


def test_run_without_files_found_exits_1(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    assert run(common, monkeypatch, "--gemeenten-dir", str(tmp_path), file_name="ssl-gateway.yml") == 1
    assert capsys.readouterr().err == "No ssl-gateway.yml files found.\n"


def test_run_takes_the_scripts_own_option_and_summary_suffix(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def add_level(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--level", type=int, default=1)

    def suffix(counts: dict[str, int], notes: list[list[str]]) -> str:
        return f"; {counts['migrated']} file(s), {sum(map(len, notes))} note(s)"

    path = write_env(tmp_path, "asse", "prod", "old: 1\n")

    assert run(common, monkeypatch, "--level", "2", str(path), add_arguments=add_level, summary_suffix=suffix) == 0
    assert capsys.readouterr().out.endswith("\n1 migrated, 0 unchanged, 0 error; 1 file(s), 2 note(s)\n")
