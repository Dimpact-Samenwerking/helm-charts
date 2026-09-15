#!/usr/bin/env python3
"""
PodiumD 4.9.2 — scope the openarchiefbeheer Objecten token to read-only.

In objecten.configuration.data, the tokenauth item for
`identifier: openarchiefbeheer` currently has no `permissions` restriction in
most gemeente podiumd.yml files, unlike every other tokenauth item in the same
file (zaak, ita, omc, ...), which already scope access via `permissions`. This
adds the same restriction already used elsewhere for this object type:

    permissions:
      - object_type: "REP_ZAC_PRODUCTAANVRAAG_UUID_REP"
        mode: read_only

Only touches files where the `openarchiefbeheer` tokenauth item exists AND has
no `permissions` key yet — safe to re-run (idempotent), and does nothing where
OpenArchiefbeheer has no Objecten access configured at all.

Detection reads the embedded configuration.data block through yq (robust
against formatting/ordering variance), but the actual edit splices the new
lines directly into the file's own text — it does not round-trip the whole
file through yq, which reformats it wholesale (strips blank lines, collapses
folded scalars, etc.) and would turn a 3-line change into a page of noise
across every gemeente file.

Requires: yq v4 (https://github.com/mikefarah/yq) — install with: brew install yq

Usage:
    # Migrate all podiumd.yml files in the default gemeenten directories
    python3 scripts/migrate-objecten-openarchiefbeheer-permissions-4.9.2.py

    # Preview changes without modifying files
    python3 scripts/migrate-objecten-openarchiefbeheer-permissions-4.9.2.py --dry-run

    # Migrate specific files
    python3 scripts/migrate-objecten-openarchiefbeheer-permissions-4.9.2.py path/to/podiumd.yml ...
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

GEMEENTEN_DIRS = [
    os.path.expanduser("~/projects/dimpact/ssctwente/ExternalsPodiumD/applications/gemeenten"),
    os.path.expanduser("~/projects/dimpact/ssctwente/SSCHostingSync/applications/gemeenten"),
]

TARGET_IDENTIFIER = "openarchiefbeheer"
PERMISSION_OBJECT_TYPE = "REP_ZAC_PRODUCTAANVRAAG_UUID_REP"
PERMISSION_MODE = "read_only"

DATA_LINE_RE = re.compile(r"^(?P<indent>\s*)data:\s*[|>][-+]?\s*$")
IDENTIFIER_LINE_RE = re.compile(
    r"^(?P<indent>\s*)-\s+identifier:\s*" + re.escape(TARGET_IDENTIFIER) + r"\s*$"
)


def yq_get(expr, file):
    r = subprocess.run(["yq", expr, file], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def check_yq():
    try:
        r = subprocess.run(["yq", "--version"], capture_output=True, text=True, check=True)
        if "mikefarah" not in r.stdout and "github.com/mikefarah" not in r.stdout:
            print("Warning: yq found but may not be mikefarah/yq v4. Output:", r.stdout.strip())
    except FileNotFoundError:
        print("Error: yq not found. Install with: brew install yq")
        sys.exit(1)


def has_target_item(data_file):
    count = yq_get(
        f'[.tokenauth.items[] | select(.identifier == "{TARGET_IDENTIFIER}")] | length',
        data_file,
    )
    return count not in ("0", "null", "")


def item_already_has_permissions(data_file):
    result = yq_get(
        f'[.tokenauth.items[] | select(.identifier == "{TARGET_IDENTIFIER}")]'
        '[0] | has("permissions")',
        data_file,
    )
    return result == "true"


def find_data_block(lines):
    """Locate the objecten.configuration.data block-scalar's content range.

    Returns (content_start, content_end) line indices (content_end exclusive),
    or None if not found. Assumes a single top-level `objecten:` section.
    """

    try:
        obj_start = next(i for i, l in enumerate(lines) if l.rstrip("\n") == "objecten:")
    except StopIteration:
        return None

    obj_end = len(lines)
    for i in range(obj_start + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith((" ", "\t")):
            obj_end = i
            break

    data_line_idx = None
    for i in range(obj_start + 1, obj_end):
        if DATA_LINE_RE.match(lines[i].rstrip("\n")):
            data_line_idx = i
            break
    if data_line_idx is None:
        return None

    data_indent = len(DATA_LINE_RE.match(lines[data_line_idx].rstrip("\n")).group("indent"))

    content_start = data_line_idx + 1
    content_indent = None
    for i in range(content_start, obj_end):
        stripped = lines[i].rstrip("\n")
        if not stripped.strip():
            continue
        content_indent = len(stripped) - len(stripped.lstrip(" "))
        break
    if content_indent is None or content_indent <= data_indent:
        return None

    content_end = obj_end
    for i in range(content_start, obj_end):
        stripped = lines[i].rstrip("\n")
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent < content_indent:
            content_end = i
            break

    return content_start, content_end


def splice_permissions(lines, content_start, content_end):
    """Insert the permissions block right after the openarchiefbeheer item's
    last property, within [content_start, content_end). Returns new lines, or
    None if the item line wasn't found in this range."""

    item_idx = None
    item_indent = None
    for i in range(content_start, content_end):
        m = IDENTIFIER_LINE_RE.match(lines[i].rstrip("\n"))
        if m:
            item_idx = i
            item_indent = len(m.group("indent"))
            break
    if item_idx is None:
        return None

    property_indent = item_indent + 2

    insert_at = content_end
    for i in range(item_idx + 1, content_end):
        stripped = lines[i].rstrip("\n")
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent < property_indent:
            insert_at = i
            break
        if indent == item_indent and stripped.lstrip().startswith("- "):
            insert_at = i
            break

    new_lines = [
        " " * property_indent + "permissions:\n",
        " " * (property_indent + 2) + f'- object_type: "{PERMISSION_OBJECT_TYPE}"\n',
        " " * (property_indent + 4) + f"mode: {PERMISSION_MODE}\n",
    ]

    return lines[:insert_at] + new_lines + lines[insert_at:]


