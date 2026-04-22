#!/usr/bin/env python3
"""
Migrate podiumd environment values files from inline REP_..._REP tokens (and/or
${var} shell-style references) inside configuration.data to the
`value_from: {env: var_name}` pattern natively supported by
django-setup-configuration >= 0.11.0.

Why: django-setup-configuration does NOT substitute ${VAR} at runtime. It only
resolves env vars via `value_from: {env: VAR}`. Storing literal `${var}` leaves
the placeholder string in the database and breaks OIDC login (401
unauthorized_client). See charts/podiumd/docs/upgrade-from-4.6.4-to-4.6.5.md.

Before (live env-file pattern):
  openzaak:
    configuration:
      data: |
        oidc_rp_client_secret: REP_OPENZAAK_OIDC_SECRET_REP
        secret: REP_OPENZAAK_CREDENTIALS_ZAC_SECRET_REP
        header_value: Token REP_OBJECTTYPEN_CREDENTIALS_OBJECTEN_TOKEN_REP

Before (partially-migrated ${var} pattern — still broken at runtime):
  openzaak:
    configuration:
      secrets:
        openzaak_oidc_secret: "REP_OPENZAAK_OIDC_SECRET_REP"
      data: |
        oidc_rp_client_secret: ${openzaak_oidc_secret}

After (works with django-setup-configuration 0.11.0):
  openzaak:
    configuration:
      secrets:
        openzaak_oidc_secret: "REP_OPENZAAK_OIDC_SECRET_REP"
        openzaak_credentials_zac_secret: "REP_OPENZAAK_CREDENTIALS_ZAC_SECRET_REP"
        objecttypen_credentials_objecten_token: "REP_OBJECTTYPEN_CREDENTIALS_OBJECTEN_TOKEN_REP"
      data: |
        oidc_rp_client_secret: {value_from: {env: openzaak_oidc_secret}}
        secret: {value_from: {env: openzaak_credentials_zac_secret}}
        header_value: Token {value_from: {env: objecttypen_credentials_objecten_token}}

Note: `Token {value_from: ...}` is not a valid django-setup-configuration
construct for a prefixed token header (the string "Token " is concatenated with
a dict). When the header-value carries a literal prefix, keep the prefix in the
configuration and substitute only the token value. The generated placement
therefore emits a warning; fix by rewriting the Authorization header as a
scalar `value_from` reference after the migration, or use a helper that joins.

Usage:
  pip install ruamel.yaml
  python migrate-configuration-secrets.py <path-to-podiumd.yml> [--dry-run]

The script writes the modified file in-place (or prints to stdout with --dry-run).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import LiteralScalarString
except ImportError:
    print("ERROR: ruamel.yaml is required. Install with: pip install ruamel.yaml", file=sys.stderr)
    sys.exit(1)

REP_PATTERN = re.compile(r"REP_([A-Z0-9_]+)_REP")
DOLLAR_VAR_PATTERN = re.compile(r"\$\{([a-z][a-z0-9_]*)\}")


def rep_to_var(rep_token: str) -> str:
    """REP_FOO_BAR_SECRET_REP -> foo_bar_secret"""
    m = REP_PATTERN.match(rep_token)
    if not m:
        raise ValueError(f"Not a REP token: {rep_token!r}")
    return m.group(1).lower()


def _value_from_inline(var: str) -> str:
    return "{value_from: {env: " + var + "}}"


def migrate_data_string(data_str: str, secrets: dict) -> tuple[str, list[str]]:
    """
    Replace REP_..._REP tokens and ${var} references in a configuration.data
    string with inline `{value_from: {env: var}}` markers.

    For REP tokens, add the corresponding `var -> REP_TOKEN` entry to `secrets`
    so the env-values file's configuration.secrets block is auto-populated.

    For bare `${var}` references, we cannot recover the REP token, so no secrets
    entry is added — the caller must ensure configuration.secrets already has
    the variable.

    Returns (new_data_str, warnings).
    """
    warnings: list[str] = []

    def _sub_rep(match: re.Match) -> str:
        token = match.group(0)
        # Skip substitution if the token appears after a literal prefix
        # (e.g. "Token REP_..._REP"). The `value_from` form would turn the
        # header value into a mapping, which django-setup-configuration rejects.
        # Keep the inline REP_..._REP token (replaced by patch_values.py pre-render)
        # and emit a warning so the operator knows it was intentionally left alone.
        start = match.start()
        prefix = data_str[max(0, start - 10):start]
        if re.search(r"\bToken\s+$", prefix):
            warnings.append(
                f"'{token}' preceded by literal 'Token ' prefix — left inline "
                f"(pipeline-replaced). `value_from` can't be used here because "
                f"the config loader would parse it as a mapping, not a string."
            )
            return token  # keep inline REP_..._REP untouched
        var = rep_to_var(token)
        secrets[var] = token
        return _value_from_inline(var)

    def _sub_dollar(match: re.Match) -> str:
        var = match.group(1)
        return _value_from_inline(var)

    out = REP_PATTERN.sub(_sub_rep, data_str)
    out = DOLLAR_VAR_PATTERN.sub(_sub_dollar, out)
    return out, warnings


def process_component(component_cfg: dict) -> tuple[dict, list[str]]:
    """
    Given a component's configuration dict, migrate REP tokens and ${var}
    references from data to value_from inline markers.

    Returns (new_secrets_added, warnings).
    """
    data_val = component_cfg.get("data")
    if not data_val:
        return {}, []

    data_str = str(data_val)
    if not (REP_PATTERN.search(data_str) or DOLLAR_VAR_PATTERN.search(data_str)):
        return {}, []

    new_secrets: dict[str, str] = {}
    new_data, warnings = migrate_data_string(data_str, new_secrets)

    if new_data == data_str:
        return {}, warnings

    component_cfg["data"] = LiteralScalarString(new_data)

    if new_secrets:
        existing = component_cfg.get("secrets") or {}
        if not isinstance(existing, dict):
            existing = {}
        for var, token in sorted(new_secrets.items()):
            if var not in existing:
                existing[var] = token
        component_cfg["secrets"] = existing

    return new_secrets, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="Path to podiumd.yml (or other values file)")
    parser.add_argument("--dry-run", action="store_true", help="Print result to stdout instead of writing")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # prevent line wrapping

    data = yaml.load(path.read_text(encoding="utf-8"))

    all_added: dict[str, dict[str, str]] = {}
    all_warnings: dict[str, list[str]] = {}

    for component_name, component_val in (data or {}).items():
        if not isinstance(component_val, dict):
            continue
        cfg = component_val.get("configuration")
        if not isinstance(cfg, dict):
            continue
        added, warnings = process_component(cfg)
        if added:
            all_added[component_name] = added
        if warnings:
            all_warnings[component_name] = warnings

    if not all_added and not all_warnings:
        print("No REP_..._REP tokens or ${var} references found in any configuration.data block. Nothing to migrate.")
        return

    if all_added:
        print("Migrated REP tokens (added to configuration.secrets):")
        for comp, tokens in sorted(all_added.items()):
            print(f"  {comp}:")
            for var, tok in sorted(tokens.items()):
                print(f"    {var}: {tok}")

    if all_warnings:
        print("\nWarnings (review manually):")
        for comp, msgs in sorted(all_warnings.items()):
            print(f"  {comp}:")
            for m in msgs:
                print(f"    - {m}")

    if not all_added:
        # Warnings only — no actual changes to write
        print("\nNo changes written (warnings only).")
        return

    if args.dry_run:
        import io
        buf = io.StringIO()
        yaml.dump(data, buf)
        print("\n--- Migrated YAML ---")
        print(buf.getvalue())
    else:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
        print(f"\nFile written: {path}")


if __name__ == "__main__":
    main()
