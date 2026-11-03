#!/usr/bin/env python3
"""Give KISS's logboek token read access to the Activiteitenlog object type (PodiumD 4.10.1).

KISS reads the ITA Activiteitenlog (logboek) from Objecten with
kiss.settings.logboek.token, on the object type at the end of
kiss.settings.logboek.objectTypeUrl. In most gemeente values that token is the
one of a tokenauth item in objecten.configuration.data (often `contact`) whose
permissions do not include that object type. Objecten then answers 200 with an
empty list, so KISS shows no ITA activity and nothing reports an error.

This script finds the tokenauth items whose `token` equals
kiss.settings.logboek.token (the same value or the same REP_..._REP
placeholder) and adds to each one's permissions:

    - object_type: "<the object type of kiss.settings.logboek.objectTypeUrl>"
      mode: read_only

KISS only reads the logboek (its proxy refuses anything but GET), so read_only
is enough. An item with `is_superuser: true` or with any permission on that
object type is left alone. CHECK notes name an item without permissions, a
logboek setting without token or objectTypeUrl, and a token that matches no
item. A file whose objecttypes.items does not create the object type (by this
uuid or by name Activiteitenlog) is left alone with a CHECK note: Objecten runs
the objecttypes step before tokenauth, and a permission on an unknown object
type fails the configuration job. A file with kiss.enabled: false is not
edited; a CHECK note names a matching item that lacks the permission, since an
overlay may enable KISS.

The permission is inserted after the item's last permission: comments, quoting
and REP_..._REP placeholders stay as they are. Before writing, the script
checks that the edited file parses to exactly the original values plus the
permission; it refuses to write a file that does not. Running it twice is safe:
the second run changes nothing.

Exit code: 1 when a file has an error, or under --check when a file needs
migrating; else 0.

Usage:
  pip install ruamel.yaml
  python3 migrate-objecten-kiss-logboek-permission-4.10.1.py --dry-run --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-objecten-kiss-logboek-permission-4.10.1.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-objecten-kiss-logboek-permission-4.10.1.py path/to/podiumd.yml ...
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

OBJECT_TYPE_NAME = "Activiteitenlog"
MODE = "read_only"
LOGBOEK_PATH = "kiss.settings.logboek"


def _permission_lines(dash_col: int, key_col: int, object_type: str) -> list[str]:
    # Quoted like the environment values write object types: an unquoted
    # placeholder (REP_..._REP) fails the SSC quoting check.
    return [
        f'{" " * dash_col}- object_type: "{object_type}"\n',
        f"{' ' * key_col}mode: {MODE}\n",
    ]


def _targets(items: list, token: str, object_type: str) -> tuple[list[int], list[int], list[str]]:
    """(indices of the items to give the permission, indices of every item with `token` that lacks it,
    CHECK notes) for the items with `token`. An item without any permissions lacks it but is not edited."""
    todo: list[int] = []
    lacking: list[int] = []
    notes: list[str] = []
    matched = [i for i, item in enumerate(items) if isinstance(item, dict) and item.get("token") == token]
    if not matched:
        notes.append(
            f"CHECK no tokenauth item has {LOGBOEK_PATH}.token: give the item with KISS's logboek token "
            f"{MODE} on {object_type} by hand"
        )
    for i in matched:
        item = items[i]
        name = f"tokenauth.items[{i}] ({item.get('identifier')})"
        if item.get("is_superuser") is True:
            continue
        permissions = item.get("permissions")
        if not permissions:
            lacking.append(i)
            notes.append(f"CHECK {name} has KISS's logboek token but no permissions: left unchanged")
        elif not any(isinstance(p, dict) and p.get("object_type") == object_type for p in permissions):
            lacking.append(i)
            todo.append(i)
    return todo, lacking, notes


def migrate_text(text: str, _args: argparse.Namespace | None = None) -> tuple[str, list[str]]:
    doc = load_safe(text)
    if not isinstance(doc, dict):
        raise MigrationError("not a YAML mapping")
    if not isinstance(doc.get("kiss"), dict):
        return text, []
    disabled = doc["kiss"].get("enabled") is False
    data, inner = objecten_data(doc)
    if data is None:
        return text, []
    logboek = (doc["kiss"].get("settings") or {}).get("logboek") or {}
    token, type_url = logboek.get("token"), logboek.get("objectTypeUrl")
    if not token or not type_url:
        if disabled:
            return text, []
        return text, [
            f"CHECK {LOGBOEK_PATH}.token or .objectTypeUrl is empty: KISS shows no ITA activity; nothing to migrate"
        ]
    object_type = str(type_url).rstrip("/").rsplit("/", 1)[-1]
    items = (inner.get("tokenauth") or {}).get("items") or []
    todo, lacking, notes = _targets(items, token, object_type)
    if disabled:
        # An overlay may enable KISS: report the missing permission, edit nothing.
        return text, [
            f"CHECK kiss.enabled is false in this file, but tokenauth.items[{i}] ({items[i].get('identifier')}) "
            f"has KISS's logboek token without {MODE} on {object_type}: where KISS is enabled (an overlay), "
            "add it there or by hand; left unchanged"
            for i in lacking
        ]
    if not todo:
        return text, notes
    if created_object_type(inner, object_type, OBJECT_TYPE_NAME) is None:
        notes.append(
            f"CHECK objecttypes.items does not create {OBJECT_TYPE_NAME} ({object_type}): "
            "add it before giving the token a permission on it; left unchanged"
        )
        return text, notes

    lines = text.splitlines(keepends=True)
    start, end, indent = literal_block(lines, load_rt(text)["objecten"]["configuration"], "data", OBJECTEN_DATA_PATH)
    seq = load_rt(data)["tokenauth"]["items"]
    # Bottom-up, so the line numbers of the items above stay valid.
    for i in reversed(todo):
        permissions = seq[i]["permissions"]
        if permissions.fa.flow_style():
            raise MigrationError(f"tokenauth.items[{i}].permissions is a flow sequence: add the permission by hand")
        first, col = permissions.lc.item(len(permissions) - 1)
        key_col = indent + col
        dash_col = lines[start + first].rindex("-", 0, key_col)
        at = block_end(lines, start + first, end, key_col)
        lines[at:at] = _permission_lines(dash_col, key_col, object_type)
    new = "".join(lines)

    want = copy.deepcopy(inner)
    for i in todo:
        want["tokenauth"]["items"][i]["permissions"].append({"object_type": object_type, "mode": MODE})
    verify_objecten_data_edit(new, doc, want)
    notes += [f"tokenauth.items[{i}] ({items[i].get('identifier')}): added {MODE} on {object_type}" for i in todo]
    return new, notes


if __name__ == "__main__":
    sys.exit(run(__doc__, migrate_text))
