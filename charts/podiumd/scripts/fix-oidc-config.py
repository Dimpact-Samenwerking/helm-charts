#!/usr/bin/env python3
"""
Migrate django-setup-configuration OIDC config in PodiumD environment values files.

Converts OIDC items from the old flat format (mozilla-django-oidc-db < ~2024)
to the new nested options format required by PodiumD 4.6+ charts.

Affected components (use new format): openzaak, opennotificaties, objecten,
objecttypen, openklant, openformulieren.

NOT affected (still use old flat format in PodiumD 4.6): openinwoner (chart
2.1.3), openarchiefbeheer (chart 1.5.3). The script automatically skips OIDC
blocks nested under these component keys — they are left untouched.

Old format (keys at item level):
  claim_mapping          (dict)  → options.user_settings.claim_mappings
  username_claim         (list)  → options.user_settings.claim_mappings.username
  groups_claim           (list)  → options.groups_settings.claim_mapping
  sync_groups            (bool)  → options.groups_settings.sync
  sync_groups_glob_pattern (str) → options.groups_settings.sync_pattern
  make_users_staff       (bool)  → options.groups_settings.make_users_staff
  superuser_group_names  (list)  → options.groups_settings.superuser_group_names

Also: item-level endpoint_config (no oidc_provider_identifier) is promoted to
a top-level providers section.

The script handles:
  - Fully old format items
  - Fully new format items (skipped / idempotent)
  - Partially migrated items (merges remaining old keys into options)
  - Mixed files with both old and new items

Only old-format OIDC keys are modified. All other fields in every item and all
other keys in the values file are left completely untouched.

It processes all string values inside the file that contain an embedded YAML
block with oidc_db_config_admin_auth (i.e. the data: | blocks used by the
configmap helm templates).

Usage:
    # Dry-run (print result, do not write):
    python fix-oidc-config.py values.yaml --dry-run

    # Migrate in-place:
    python fix-oidc-config.py values.yaml

    # Write to a new file:
    python fix-oidc-config.py values.yaml -o values-migrated.yaml

Requires: ruamel.yaml  (pip install ruamel.yaml)
Falls back to PyYAML if ruamel.yaml is unavailable (comments/style will be lost).
"""

import sys
import argparse
from io import StringIO

try:
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.scalarstring import LiteralScalarString, FoldedScalarString
    _USE_RUAMEL = True