def process_file(podiumd_yml, dry_run):
    """Process a single podiumd.yml. Returns (changed, reason)."""

    objecten_section = yq_get(".objecten", podiumd_yml)
    if objecten_section in ("null", "~", ""):
        return False, "no objecten section"

    data_raw = yq_get(".objecten.configuration.data", podiumd_yml)
    if not data_raw or data_raw in ("null", "~", '""', ""):
        return False, "configuration.data is empty"

    if "tokenauth" not in data_raw:
        return False, "no tokenauth in configuration.data"

    if TARGET_IDENTIFIER not in data_raw:
        return False, f"no tokenauth item for identifier: {TARGET_IDENTIFIER}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write(data_raw)
        temp_path = tf.name

    try:
        if not has_target_item(temp_path):
            return False, f"no tokenauth item for identifier: {TARGET_IDENTIFIER}"
        if item_already_has_permissions(temp_path):
            return False, "already has permissions"
    finally:
        os.unlink(temp_path)

    if dry_run:
        return True, "would add permissions (dry-run)"

    with open(podiumd_yml) as f:
        lines = f.readlines()

    block = find_data_block(lines)
    if block is None:
        return False, "could not locate configuration.data block in file text"

    new_lines = splice_permissions(lines, *block)
    if new_lines is None:
        return False, f"could not locate identifier: {TARGET_IDENTIFIER} line in file text"

    with open(podiumd_yml, "w") as f:
        f.writelines(new_lines)

    return True, "added permissions"


def find_podiumd_files():
    files = []
    for gemeenten_dir in GEMEENTEN_DIRS:
        pattern = os.path.join(gemeenten_dir, "*", "*", "podiumd.yml")
        files.extend(glob.glob(pattern))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific podiumd.yml files to process (default: all files in the gemeenten dirs)",
    )
    args = parser.parse_args()

    check_yq()

    files = args.files if args.files else find_podiumd_files()
    if not files:
        print(f"No podiumd.yml files found in {GEMEENTEN_DIRS}")
        sys.exit(1)

    if args.dry_run:
        print("Dry run — no files will be modified.\n")

    migrated = skipped = errors = 0

    for f in files:
        rel = f
        for gemeenten_dir in GEMEENTEN_DIRS:
            if f.startswith(gemeenten_dir):
                rel = os.path.relpath(f, gemeenten_dir)
                break
        try:
            changed, reason = process_file(f, args.dry_run)
            status = "CHANGED " if changed else "skipped "
            print(f"{status}  {rel}  ({reason})")
            if changed:
                migrated += 1
            else:
                skipped += 1
        except subprocess.CalledProcessError as e:
            print(f"ERROR    {rel}  (yq failed: {e.stderr.strip() if e.stderr else e})")
            errors += 1
        except Exception as e:
            print(f"ERROR    {rel}  ({e})")
            errors += 1

    print(f"\nDone: {migrated} migrated, {skipped} skipped, {errors} errors")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
