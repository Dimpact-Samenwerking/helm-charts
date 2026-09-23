"""Scans values.yaml for duplicate keys that would silently overwrite an
earlier value. Each YAML sequence item gets its own scope (tagged by the
line its "-" appears on) so that unrelated list items sharing a key name
(e.g. every item in a list having its own "value:" or "mountPath:") are
never treated as duplicates of each other."""

import re

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


@dataclass
class DuplicateKeyScan:
    """Running state for check_duplicate_keys' line-by-line scan: filename
    (for message text only), the indent-tagged scope stack, the keys seen
    so far per scope, and the duplicates found. Bundled so
    _scan_list_item_line/_scan_key_line/_register_duplicate_key can share
    and mutate it without each taking four separate parameters."""

    filename: str
    stack: list = field(default_factory=list)
    scope_keys: dict = field(default_factory=dict)
    duplicates: list = field(default_factory=list)


def _register_duplicate_key(scan: DuplicateKeyScan, scope_id: tuple, key: str, line_no: int):
    scan.scope_keys.setdefault(scope_id, {})
    if key in scan.scope_keys[scope_id]:
        parent = " > ".join(scope_id) if scope_id else "(root)"
        scan.duplicates.append(
            f'{scan.filename}:{line_no}: duplicate "{key}" under [{parent}] '
            f"(first line {scan.scope_keys[scope_id][key]})"
        )
    else:
        scan.scope_keys[scope_id][key] = line_no


def _scan_list_item_line(scan: DuplicateKeyScan, key_re: re.Pattern, dash_re: re.Pattern, line: str, line_no: int):
    """A "- ..." line: closes any scope at or past this item's indent,
    opens a new one unique to this occurrence (so sibling list items never
    share a scope), then treats "- key: ..." same as a plain key line."""
    dash_m = dash_re.match(line)
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


def _scan_key_line(scan: DuplicateKeyScan, key_re: re.Pattern, line: str, line_no: int):
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
    """Scan values.yaml for duplicate keys that would silently overwrite an
    earlier value. See module docstring for the scoping rule, and
    DuplicateKeyScan/_scan_list_item_line/_scan_key_line for the
    line-by-line scan itself."""
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
