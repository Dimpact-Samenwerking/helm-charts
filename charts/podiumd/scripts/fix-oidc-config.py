#!/usr/bin/env python3
"""
Migrate django-setup-configuration OIDC config in PodiumD environment values files.

Converts OIDC items from the old flat format (mozilla-django-oidc-db < ~2024)
to the new nested options format required by PodiumD 4.6+ charts.

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
# Outer-file walker: finds embedded YAML strings and migrates them
# ---------------------------------------------------------------------------

def _walk_and_migrate(node):
    """
    Recursively walk a loaded YAML document.
    For any string value containing an embedded oidc_db_config_admin_auth block,
    parse and migrate it in-place.
    Returns True if anything was changed.
    """
    changed = False

    if isinstance(node, dict):
        for key in list(node):
            val = node[key]
            if isinstance(val, str) and "oidc_db_config_admin_auth" in val:
                new_val, c = _migrate_oidc_yaml_str(val)
                if c:
                    if _USE_RUAMEL and isinstance(val, (LiteralScalarString, FoldedScalarString)):
                        node[key] = LiteralScalarString(new_val)
                    else:
                        node[key] = new_val
                    changed = True
            else:
                changed = _walk_and_migrate(val) or changed

    elif isinstance(node, list):
        for item in node:
            changed = _walk_and_migrate(item) or changed

    return changed


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load(path):
    if _USE_RUAMEL:
        ry = RuamelYAML()
        ry.preserve_quotes = True
        ry.width = 4096
        with open(path, "r", encoding="utf-8") as f:
            return ry, ry.load(f)
    else:
        with open(path, "r", encoding="utf-8") as f:
            return None, _pyyaml.safe_load(f)


def _dump(ry, data, path=None):
    if _USE_RUAMEL:
        buf = StringIO()
        ry.dump(data, buf)
        text = buf.getvalue()
    else:
        text = _pyyaml.dump(data, default_flow_style=False, allow_unicode=True)

    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


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

    ry, data = _load(args.input)

    changed = _walk_and_migrate(data)

    if not changed:
        print("No OIDC items needed migration — file is already up-to-date.", file=sys.stderr)
        sys.exit(0)

    if args.dry_run:
        _dump(ry, data, path=None)
    else:
        output_path = args.output or args.input
        _dump(ry, data, path=output_path)
        print(f"Migration complete → {output_path}")
        if not _USE_RUAMEL:
            print("Tip: install ruamel.yaml to preserve comments: pip install ruamel.yaml")


if __name__ == "__main__":
    main()
