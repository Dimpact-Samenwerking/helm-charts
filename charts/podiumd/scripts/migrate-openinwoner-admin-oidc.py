#!/usr/bin/env python3
"""
Migrate gemeente values files to the providers schema of Open Inwoner's admin
OIDC setup-configuration.

Since Open Inwoner 2.4.0 (PodiumD 4.8.4), mozilla-django-oidc-db 2.x requires
oidc_db_config_admin_auth to list the OIDC provider separately and every item
to name it in oidc_provider_identifier. An item in the old flat shape (with
endpoint_config, claim_mapping, username_claim, groups_claim, sync_groups,
make_users_staff, ... directly in the item) fails validation:

  oidc_db_config_admin_auth.items.0.oidc_provider_identifier
    String should match pattern '^[-a-zA-Z0-9_]+\\z' [type=string_pattern_mismatch, input_value='']

Up to PodiumD 4.9.x the openinwoner-config Job then fails on its own. From
PodiumD 4.10.0 (openinwoner chart 2.6.0) that Job is a post-install/post-upgrade
Helm hook, so the whole helm upgrade fails. See
docs/_UPGRADE_PATHS/4.9.5-to-4.10.0-values-deltas.md, "Admin OIDC login: the
providers schema".

For every flat item in openinwoner.configuration.data, this script:

  - adds a provider with the item's endpoint_config (and
    oidc_token_use_basic_auth, oidc_use_nonce, oidc_nonce_size,
    oidc_state_size, when the item sets them), named after the item's
    oidc_provider_identifier when it already sets one, else
    "<item identifier>-provider"; nothing is added when that provider is
    already listed;
  - sets the item's oidc_provider_identifier to that provider;
  - moves username_claim and claim_mapping to options.user_settings.claim_mappings,
    and groups_claim, sync_groups, sync_groups_glob_pattern, make_users_staff,
    superuser_group_names and default_groups to options.groups_settings, with
    mozilla-django-oidc-db's defaults for the ones the item leaves out (so the
    result means what the flat item meant).

The provider identifier and the options are what mozilla-django-oidc-db's own
fallback for the flat shape would create, except that the options use
groups_settings, the key its admin plugin reads.

Input files:
  - a gemeente podiumd.yml (openinwoner.configuration.data is a block scalar
    holding the setup-configuration YAML);
  - a setup-configuration data file whose top level holds
    oidc_db_config_admin_auth (e.g. podiumd-infra's
    values/layer0/openinwoner.configuration.data.yml).

Only the oidc_db_config_admin_auth block changes; the rest of the file keeps
its lines, comments and REP_..._REP placeholders. Moved values keep their
quoting. Before writing, the script checks that the edited file parses to
exactly the old values with only that block migrated; it refuses to write a
file that does not. Running it again on a migrated file changes nothing.

Requires: ruamel.yaml (pip install ruamel.yaml)

Usage:
    # Migrate all podiumd.yml files under a gemeenten directory
    python3 scripts/migrate-openinwoner-admin-oidc.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten

    # Preview (unified diff, nothing written)
    python3 scripts/migrate-openinwoner-admin-oidc.py --dry-run path/to/podiumd.yml ...

    # Exit 1 when a file still needs migrating (for a pipeline check)
    python3 scripts/migrate-openinwoner-admin-oidc.py --check --gemeenten-dir <dir>
"""

from __future__ import annotations

import argparse
import copy
import difflib
import glob
import io
import os
import sys

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap
    from ruamel.yaml.comments import CommentedSeq
except ImportError:
    print("ERROR: ruamel.yaml is required. Install with: pip install ruamel.yaml", file=sys.stderr)
    sys.exit(1)

KEY = "oidc_db_config_admin_auth"
PROVIDER_KEYS = ("oidc_token_use_basic_auth", "oidc_use_nonce", "oidc_nonce_size", "oidc_state_size")
# mozilla-django-oidc-db 2.0.1, AdminOIDCConfigurationModelItem: the deprecated fields and their defaults.
USER_DEFAULTS = {
    "username_claim": ["sub"],
    "claim_mapping": {"email": ["email"], "first_name": ["given_name"], "last_name": ["family_name"]},
}
GROUP_FIELDS = (  # (flat field, options.groups_settings key, default)
    ("groups_claim", "claim_mapping", ["roles"]),
    ("sync_groups", "sync", True),
    ("sync_groups_glob_pattern", "sync_pattern", "*"),
    ("make_users_staff", "make_users_staff", False),
    ("superuser_group_names", "superuser_group_names", []),
    ("default_groups", "default_groups", []),
)
FLAT_KEYS = ("endpoint_config", *PROVIDER_KEYS, *USER_DEFAULTS, *(f for f, _, _ in GROUP_FIELDS))


