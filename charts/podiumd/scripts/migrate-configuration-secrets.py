#!/usr/bin/env python3
"""
Migrate podiumd environment values files from inline REP_..._REP tokens in
configuration.data blocks to configuration.secrets + ${var_name} substitution.

Before (live env file pattern):
  openzaak:
    configuration:
      data: |
        oidc_rp_client_secret: REP_OPENZAAK_OIDC_SECRET_REP
        secret: REP_OPENZAAK_CREDENTIALS_ZAC_SECRET_REP
        header_value: Token REP_OBJECTTYPEN_CREDENTIALS_OBJECTEN_TOKEN_REP

After:
  openzaak:
    configuration:
      secrets:
        openzaak_oidc_secret: "REP_OPENZAAK_OIDC_SECRET_REP"
        openzaak_credentials_zac_secret: "REP_OPENZAAK_CREDENTIALS_ZAC_SECRET_REP"
        objecttypen_credentials_objecten_token: "REP_OBJECTTYPEN_CREDENTIALS_OBJECTEN_TOKEN_REP"
      data: |
        oidc_rp_client_secret: ${openzaak_oidc_secret}
        secret: ${openzaak_credentials_zac_secret}
        header_value: Token ${objecttypen_credentials_objecten_token}

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


def rep_to_var(rep_token: str) -> str:
    """REP_FOO_BAR_SECRET_REP -> foo_bar_secret"""
    m = REP_PATTERN.match(rep_token)
    if not m:
        raise ValueError(f"Not a REP token: {rep_token!r}")
    return m.group(1).lower()


def migrate_data_string(data_str: str, secrets: dict) -> str:
    """
    Replace all REP_..._REP tokens in a configuration.data string with ${var_name}.
    Collects the mapping in `secrets` dict: {var_name: REP_TOKEN}.
    Handles both bare tokens and tokens preceded by 'Token ' (api_key header values).
    """
    def _sub(match: re.Match) -> str:
        token = match.group(0)
        var = rep_to_var(token)
        secrets[var] = token
        return "${" + var + "}"

    return REP_PATTERN.sub(_sub, data_str)


def process_component(component_cfg: dict) -> dict:
    """
    Given a component's configuration dict, migrate REP tokens from data to secrets.
    Returns a dict of {var_name: REP_TOKEN} tokens found (may be empty).
    """
    data_val = component_cfg.get("data")
    if not data_val:
        return {}

    data_str = str(data_val)
    if not REP_PATTERN.search(data_str):
        return {}

    new_secrets: dict[str, str] = {}
    new_data = migrate_data_string(data_str, new_secrets)

    if not new_secrets:
        return {}

    # Update the data field
    component_cfg["data"] = LiteralScalarString(new_data)

    # Merge into existing secrets (create if absent)
    existing = component_cfg.get("secrets") or {}
    if not isinstance(existing, dict):
        existing = {}
    for var, token in sorted(new_secrets.items()):
        if var not in existing:
            existing[var] = token
    component_cfg["secrets"] = existing

    return new_secrets


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

    all_found: dict[str, dict[str, str]] = {}

    # Walk top-level keys looking for components with configuration.data
    for component_name, component_val in (data or {}).items():
        if not isinstance(component_val, dict):
            continue
        cfg = component_val.get("configuration")
        if not isinstance(cfg, dict):
            continue
        found = process_component(cfg)
        if found:
            all_found[component_name] = found

    if not all_found:
        print("No REP_..._REP tokens found in any configuration.data block. Nothing to migrate.")
        return

    print("Migrated tokens:")
    for comp, tokens in sorted(all_found.items()):
        print(f"  {comp}:")
        for var, tok in sorted(tokens.items()):
            print(f"    {var}: {tok}")

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
