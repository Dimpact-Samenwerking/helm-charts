"""Scan values.yaml for duplicate keys that would silently overwrite an earlier value.

Each sequence item gets its own scope, so list items sharing a key name (e.g. "value:")
are not duplicates of each other.
"""

import re

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


@dataclass
class DuplicateKeyScan:
    """Mutable state for check_duplicate_keys' line-by-line scan."""

    filename: str
    stack: list[tuple[int, str]] = field(default_factory=list)
    scope_keys: dict[tuple[str, ...], dict[str, int]] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)


def _register_duplicate_key(scan: DuplicateKeyScan, scope_id: tuple[str, ...], key: str, line_no: int):
    scan.scope_keys.setdefault(scope_id, {})
    if key in scan.scope_keys[scope_id]:
        parent = " > ".join(scope_id) if scope_id else "(root)"
        scan.duplicates.append(
            f'{scan.filename}:{line_no}: duplicate "{key}" under [{parent}] '
            f"(first line {scan.scope_keys[scope_id][key]})"
        )
    else:
        scan.scope_keys[scope_id][key] = line_no


def _scan_list_item_line(
    scan: DuplicateKeyScan, key_re: re.Pattern[str], dash_re: re.Pattern[str], line: str, line_no: int
):
    """A "- ..." line: close scopes at or past its indent, open one unique to this item,
    then handle "- key: ..." like a plain key line."""
    dash_m = dash_re.match(line)
    if dash_m is None:
        return
    list_indent = len(dash_m.group(1))
    rest = dash_m.group(2)
    while scan.stack and scan.stack[-1][0] >= list_indent:
        scan.stack.pop()
    stack_id = f"<item:{line_no}>"
    scan.stack.append((list_indent, stack_id))

    km = key_re.match(rest)
    if km:
        key = km.group(2).strip()
        scope_id = tuple(k for _, k in scan.stack)
        _register_duplicate_key(scan, scope_id, key, line_no)
        scan.stack.append((list_indent + 2, key))


def _scan_key_line(scan: DuplicateKeyScan, key_re: re.Pattern[str], line: str, line_no: int):
    m = key_re.match(line)
    if not m:
        return
    indent = len(m.group(1))
    key = m.group(2).strip()
    while scan.stack and scan.stack[-1][0] >= indent:
        scan.stack.pop()
    scope_id = tuple(k for _, k in scan.stack)
    _register_duplicate_key(scan, scope_id, key, line_no)
    scan.stack.append((indent, key))


def check_duplicate_keys(chart_dir: Path):
    """Scan values.yaml for duplicate keys (see module docstring for scoping)."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines(keepends=True)
    key_re = re.compile(r"^(\s*)([a-zA-Z0-9_\-][^:#\n]*?)\s*:")
    dash_re = re.compile(r"^(\s*)-\s*(.*)$")
    scan = DuplicateKeyScan(filename=values_path.name)

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("-"):
            _scan_list_item_line(scan, key_re, dash_re, line, i)
            continue
        _scan_key_line(scan, key_re, line, i)

    if scan.duplicates:
        print(f"FOUND {len(scan.duplicates)} duplicate(s):")
        for d in scan.duplicates:
            print(" ", d)
        return False, f"{len(scan.duplicates)} duplicate(s) found"
    print(f"OK: no duplicate keys in {values_path.name}")
    return True, "0 duplicates"