class MigrationError(Exception):
    """The file cannot be migrated automatically."""


def _rt_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    return y


def _safe_load(text: str):
    return YAML(typ="safe", pure=True).load(text)


def is_flat(item) -> bool:
    """An item that still sets one of the deprecated flat fields."""
    return isinstance(item, dict) and any(k in item for k in FLAT_KEYS)


def _move_options(item) -> None:
    """Replace the flat user and group fields of `item` with options, as mozilla-django-oidc-db means them."""
    option_fields = (*USER_DEFAULTS, *(f for f, _, _ in GROUP_FIELDS))
    if not any(k in item for k in option_fields):
        return
    if "options" in item:
        raise MigrationError(f"item {item['identifier']} has both the flat fields and options; migrate it by hand")
    claims = CommentedMap(username=item.pop("username_claim", USER_DEFAULTS["username_claim"]))
    for name, value in item.pop("claim_mapping", USER_DEFAULTS["claim_mapping"]).items():
        if name == "username" and value != claims["username"]:
            raise MigrationError(
                f"item {item['identifier']}: both username_claim and claim_mapping.username are set; migrate it by hand"
            )
        claims[name] = value
    groups = CommentedMap((key, item.pop(field, default)) for field, key, default in GROUP_FIELDS)
    item["options"] = CommentedMap(user_settings=CommentedMap(claim_mappings=claims), groups_settings=groups)


def migrate_block(block) -> tuple[object, list[str]]:
    """(migrated copy of an oidc_db_config_admin_auth mapping, notes). Works on plain and round-trip data.

    An item that already names a provider (oidc_provider_identifier) but still has
    the flat fields gets that provider in `providers`, unless it is already there.
    """
    new = copy.deepcopy(block)
    items = new.get("items") or []
    providers = new.get("providers")
    notes = []
    for item in items:
        if not is_flat(item):
            continue
        if not item.get("identifier"):
            raise MigrationError("an oidc_db_config_admin_auth item has no identifier; fix it by hand")
        ident = item.get("oidc_provider_identifier") or f"{item['identifier']}-provider"
        existing = next((p for p in providers or [] if isinstance(p, dict) and p.get("identifier") == ident), None)
        endpoint_config = item.pop("endpoint_config", None)
        provider_fields = [(k, item.pop(k)) for k in PROVIDER_KEYS if k in item]
        if existing is None:
            if endpoint_config is None:
                raise MigrationError(
                    f"item {item['identifier']}: no endpoint_config for provider {ident}; add it by hand"
                )
            provider = CommentedMap(identifier=ident, endpoint_config=endpoint_config)
            for k, v in provider_fields:
                provider[k] = v
            if providers is None:
                providers = CommentedSeq()
            providers.append(provider)
            notes.append(f"{item['identifier']}: provider {ident} added")
        elif (endpoint_config is not None and endpoint_config != existing.get("endpoint_config")) or any(
            existing.get(k) != v for k, v in provider_fields
        ):
            raise MigrationError(
                f"item {item['identifier']}: provider {ident} exists with other settings; merge by hand"
            )
        _move_options(item)
        item["oidc_provider_identifier"] = ident
        notes.append(f"{item['identifier']}: flat fields moved to options")
    if providers is not None and "providers" not in new:
        # providers first, as in the documented example
        reordered = CommentedMap(providers=providers)
        for k, v in new.items():
            reordered[k] = v
        new = reordered
    elif providers is not None:  # an explicit "providers:" (null) or an existing list
        new["providers"] = providers
    return new, notes


def _plain(node):
    """Round-trip data as plain Python (for comparing)."""
    return _safe_load(_dump(node, 0, 2))


def _dump(node, indent: int, seq_offset: int) -> str:
    y = _rt_yaml()
    y.indent(mapping=2, sequence=seq_offset + 2, offset=seq_offset)
    y.width = 4096
    buf = io.StringIO()
    y.dump(node, buf)
    return "".join(" " * indent + ln if ln.strip() else ln for ln in buf.getvalue().splitlines(True))


def _value_end(lines: list[str], start: int, end: int) -> int:
    """End of a key's value: following lines indented deeper (or blank)."""
    col = len(lines[start]) - len(lines[start].lstrip(" "))
    j = start + 1
    while j < end and (not lines[j].strip() or (len(lines[j]) - len(lines[j].lstrip(" "))) > col):
        j += 1
    while j > start + 1 and not lines[j - 1].strip():  # trailing blank lines belong to what follows
        j -= 1
    return j


def _seq_offset(block_rt, key_col: int) -> int:
    """How far this file indents "- " under its key, from the block's items list."""
    items = block_rt.get("items")
    if isinstance(items, CommentedSeq) and items:
        return max(0, items.lc.item(0)[1] - 2 - (key_col + 2))
    return 2


