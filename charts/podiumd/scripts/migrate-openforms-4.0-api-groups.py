#!/usr/bin/env python3
"""
Migrate gemeente values files for Open Forms 4.0: remove the API group fields
its setup-configuration no longer accepts.

Open Forms 4.0 (openformulieren 4.0.2, PodiumD 4.10.0) removed these fields
from the setup-configuration models of its API groups:

  objects_api.groups[]   catalogue_domain, catalogue_rsin,
                         document_type_submission_report,
                         document_type_submission_csv, document_type_attachment
  zgw_api.groups[]       catalogue_domain, catalogue_rsin

A group that still sets one of them fails validation (`Extra inputs are not
permitted`), the openformulieren-config post-upgrade hook Job fails, and the
helm upgrade fails with it. See
docs/_UPGRADE_PATHS/4.9.5-to-4.10.0-values-deltas.md, "Remove the catalogue
and document type fields from the API groups".

This script removes those keys from every group under objects_api.groups and
zgw_api.groups in openformulieren.configuration.data. The three document_type_*
keys are also removed from zgw_api groups, where 3.5.x never accepted them.
Nothing else changes.

The removed values are not lost on an upgrade: Open Forms 4.0 keeps the
catalogue and the document types of an API group in its database (editable
in the admin; a form can override them in its registration options). On a new
environment they must be set in the admin. The script prints, per file, the
values it removed, so they can be set there.

Input files:
  - a gemeente podiumd.yml (openformulieren.configuration.data is a block
    scalar holding the setup-configuration YAML);
  - a setup-configuration data file whose top level holds objects_api/zgw_api
    (e.g. podiumd-infra's openformulieren.configuration.data.yml layers).

The file is edited in place, line by line: only the removed lines change, so
comments, quoting, indentation and REP_..._REP placeholders stay as they are.
Before writing, the script checks that the edited file parses to exactly the
old values minus the removed keys; it refuses to write a file that does not.
Running it again on a migrated file changes nothing.

Requires: ruamel.yaml (pip install ruamel.yaml)

Usage:
    # Migrate all podiumd.yml files under a gemeenten directory
    python3 scripts/migrate-openforms-4.0-api-groups.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten

    # Preview (unified diff, nothing written)
    python3 scripts/migrate-openforms-4.0-api-groups.py --dry-run path/to/podiumd.yml ...

    # Exit 1 when a file still needs migrating (for a pipeline check)
    python3 scripts/migrate-openforms-4.0-api-groups.py --check --gemeenten-dir <dir>
"""

from __future__ import annotations

import argparse
import copy
import difflib
import glob
import os
import sys

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ERROR: ruamel.yaml is required. Install with: pip install ruamel.yaml", file=sys.stderr)
    sys.exit(1)

DOCUMENT_TYPE_KEYS = ("document_type_submission_report", "document_type_submission_csv", "document_type_attachment")
REMOVED_KEYS = {
    "objects_api": ("catalogue_domain", "catalogue_rsin", *DOCUMENT_TYPE_KEYS),
    # 3.5.x only knew the catalogue fields here; the document types are removed
    # too because 4.0 rejects any unknown key.
    "zgw_api": ("catalogue_domain", "catalogue_rsin", *DOCUMENT_TYPE_KEYS),
}


class MigrationError(Exception):
    """The file cannot be migrated automatically."""


def _rt_load(text: str):
    y = YAML()
    y.preserve_quotes = True
    return y.load(text)


def _safe_load(text: str):
    return YAML(typ="safe", pure=True).load(text)


def removals(data) -> list[tuple[str, int, str, object]]:
    """(section, group index, key, value) for every key to remove from a parsed data mapping."""
    out = []
    if not isinstance(data, dict):
        return out
    for section, keys in REMOVED_KEYS.items():
        groups = (data.get(section) or {}).get("groups") if isinstance(data.get(section), dict) else None
        for i, group in enumerate(groups or []):
            if isinstance(group, dict):
                out.extend((section, i, k, group[k]) for k in keys if k in group)
    return out


def strip_data(data):
    """A deep copy of `data` without the removed keys."""
    data = copy.deepcopy(data)
    for section, i, key, _ in removals(data):
        del data[section]["groups"][i][key]
    return data


def _key_lines(inner_rt, offset: int) -> list[int]:
    """Absolute line numbers of the keys to remove, from a round-trip-loaded data mapping."""
    lines = []
    for section, i, key, _ in removals(inner_rt):
        lines.append(offset + inner_rt[section]["groups"][i].lc.key(key)[0])
    return lines


def _value_end(lines: list[str], start: int, end: int) -> int:
    """End of a key's value: following lines indented deeper (a folded or nested value)."""
    col = len(lines[start]) - len(lines[start].lstrip(" "))
    j = start + 1
    while j < end and lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip(" "))) > col:
        j += 1
    return j


