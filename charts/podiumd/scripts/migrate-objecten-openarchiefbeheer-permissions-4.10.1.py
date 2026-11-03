#!/usr/bin/env python3
"""Give Open Archiefbeheer's Objecten token a permission on the productaanvraag object type (PodiumD 4.10.1).

In objecten.configuration.data, the tokenauth item `identifier: openarchiefbeheer`
has no `permissions` in most gemeente values. Objecten then gives that token no
access to any object: only an `is_superuser` token sees every object type.
When Open Archiefbeheer destroys a zaak, it deletes the zaak's related objects
in Objecten (DELETE /objects/{uuid}?zaak=...). That needs read_and_write on the
object's type, so the destruction of such a zaak fails with 403.

This script adds the permission to every such item:

  permissions:
    - object_type: "REP_ZAC_PRODUCTAANVRAAG_UUID_REP"
      mode: read_and_write

When objecttypes.items creates Productaanvraag-Dimpact under another uuid,
the permission names that uuid instead.

An item that has `permissions` or `is_superuser: true` is left alone; a CHECK
note names the one whose permissions lack read_and_write on the productaanvraag
object type. A file without the item changes nothing. A file whose
objecttypes.items does not create the productaanvraag object type (by this
uuid or by name Productaanvraag-Dimpact) is left alone with a CHECK note:
Objecten runs the objecttypes step before tokenauth, and a permission on an
unknown object type fails the configuration job.

The block is inserted after the item's last line: comments, quoting and
REP_..._REP placeholders stay as they are. Before writing, the script checks
that the edited file parses to exactly the original values plus the permission;
it refuses to write a file that does not. Running it twice is safe: the second
run changes nothing.

Exit code: 1 when a file has an error, or under --check when a file needs
migrating; else 0.

Usage:
  pip install ruamel.yaml
  python3 migrate-objecten-openarchiefbeheer-permissions-4.10.1.py --dry-run --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-objecten-openarchiefbeheer-permissions-4.10.1.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-objecten-openarchiefbeheer-permissions-4.10.1.py path/to/podiumd.yml ...
"""

from __future__ import annotations

import argparse
import copy
import sys

from migrate_common import OBJECTEN_DATA_PATH
from migrate_common import MigrationError
from migrate_common import block_end
from migrate_common import created_object_type
from migrate_common import literal_block
from migrate_common import load_rt
from migrate_common import load_safe
from migrate_common import objecten_data
from migrate_common import run
from migrate_common import verify_objecten_data_edit

IDENTIFIER = "openarchiefbeheer"
OBJECT_TYPE = "REP_ZAC_PRODUCTAANVRAAG_UUID_REP"
OBJECT_TYPE_NAME = "Productaanvraag-Dimpact"
MODE = "read_and_write"


def _permission_lines(key_col: int, object_type: str) -> list[str]:
    pad = " " * key_col
    # Quoted like the environment values write object types: an unquoted
    # placeholder (REP_..._REP) fails the SSC quoting check.
    return [
        f"{pad}permissions:\n",
        f'{pad}  - object_type: "{object_type}"\n',
        f"{pad}    mode: {MODE}\n",
    ]


def _check_note(index: int, item: dict, object_type: str) -> str | None:
    if item.get("is_superuser") is True:
        return None
    if any(p.get("object_type") == object_type and p.get("mode") == MODE for p in item.get("permissions") or []):
        return None
    return (
        f"CHECK tokenauth.items[{index}] ({IDENTIFIER}) has permissions without {MODE} on {object_type}: "
        "Open Archiefbeheer cannot delete productaanvraag objects; left unchanged"
    )


def migrate_text(text: str, _args: argparse.Namespace | None = None) -> tuple[str, list[str]]:
    doc = load_safe(text)
    if not isinstance(doc, dict):
        raise MigrationError("not a YAML mapping")
    data, inner = objecten_data(doc)
    if data is None:
        return text, []
    items = (inner.get("tokenauth") or {}).get("items") or []
    targets = [i for i, item in enumerate(items) if isinstance(item, dict) and item.get("identifier") == IDENTIFIER]
    notes: list[str] = []
    if len(targets) > 1:
        notes.append(f"CHECK tokenauth has {len(targets)} items with identifier {IDENTIFIER}: keep one")
    todo = [i for i in targets if "permissions" not in items[i] and items[i].get("is_superuser") is not True]
    object_type = created_object_type(inner, OBJECT_TYPE, OBJECT_TYPE_NAME)
    notes += [n for i in targets if i not in todo and (n := _check_note(i, items[i], object_type or OBJECT_TYPE))]
    if not todo:
        return text, notes
    if object_type is None:
        notes.append(
            f"CHECK objecttypes.items does not create {OBJECT_TYPE_NAME} ({OBJECT_TYPE}): "
            "add it before giving the token a permission on it; left unchanged"
        )
        return text, notes

    lines = text.splitlines(keepends=True)
    start, end, indent = literal_block(lines, load_rt(text)["objecten"]["configuration"], "data", OBJECTEN_DATA_PATH)
    seq = load_rt(data)["tokenauth"]["items"]
    # Bottom-up, so the line numbers of the items above stay valid.
    for i in reversed(todo):
        first, col = seq.lc.item(i)
        key_col = indent + col
        at = block_end(lines, start + first, end, key_col)
        lines[at:at] = _permission_lines(key_col, object_type)
    new = "".join(lines)

    want = copy.deepcopy(inner)
    for i in todo:
        want["tokenauth"]["items"][i]["permissions"] = [{"object_type": object_type, "mode": MODE}]
    verify_objecten_data_edit(new, doc, want)
    notes += [f"tokenauth.items[{i}] ({IDENTIFIER}): added {MODE} on {object_type}" for i in todo]
    return new, notes


if __name__ == "__main__":
    sys.exit(run(__doc__, migrate_text))
