#!/usr/bin/env python3
"""
Migrate openarchiefbeheer OIDC configuration in podiumd.yml files
from mozilla-django-oidc-db v1.x to v1.1.1 format (required for Open Archiefbeheer 2.0.0).

The OIDC configuration structure in configuration.data changes as follows:
- The endpoint_config moves from each item into a separate top-level providers list.
- Claim mappings (username_claim, groups_claim, superuser_group_names, make_users_staff)
  are restructured into an options block.
- Deprecated fields (claim_mapping, userinfo_claims_source, oidc_rp_scopes_list,
  sync_groups) are removed.

Requires: yq v4 (https://github.com/mikefarah/yq) — install with: brew install yq

Usage:
    # Migrate all podiumd.yml files in the default gemeenten directory
    python3 scripts/migrate-openarchiefbeheer-2.0.0.py

    # Preview changes without modifying files
    python3 scripts/migrate-openarchiefbeheer-2.0.0.py --dry-run

    # Migrate specific files
    python3 scripts/migrate-openarchiefbeheer-2.0.0.py path/to/podiumd.yml ...
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile

GEMEENTEN_DIR = os.path.expanduser(
    "~/projects/dimpact/ssctwente/Applications/applications/gemeenten"
)

DEPRECATED_ITEM_FIELDS = [
    "endpoint_config",
    "username_claim",
    "groups_claim",
    "superuser_group_names",
    "make_users_staff",
    "sync_groups",
    "sync_groups_glob_pattern",
    "default_groups",
    "claim_mapping",
    "userinfo_claims_source",
    "oidc_rp_scopes_list",
]


def yq_get(expr, file):
    r = subprocess.run(["yq", expr, file], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def yq_set(expr, file):
    subprocess.run(["yq", "-i", expr, file], capture_output=True, check=True)


def yq_set_env(expr, file, env_vars):
    env = os.environ.copy()
    env.update(env_vars)
    subprocess.run(["yq", "-i", expr, file], env=env, check=True)


def check_yq():
    try:
        r = subprocess.run(["yq", "--version"], capture_output=True, text=True, check=True)
        if "mikefarah" not in r.stdout and "github.com/mikefarah" not in r.stdout:
            print("Warning: yq found but may not be mikefarah/yq v4. Output:", r.stdout.strip())
    except FileNotFoundError:
        print("Error: yq not found. Install with: brew install yq")
        sys.exit(1)


def is_already_migrated(data_file):
    result = yq_get('.oidc_db_config_admin_auth | has("providers")', data_file)
    return result == "true"


def has_old_oidc_config(data_file):
    result = yq_get('.oidc_db_config_admin_auth | has("items")', data_file)
    return result == "true"


def transform_data_file(data_file):
    """Transform the OIDC section of a configuration.data temp file in-place."""

    if is_already_migrated(data_file):
        return False, "already in new format (providers key present)"

    if not has_old_oidc_config(data_file):
        return False, "no oidc_db_config_admin_auth.items found"

    # Add new item fields first so they appear before options in the output
    yq_set(
        '.oidc_db_config_admin_auth.items[0].oidc_provider_identifier = "admin-oidc-provider"',
        data_file,
    )
    yq_set(".oidc_db_config_admin_auth.items[0].oidc_use_pkce = false", data_file)

    # Build options from old claim fields (must happen before deletes)
    yq_set(
        ".oidc_db_config_admin_auth.items[0].options = {"
        '"user_settings": {'
        '"claim_mappings": {"username": .oidc_db_config_admin_auth.items[0].username_claim},'
        '"username_case_sensitive": false},'
        '"groups_settings": {'
        '"superuser_group_names": .oidc_db_config_admin_auth.items[0].superuser_group_names,'
        '"claim_mapping": .oidc_db_config_admin_auth.items[0].groups_claim,'
        '"make_users_staff": .oidc_db_config_admin_auth.items[0].make_users_staff}}',
        data_file,
    )

    # Add providers list — endpoint_config moves here from the item (still present at this point)
    yq_set(
        ".oidc_db_config_admin_auth.providers = ["
        '{"identifier": "admin-oidc-provider",'
        " \"endpoint_config\": .oidc_db_config_admin_auth.items[0].endpoint_config,"
        ' "oidc_token_use_basic_auth": false}]',
        data_file,
    )

    # Remove deprecated fields from the item
    for field in DEPRECATED_ITEM_FIELDS:
        yq_set(f"del(.oidc_db_config_admin_auth.items[0].{field})", data_file)

    # Reorder so providers appears before items
    yq_set(
        '.oidc_db_config_admin_auth |= {"providers": .providers, "items": .items}',
        data_file,
    )

    return True, "migrated"


def process_file(podiumd_yml, dry_run):
    """Process a single podiumd.yml. Returns (changed, reason)."""

    oab_section = yq_get(".openarchiefbeheer", podiumd_yml)
    if oab_section in ("null", "~", ""):
        return False, "no openarchiefbeheer section"

    data_raw = yq_get(".openarchiefbeheer.configuration.data", podiumd_yml)
    if not data_raw or data_raw in ("null", "~", '""', ""):
        return False, "configuration.data is empty"

    if "oidc_db_config_admin_auth" not in data_raw:
        return False, "no oidc_db_config_admin_auth in configuration.data"

    if dry_run:
        # Check the data in a temp file without writing back
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
            tf.write(data_raw)
            temp_path = tf.name
        try:
            if is_already_migrated(temp_path):
                return False, "already in new format"
            if not has_old_oidc_config(temp_path):
                return False, "no oidc_db_config_admin_auth.items found"
            return True, "would migrate (dry-run)"
        finally:
            os.unlink(temp_path)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write(data_raw)
        temp_path = tf.name

    try:
        changed, reason = transform_data_file(temp_path)

        if changed:
            with open(temp_path) as f:
                new_data = f.read().rstrip("\n")
            yq_set_env(
                ".openarchiefbeheer.configuration.data = strenv(NEW_DATA)",
                podiumd_yml,
                {"NEW_DATA": new_data},
            )

        return changed, reason
    finally:
        os.unlink(temp_path)


def find_podiumd_files():
    pattern = os.path.join(os.path.expanduser(GEMEENTEN_DIR), "*", "*", "podiumd.yml")
    return sorted(glob.glob(pattern))


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
        help="Specific podiumd.yml files to process (default: all files in gemeenten dir)",
    )
    args = parser.parse_args()

    check_yq()

    files = args.files if args.files else find_podiumd_files()
    if not files:
        print(f"No podiumd.yml files found in {GEMEENTEN_DIR}")
        sys.exit(1)

    if args.dry_run:
        print("Dry run — no files will be modified.\n")

    migrated = skipped = errors = 0

    for f in files:
        rel = os.path.relpath(f, os.path.expanduser(GEMEENTEN_DIR))
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
