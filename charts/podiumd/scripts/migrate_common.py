"""Shared parts of the migrate-*.py scripts in this directory.

A script defines migrate_text(text, args) -> (new_text, notes), raising
MigrationError for a file it cannot migrate automatically, and calls run().
run() gives every script the same command line (files, --gemeenten-dir,
--dry-run, --check), output and exit codes. A script with its own file loop
(migrate-objecten-4.1.0.py) uses only the helpers.

Run a script as `python3 <script>`: Python then finds this module next to it.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import os
import sys
from collections.abc import Callable

try:
    from ruamel.yaml import YAML
except ImportError:  # pragma: no cover
    sys.exit("ruamel.yaml is required: pip install ruamel.yaml")

Migrate = Callable[[str, argparse.Namespace], "tuple[str, list[str]]"]

STATUSES = ("migrated", "needs migration", "unchanged", "error")


class MigrationError(Exception):
    """The file cannot be migrated automatically."""


def rt_yaml(width: int | None = None) -> YAML:
    """A round-trip YAML that keeps quotes; `width` avoids re-wrapping long lines."""
    yaml = YAML()
    yaml.preserve_quotes = True
    if width is not None:
        yaml.width = width
    return yaml


def load_rt(text: str):
    return rt_yaml().load(text)


def load_safe(text: str):
    return YAML(typ="safe", pure=True).load(text)


def load_rt_all(text: str) -> list:
    return list(rt_yaml().load_all(text))


def load_safe_all(text: str) -> list:
    return list(YAML(typ="safe", pure=True).load_all(text))


def error_note(e: Exception) -> str:
    """The note for a file that failed: a MigrationError's own text, else the
    exception type with the YAML error's line and problem when it has them."""
    if isinstance(e, MigrationError):
        return str(e)
    mark = getattr(e, "problem_mark", None)
    where = f" at line {mark.line + 1}" if mark else ""
    problem = getattr(e, "problem", None) or next(iter(str(e).splitlines()), "")
    return f"unexpected {type(e).__name__}{where}: {problem[:200]}"


def unified_diff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def write_lf(path: str, text: str) -> None:
    """Write `text` with LF line endings on every OS."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def migrate_file(
    path: str,
    migrate: Migrate,
    args: argparse.Namespace,
    check_notes: Callable[[list[str]], list[str]] | None = None,
) -> tuple[str, list[str]]:
    """(status, notes) for one file; writes it unless --dry-run or --check.

    Universal newlines read CRLF as LF, so a migrated file is written with LF.
    check_notes picks the notes shown for a file that needs migrating under --check.
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate(text, args)
    except Exception as e:  # noqa: BLE001 -- unexpected file shape: report, never write half a migration
        return "error", [error_note(e)]
    if new == text:
        return "unchanged", notes
    if args.check:
        return "needs migration", check_notes(notes) if check_notes else notes
    if args.dry_run:
        sys.stdout.write(unified_diff(path, text, new))
    else:
        write_lf(path, text=new)
    return "migrated", notes


def run(
    doc: str | None,
    migrate: Migrate,
    *,
    file_name: str = "podiumd.yml",
    files_help: str | None = None,
    add_arguments: Callable[[argparse.ArgumentParser], None] | None = None,
    check_notes: Callable[[list[str]], list[str]] | None = None,
    summary_suffix: Callable[[dict[str, int], list[list[str]]], str] | None = None,
) -> int:
    """The command line of a migrate script. Exit code 1 on an error, or under
    --check when a file needs migrating; else 0.

    file_name is the file --gemeenten-dir collects; files_help describes the
    files a script accepts when that is more than file_name. add_arguments
    adds the script's own options; summary_suffix gets the status counts and
    every file's notes and returns text to add after the summary line.
    """
    parser = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "files", nargs="*", help=f"{files_help or file_name + ' files'} (default: all under --gemeenten-dir)"
    )
    parser.add_argument(
        "--gemeenten-dir", help=f"directory with <gemeente>/<env>/{file_name} (used when no files are given)"
    )
    if add_arguments:
        add_arguments(parser)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 when a file needs migrating")
    args = parser.parse_args()

    if not args.files and not args.gemeenten_dir:
        parser.error(f"give {file_name} files or --gemeenten-dir")
    files = args.files or sorted(
        glob.glob(os.path.join(os.path.expanduser(args.gemeenten_dir), "*", "*", file_name))
    )
    if not files:
        print(f"No {file_name} files found.", file=sys.stderr)
        return 1
    counts = dict.fromkeys(STATUSES, 0)
    all_notes: list[list[str]] = []
    # Under --dry-run stdout carries the diff only.
    out = sys.stderr if args.dry_run else sys.stdout
    for path in files:
        status, notes = migrate_file(path, migrate, args, check_notes)
        counts[status] += 1
        all_notes.append(notes)
        print(f"[{status}] {path}", file=out)
        for note in notes:
            print(f"    - {note}", file=out)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v or k in ("unchanged", "error"))
    if summary_suffix:
        summary += summary_suffix(counts, all_notes)
    print(f"\n{summary}", file=out)
    return 1 if counts["error"] or counts["needs migration"] else 0