except ImportError:
    _USE_RUAMEL = False
    try:
        import yaml as _pyyaml
    except ImportError:
        print("ERROR: Install ruamel.yaml or PyYAML: pip install ruamel.yaml", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Components that still use the OLD flat OIDC format and must NOT be migrated.
# These are excluded because their chart versions do not yet support the new
# options.user_settings / options.groups_settings nested format.
# ---------------------------------------------------------------------------

_SKIP_COMPONENTS = frozenset({
    "openinwoner",       # chart 2.1.3 — still uses old mozilla-django-oidc-db format
    "openarchiefbeheer", # chart 1.5.3 — still uses old mozilla-django-oidc-db format
})


# ---------------------------------------------------------------------------
# Old-format key sets
# ---------------------------------------------------------------------------

_OLD_USER_KEYS = frozenset({"claim_mapping", "username_claim"})
_OLD_GROUP_KEYS = frozenset({
    "groups_claim",
    "sync_groups",
    "sync_groups_glob_pattern",
    "make_users_staff",
    "superuser_group_names",
})
_ALL_OLD_KEYS = _OLD_USER_KEYS | _OLD_GROUP_KEYS


# ---------------------------------------------------------------------------
# Item-level migration
# ---------------------------------------------------------------------------

def _needs_migration(item):
    has_old_key = bool(_ALL_OLD_KEYS.intersection(item))
    has_inline_endpoint = "endpoint_config" in item and "oidc_provider_identifier" not in item
    return has_old_key or has_inline_endpoint


def _migrate_item(item, admin_auth):
    """
    Migrate a single OIDC item from old flat format to new options format.

    admin_auth is the parent oidc_db_config_admin_auth dict, modified in-place
    to add a providers section when the item uses inline endpoint_config.

    Returns True if the item was modified.
    """
    changed = False

    # ---- user settings migration ----------------------------------------
    if _OLD_USER_KEYS.intersection(item):
        options = item.setdefault("options", {})
        us = options.setdefault("user_settings", {})
        cm = us.setdefault("claim_mappings", {})

        # claim_mapping (dict) → claim_mappings
        if "claim_mapping" in item:
            for field, claim_list in item.pop("claim_mapping").items():
                cm.setdefault(field, claim_list)
            changed = True

        # username_claim (list) → claim_mappings.username
        if "username_claim" in item:
            cm.setdefault("username", item.pop("username_claim"))
            changed = True

    # ---- groups settings migration --------------------------------------
    if _OLD_GROUP_KEYS.intersection(item):
        options = item.setdefault("options", {})
        gs = options.setdefault("groups_settings", {})

        if "groups_claim" in item:
            gs.setdefault("claim_mapping", item.pop("groups_claim"))
            changed = True

        if "sync_groups" in item:
            gs.setdefault("sync", item.pop("sync_groups"))
            changed = True

        if "sync_groups_glob_pattern" in item:
            gs.setdefault("sync_pattern", item.pop("sync_groups_glob_pattern"))
            changed = True

        if "make_users_staff" in item:
            gs.setdefault("make_users_staff", item.pop("make_users_staff"))
            changed = True

        if "superuser_group_names" in item:
            gs.setdefault("superuser_group_names", item.pop("superuser_group_names"))
            changed = True

    # ---- clean up empty options that may have been created ---------------
    if "options" in item:
        opts = item["options"]
        if not opts.get("user_settings"):
            opts.pop("user_settings", None)
        if not opts.get("groups_settings"):
            opts.pop("groups_settings", None)
        if not opts:
            del item["options"]

    # ---- endpoint_config → providers section promotion ------------------
    if "endpoint_config" in item and "oidc_provider_identifier" not in item:
        provider_id = "admin-oidc-provider"
        providers = admin_auth.setdefault("providers", [])
        existing_ids = {p.get("identifier") for p in providers}
        if provider_id not in existing_ids:
            providers.insert(0, {
                "identifier": provider_id,
                "endpoint_config": item["endpoint_config"],
            })
        item["oidc_provider_identifier"] = provider_id
        del item["endpoint_config"]
        changed = True

    return changed


# ---------------------------------------------------------------------------
# Inner-YAML migration (the content of `data: |` blocks)
# ---------------------------------------------------------------------------

def _migrate_oidc_yaml_str(yaml_str):
    """
    Parse a YAML string, find oidc_db_config_admin_auth items, migrate them.
    Returns (new_yaml_str, changed).
    """
    if _USE_RUAMEL:
        ry = RuamelYAML()
        ry.preserve_quotes = True
        ry.width = 4096
        try:
            doc = ry.load(StringIO(yaml_str))
        except Exception:
            return yaml_str, False
    else:
        try:
            doc = _pyyaml.safe_load(yaml_str)
        except Exception:
            return yaml_str, False

    if not isinstance(doc, dict):
        return yaml_str, False

    admin_auth = doc.get("oidc_db_config_admin_auth")
    if not isinstance(admin_auth, dict):
        return yaml_str, False

    items = admin_auth.get("items")
    if not isinstance(items, list):
        return yaml_str, False

    changed = False
    for item in items:
        if isinstance(item, dict) and _needs_migration(item):
            changed = _migrate_item(item, admin_auth) or changed

    if not changed:
        return yaml_str, False

    if _USE_RUAMEL:
        buf = StringIO()
        ry.dump(doc, buf)
        return buf.getvalue(), True
    else:
        return _pyyaml.dump(doc, default_flow_style=False, allow_unicode=True), True


# ---------------------------------------------------------------------------
# Text-level outer-file processor
#
# Scans the file as raw text, finds literal block scalars containing
# oidc_db_config_admin_auth, migrates them, and substitutes back — without
# touching anything else in the file. This avoids ruamel re-indenting
# unrelated sections during a whole-file round-trip dump.
# ---------------------------------------------------------------------------

def _migrate_file_text(text):
    """
    Process the outer values file as text.

    For each YAML literal block scalar that contains oidc_db_config_admin_auth:
      - Determines the owning top-level component key.
      - Skips the block if that component is in _SKIP_COMPONENTS.
      - Otherwise parses, migrates, and substitutes the block back in-place.

    All other content — including indentation, comments, trailing whitespace,
    and duplicate keys — is left completely untouched.

    Returns (new_text, changed).
    """
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    changed = False
    current_component = None  # top-level key currently in scope

    while i < len(lines):
        raw = lines[i]
        stripped = raw.rstrip("\r\n")

        # Track top-level component key: line at column 0 containing a colon,
        # not starting with whitespace or a comment.
        if stripped and stripped[0].isalpha() and ":" in stripped:
            current_component = stripped.split(":")[0].strip()

        # Detect start of a YAML literal block scalar (value is | or |-)
        literal_match = _LITERAL_BLOCK_RE.match(stripped)
        if literal_match:
            block_indent_str = literal_match.group(1)
            block_indent = len(block_indent_str)

            # Collect the block body: lines more indented than the key line.
            j = i + 1
            while j < len(lines):
                body_line = lines[j].rstrip("\r\n")
                if body_line == "" or body_line.strip() == "":
                    # Blank lines are part of the block
                    j += 1
                    continue
                body_indent = len(body_line) - len(body_line.lstrip())
                if body_indent <= block_indent:
                    break
                j += 1

            block_lines = lines[i + 1:j]
            block_body = "".join(block_lines)

            # Only process blocks containing an OIDC config section.
            if "oidc_db_config_admin_auth" in block_body:
                if current_component in _SKIP_COMPONENTS:
                    # Skip-component: emit as-is
                    out.append(raw)
                    out.extend(block_lines)
                    i = j
                    continue

                # Determine the base indentation of the block body.
                base_indent = None
                for bl in block_lines:
                    if bl.strip():
                        base_indent = len(bl) - len(bl.lstrip())
                        break

                if base_indent is not None:
                    # Strip base indent to get clean embedded YAML.
                    unindented = "".join(
                        bl[base_indent:] if len(bl) > base_indent else bl
                        for bl in block_lines
                    )
                    new_yaml, block_changed = _migrate_oidc_yaml_str(unindented)
                    if block_changed:
                        indent_prefix = " " * base_indent
                        new_block_lines = []
                        for ml in new_yaml.splitlines(keepends=True):
                            if ml.strip():
                                new_block_lines.append(indent_prefix + ml)
                            else:
                                new_block_lines.append(ml)
                        out.append(raw)
                        out.extend(new_block_lines)
                        changed = True
                        i = j
                        continue

        out.append(raw)
        i += 1

    return "".join(out), changed


# Matches the start of a YAML literal block scalar: key: | or key: |-
import re as _re
_LITERAL_BLOCK_RE = _re.compile(r"^(\s*)\S.*:\s*\|[-+]?\s*$")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(text, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Migrate django-setup-configuration OIDC config to the new "
            "options.user_settings / options.groups_settings format (PodiumD 4.6+)"
        )
    )
    parser.add_argument("input", help="Input values YAML file")
    parser.add_argument(
        "-o", "--output", metavar="FILE",
        help="Write output to FILE instead of overwriting the input file",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the migrated YAML to stdout without writing any file",
    )
    args = parser.parse_args()

    text = _read(args.input)
    new_text, changed = _migrate_file_text(text)

    if not changed:
        print("No OIDC items needed migration — file is already up-to-date.", file=sys.stderr)
        sys.exit(0)

    if args.dry_run:
        sys.stdout.write(new_text)
    else:
        output_path = args.output or args.input
        _write(new_text, output_path)
        print(f"Migration complete → {output_path}")


if __name__ == "__main__":
    main()