def migrate_text(text: str) -> tuple[str, list[str]]:
    """Return (new text, notes). Raises MigrationError when the file cannot be migrated safely."""
    doc = _safe_load(text)
    if not isinstance(doc, dict):
        raise MigrationError("not a YAML mapping")
    if isinstance(doc.get(KEY), dict):  # a setup-configuration data file
        return _migrate_data_file(text, doc)
    oip = doc.get("openinwoner")
    data = ((oip or {}).get("configuration") or {}).get("data") if isinstance(oip, dict) else None
    if not data:
        return text, ["no openinwoner.configuration.data"]
    if not isinstance(data, str):
        raise MigrationError("openinwoner.configuration.data is not a block scalar string")
    inner = _safe_load(data)
    if not isinstance(inner, dict) or not isinstance(inner.get(KEY), dict):
        return text, []
    if not any(is_flat(i) for i in inner[KEY].get("items") or []):
        return text, []

    lines = text.splitlines(keepends=True)
    rt = _rt_yaml().load(text)
    data_line = rt["openinwoner"]["configuration"].lc.key("data")[0]
    if not lines[data_line].split(" #", 1)[0].rstrip().endswith(("|", "|-", "|+")):
        raise MigrationError(f"line {data_line + 1}: openinwoner.configuration.data is not a literal block (|)")
    start = data_line + 1
    inner_rt = _rt_yaml().load(data)
    key_line, key_col = inner_rt.lc.key(KEY)
    block_indent = len(lines[start]) - len(lines[start].lstrip(" "))
    abs_key = start + key_line
    end = _value_end(lines, abs_key, len(lines))
    migrated, notes = migrate_block(inner_rt[KEY])
    body = _dump(CommentedMap([(KEY, migrated)]), block_indent + key_col, _seq_offset(inner_rt[KEY], key_col))
    new = "".join(lines[:abs_key]) + body + "".join(lines[end:])

    expected = copy.deepcopy(doc)
    expected_inner = copy.deepcopy(inner)
    expected_inner[KEY] = _plain(migrate_block(inner[KEY])[0])
    expected["openinwoner"]["configuration"]["data"] = expected_inner
    got = _safe_load(new)
    got["openinwoner"]["configuration"]["data"] = _safe_load(got["openinwoner"]["configuration"]["data"])
    if got != expected:
        raise MigrationError("edited file does not parse to the intended values; not written")
    return new, notes


def _migrate_data_file(text: str, doc: dict) -> tuple[str, list[str]]:
    """migrate_text for a file whose top level holds oidc_db_config_admin_auth."""
    if not any(is_flat(i) for i in doc[KEY].get("items") or []):
        return text, []
    lines = text.splitlines(keepends=True)
    rt = _rt_yaml().load(text)
    key_line, key_col = rt.lc.key(KEY)
    end = _value_end(lines, key_line, len(lines))
    migrated, notes = migrate_block(rt[KEY])
    body = _dump(CommentedMap([(KEY, migrated)]), key_col, _seq_offset(rt[KEY], key_col))
    new = "".join(lines[:key_line]) + body + "".join(lines[end:])
    expected = copy.deepcopy(doc)
    expected[KEY] = _plain(migrate_block(doc[KEY])[0])
    if _safe_load(new) != expected:
        raise MigrationError("edited file does not parse to the intended values; not written")
    return new, notes


def _diff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def process(path: str, args) -> tuple[str, list[str]]:
    # Universal newlines read CRLF as LF; a migrated file is written with LF only, on every OS.
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate_text(text)
    except MigrationError as e:
        return "error", [str(e)]
    except Exception as e:  # unexpected file shape: report, never write half a migration
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        problem = getattr(e, "problem", None) or str(e).splitlines()[0]
        return "error", [f"unexpected {type(e).__name__}{where}: {problem[:200]}"]
    if new == text:
        return "unchanged", notes
    if args.dry_run:
        sys.stdout.write(_diff(path, text, new))
    elif not args.check:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    return ("needs migration" if args.check else "migrated"), notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="podiumd.yml or data files (default: all under --gemeenten-dir)")
    parser.add_argument(
        "--gemeenten-dir", help="directory with <gemeente>/<env>/podiumd.yml (used when no files are given)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 when a file needs migrating")
    args = parser.parse_args()

    if not args.files and not args.gemeenten_dir:
        parser.error("give files or --gemeenten-dir")
    files = args.files or sorted(
        glob.glob(os.path.join(os.path.expanduser(args.gemeenten_dir), "*", "*", "podiumd.yml"))
    )
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
    return 1 if counts["error"] or counts["needs migration"] else 0


if __name__ == "__main__":
    sys.exit(main())