def _drop(lines: list[str], starts: list[int], end: int) -> list[str]:
    drop = set()
    for s in starts:
        drop.update(range(s, _value_end(lines, s, end)))
    return [ln for n, ln in enumerate(lines) if n not in drop]


def migrate_text(text: str) -> tuple[str, list[str]]:
    """Return (new text, notes). Raises MigrationError when the file cannot be migrated safely."""
    doc = _safe_load(text)
    if not isinstance(doc, dict):
        raise MigrationError("not a YAML mapping")
    lines = text.splitlines(keepends=True)

    of = doc.get("openformulieren")
    if isinstance(of, dict):
        data = (of.get("configuration") or {}).get("data")
        if not data:
            return text, ["no openformulieren.configuration.data"]
        if not isinstance(data, str):
            raise MigrationError("openformulieren.configuration.data is not a block scalar string")
        inner = _safe_load(data)
        found = removals(inner)
        if not found:
            return text, []
        rt = _rt_load(text)
        cfg = rt["openformulieren"]["configuration"]
        data_line = cfg.lc.key("data")[0]
        if not lines[data_line].rstrip().endswith(("|", "|-", "|+")):
            raise MigrationError(f"line {data_line + 1}: openformulieren.configuration.data is not a literal block (|)")
        # A literal block's content starts on the next line, one source line per content line.
        start = data_line + 1
        block_end = start
        while block_end < len(lines) and (not lines[block_end].strip()
                                          or lines[block_end].startswith(" " * (len(lines[start]) - len(lines[start].lstrip(" "))))):
            block_end += 1
        starts = _key_lines(_rt_load(data), start)
        new_lines = _drop(lines, starts, block_end)
        new = "".join(new_lines)
        expected = copy.deepcopy(doc)
        expected["openformulieren"]["configuration"]["data"] = strip_data(inner)
        got = _safe_load(new)
        got["openformulieren"]["configuration"]["data"] = _safe_load(got["openformulieren"]["configuration"]["data"])
    elif any(k in doc for k in REMOVED_KEYS):
        found = removals(doc)
        if not found:
            return text, []
        new = "".join(_drop(lines, _key_lines(_rt_load(text), 0), len(lines)))
        expected, got = strip_data(doc), _safe_load(new)
    else:
        return text, ["no openformulieren block and no objects_api/zgw_api data"]

    if got != expected:
        raise MigrationError("edited file does not parse to the intended values; not written")
    notes = [f"{s}.groups[{i}] ({_ident(doc, s, i)}): removed {k}: {v!r}" for s, i, k, v in found]
    return new, notes


def _ident(doc, section, i):
    of = doc.get("openformulieren")
    data = _safe_load(of["configuration"]["data"]) if isinstance(of, dict) else doc
    return data[section]["groups"][i].get("identifier", "?")


def _diff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def process(path: str, args) -> tuple[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate_text(text)
    except MigrationError as e:
        return "error", [str(e)]
    except Exception as e:  # unexpected file shape: report, never write half a migration
        # A YAML error (e.g. a duplicate key elsewhere in the file) names its line and problem.
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        problem = getattr(e, "problem", None) or str(e).splitlines()[0]
        return "error", [f"unexpected {type(e).__name__}{where}: {problem[:200]}"]
    if new == text:
        return "unchanged", notes
    if args.dry_run:
        sys.stdout.write(_diff(path, text, new))
    elif not args.check:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    return ("needs migration" if args.check else "migrated"), notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="podiumd.yml or data files (default: all under --gemeenten-dir)")
    parser.add_argument("--gemeenten-dir", help="directory with <gemeente>/<env>/podiumd.yml (used when no files are given)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 when a file needs migrating")
    args = parser.parse_args()

    if not args.files and not args.gemeenten_dir:
        parser.error("give files or --gemeenten-dir")
    files = args.files or sorted(glob.glob(os.path.join(os.path.expanduser(args.gemeenten_dir), "*", "*", "podiumd.yml")))
    if not files:
        print("No podiumd.yml files found.", file=sys.stderr)
        return 1
    counts: dict[str, int] = {"migrated": 0, "needs migration": 0, "unchanged": 0, "error": 0}
    out = sys.stderr if args.dry_run else sys.stdout
    for path in files:
        status, notes = process(path, args)
        counts[status] += 1
        print(f"[{status}] {path}", file=out)
        for n in notes:
            print(f"    - {n}", file=out)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v or k in ("unchanged", "error"))
    print(f"\n{summary}", file=out)
    if counts["migrated"] or counts["needs migration"]:
        print("The removed values stay in the Open Forms database on an upgrade. On a new environment, set the "
              "catalogue and document types in the admin on the API group, or per form.", file=out)
    return 1 if counts["error"] or counts["needs migration"] else 0


if __name__ == "__main__":
    sys.exit(main())
