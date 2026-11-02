#!/usr/bin/env python3
"""
Migrate gemeente values files for the Objecten 4 merge (Open Object 4.1.0).

PodiumD replaces the separate `objecten` (objects-api) and `objecttypen`
(objecttypes-api) charts with one `openobject` chart, aliased as `objecten`
(see docs/apps/objecten/openobject-migration.md). The Objecttypen API is now
served by Objecten itself. This script rewrites a gemeente `podiumd.yml` for
that change:

  objecten / objecttypen
  - Remove the whole `objecttypen:` block.
  - objecten.settings.siteDomain: the objecten domain from `sites_config`
    (required by the new chart; `sites_config` is gone in Open Object 4).
  - objecten.settings.allowedHosts: add the old public objecttypen hostname.
    It keeps working through the ingress (IN-2597) and is then served by
    objecten, so Django must accept it.
  - objecten.configuration.secrets: move objecttypen's secrets over and set
    `create_required_objecttypen_token` to the token of an existing objecten
    superuser tokenauth item (the create-required-objecttypen job needs a
    superuser token; Open Object tokens are unique, so no duplicate is added).
  - objecten.create_required_objecttypen_job: moved from objecttypen.

  objecten.configuration.data (setup-configuration)
  - objecttypes.items[].service_identifier: removed (objecttypes are local).
  - The zgw_consumers service those items pointed at: removed.
  - sites_config / sites_config_enable: removed (now settings.siteDomain).
  - tokenauth.items[].fields / use_fields: removed (gone in Open Object 4).
  - objecttypen's tokenauth items are merged in. Open Object has one token
    table for both APIs, so an identifier can have only one token:
      - same identifier and token: dropped as a duplicate;
      - same identifier, other token: the objecten token wins. The
        objecttypen item is dropped, and every consumer value that carried
        the objecttypen token gets the objecten token instead (see below);
      - identifier only in objecttypen: copied over, and reported, so you can
        check whether a client still uses it.

  Token rewrite (every string value outside objecten's own tokenauth)
  - A consumer that called the Objecttypen API with the objecttypen token of
    an identifier that also exists in objecten (zgw_consumers header_value
    `Token ...`, omc, ...) now sends the objecten token of
    that identifier. Without this it gets 403 after the upgrade. A
    `value_from: {env: ...}` token is resolved through the component's
    configuration.secrets, so its REP_..._REP placeholder is rewritten; a token
    that cannot be resolved is reported instead.

  Consumers (every string value, including embedded configuration.data)
  - The public objecttypen hostname and `objecttypen.<ns>.svc.cluster.local`
    are replaced by the objecten ones: ita.*.type, kiss objectTypeUrl's, omc endpoints, openformulieren's objecttypen-api
    service api_root, ... (only objecten.settings.allowedHosts keeps the old
    hostname, see above).
  - kiss.adapter.objecttypen is folded into kiss.adapter.objecten (its token
    is dropped: the adapter uses the objecten token).
  - mi.targets entries for component objecttypen are removed.
  - zac.objecttypenApi is removed: ZAC reads only zac.objectenApi since the
    merge, and podiumd 4.10.0 no longer has the key.

  zgw_consumers: one service per api_root (every component's configuration.data)
  - zgw_consumers allows an api_root only once. After the host rewrite a
    component's objecttypen service (Open Formulieren `objecttypen-api`, Open
    Beheer `objecttypen-service`) has the same api_root as its objecten
    service, and its config job would fail on the unique key. Per component
    and objecten api_root (compared exactly, as the database does), with one
    objecttypen service and one other service: the objecttypen service is
    removed, and every `*_service_identifier` that named it (Open Formulieren
    `objecttypes_service_identifier`, Open Beheer
    `objecttypen_service_identifier`) points at the kept service. This also
    runs on files migrated before (no objecttypen block any more).
  - Open Formulieren's kept objecten-api often sends the old objecttypen token
    (Token REP_OBJECTEN_CREDENTIALS_OBJECTTYPEN_TOKEN_REP), which no objecten
    tokenauth item has. When objecten has a tokenauth item `formulier` with
    read_and_write, that header becomes the formulier token (SWITCHED); this
    assumes the formulier token's Key Vault secret exists.
  - Open Zaak's objecten-api (api_type orc, zaakobject validation) often
    sends the same old objecttypen token. Open Zaak keeps it, and objecten
    gets a tokenauth item `openzaak` with that token (ADDED): not a
    superuser, read_only on the objecttypes of the `zaak` item (ZAC's own
    token, which Open Zaak should not share). The token is written in the
    same form as the `zaak` item's: plainly, or as `value_from` env
    objecten_credentials_openzaak_token, added to objecten.configuration.secrets.
    The secret name still says OBJECTTYPEN; no new Key Vault secret is needed,
    but its value must differ from every other objecten token (Open Object
    refuses duplicates). An `openzaak` item with another token, or no `zaak`
    item with permissions, is an ACTION. An Open Zaak objecten-api that sends
    the `zaak` token (switched by an earlier version of this script) is a
    CHECK: set it back to the old objecttypen token and run again.
  - The formulier switch also applies to a service at the objecten api_root
    that was merged before (by an earlier version of this script or by hand).
  - Any other component that still sends the old objecttypen token to the
    objecten api_root is an ACTION: no switch is defined for it.
  - After a merge, the self-check refuses the file when the removed service's
    identifier still appears as a value anywhere in that component's
    configuration.data (only `*_service_identifier` keys are repointed).
  - Otherwise, when the two services sent different tokens, the kept service's
    token is an ACTION: whether it is an objecten token with the permissions
    the component needs cannot be checked here (values-deltas.md, 'One
    zgw_consumers service per api_root'). Any other duplicate at an objecten
    api_root is an ACTION to fix by hand; duplicates at other api_roots are
    left alone.
  - A configuration.data that does not parse is reported (CHECK), not merged.

  objecten.image.repository
  - An override `<registry>/maykinmedia/objects-api` (a mirror of the old
    image), or a mirror under the legacy component name `<registry>/objecten`,
    becomes `<registry>/maykinmedia/open-object`: the name
    mirror-strip-registry.py gives the new image. That image must be mirrored
    there before deploying. Any other override is left alone and reported.
    --objecten-image-repository sets it explicitly.

  services-gateway.yml (next to podiumd.yml, skip with --no-gateway)
  - The `objecttypen-nginx` ExternalName Service is repointed to
    objecten.<ns>.svc.cluster.local, so the existing HTTPRoute for the old
    hostname reaches objecten (IN-2597). Only when podiumd.yml has an objecten
    block and (after migration) no objecttypen block: a podiumd.yml without
    objecten (an environment deployed from another repo) leaves the gateway
    alone, because its objecttypen is still running.

The file is edited in place, line by line: only the lines that change are
touched, so comments, quoting, indentation and REP_..._REP placeholders stay
as they are. The objecttypen hostnames and the rewritten tokens are replaced
everywhere in the file, comments included. Before writing, the script checks that the edited file parses to
exactly the intended values; it refuses to write a file that does not.

Exit code: 1 when a file has an error, 2 when a file needs an ACTION (listed
again after the summary), else 0.

Not done by this script (reported as reminders):
  - Per environment, before deploying: run `import_objecttypes` in the old
    objecten (3.6.x; PodiumD 4.9.x ships 3.6.2) so every objecttype exists
    locally, and run migrate-objecttypen-tokens.sh for tokens that exist only
    in the objecttypen database.
  - Clients outside these values (external parties, services configured by
    hand in an admin) that call the Objecttypen API with an objecttypen token
    must switch to the objecten token of the same identifier.
  - The token of a merged zgw_consumers service (ACTION above), and a
    configuration.data that does not parse (CHECK).

Requires: ruamel.yaml (pip install ruamel.yaml)

Usage:
    # Migrate all podiumd.yml files under a gemeenten directory
    python3 scripts/migrate-objecten-4.1.0.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten

    # Preview (unified diff, nothing written)
    python3 scripts/migrate-objecten-4.1.0.py --dry-run path/to/podiumd.yml ...

    # Also set the objecten image repository
    python3 scripts/migrate-objecten-4.1.0.py --objecten-image-repository acrprodmgmt.azurecr.io/maykinmedia/open-object path/to/podiumd.yml
"""

from __future__ import annotations

import argparse
import copy
import glob
import os
import re
import sys
from dataclasses import dataclass, field

from migrate_common import MigrationError
from migrate_common import error_note
from migrate_common import load_safe
from migrate_common import rt_yaml
from migrate_common import unified_diff
from migrate_common import write_lf
from ruamel.yaml.error import YAMLError

# A token value is only rewritten in consumers when it is long enough not to
# match by accident (REP_..._REP placeholders and real tokens both are).
MIN_REWRITE_TOKEN_LEN = 12


# --------------------------------------------------------------------------- #
# YAML helpers
# --------------------------------------------------------------------------- #

def _rt_yaml():
    # Wide lines: ruamel would otherwise re-wrap long values it dumps.
    return rt_yaml(width=4096)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _trim_trailing(lines: list[str], start: int, end: int, key_col: int) -> int:
    """Leave trailing blank lines and comments at or left of the key's column out of a block:
    they belong to whatever follows."""
    while end > start + 1 and _is_blank_or_comment(lines[end - 1]) and (
        not lines[end - 1].strip() or _indent(lines[end - 1]) <= key_col
    ):
        end -= 1
    return end


def key_range(lines: list[str], mapping, key, parent_end: int) -> tuple[int, int]:
    """[start, end) line range of `key` and its value inside a ruamel CommentedMap."""
    keys = list(mapping.keys())
    i = keys.index(key)
    start, col = mapping.lc.key(key)
    end = mapping.lc.key(keys[i + 1])[0] if i + 1 < len(keys) else parent_end
    return start, _trim_trailing(lines, start, end, col)


def item_range(lines: list[str], seq, index: int, parent_end: int) -> tuple[int, int]:
    """[start, end) line range of a sequence item (from its dash line)."""
    start, col = seq.lc.item(index)
    end = seq.lc.item(index + 1)[0] if index + 1 < len(seq) else parent_end
    return start, _trim_trailing(lines, start, end, max(col - 2, 0))


def path_range(lines: list[str], root, path: list, total: int) -> tuple[int, int]:
    node, end = root, total
    start = 0
    for key in path:
        start, end = key_range(lines, node, key, end)
        node = node[key]
    return start, end


def child_indent(lines: list[str], start: int, end: int) -> int:
    """Indentation of the first child line of the block starting at `start`."""
    for line in lines[start + 1:end]:
        if not _is_blank_or_comment(line):
            return _indent(line)
    return _indent(lines[start]) + 2


def reindent(block: list[str], delta: int) -> list[str]:
    out = []
    for line in block:
        if not line.strip():
            out.append(line)
        elif delta >= 0:
            out.append(" " * delta + line)
        else:
            out.append(line[-delta:] if line[:-delta].strip() == "" else line.lstrip())
    return out


@dataclass
class Edits:
    """Line edits on the original text, applied bottom-up so positions stay valid."""
    ops: list[tuple[int, int, list[str]]] = field(default_factory=list)

    def replace(self, start: int, end: int, new: list[str]) -> None:
        self.ops.append((start, end, new))

    def delete(self, start: int, end: int) -> None:
        self.replace(start, end, [])

    def insert(self, at: int, new: list[str]) -> None:
        self.replace(at, at, new)

    def apply(self, lines: list[str]) -> list[str]:
        out = list(lines)
        # Same position: replacements/deletions before insertions at that line.
        for start, end, new in sorted(self.ops, key=lambda o: (o[0], o[1]), reverse=True):
            out[start:end] = new
        return out


# --------------------------------------------------------------------------- #
# Host rewriting
# --------------------------------------------------------------------------- #

@dataclass
class Hosts:
    old_public: str  # acc-objecttypen.example.nl
    new_public: str  # acc-objecten.example.nl
    # objecttypen token -> objecten token of the same identifier (see token_remap)
    tokens: dict[str, str] = field(default_factory=dict)

    def rewrite(self, text: str) -> str:
        text = re.sub(rf"(?<![\w.-]){re.escape(self.old_public)}(?![\w-])", self.new_public, text)
        text = re.sub(r"(?<![\w.-])objecttypen\.([a-z0-9-]+)\.svc\.cluster\.local(?![\w-])",
                      r"objecten.\1.svc.cluster.local", text)
        for old, new in self.tokens.items():
            text = re.sub(rf"(?<![\w-]){re.escape(old)}(?![\w-])", new, text)
        return text


def _host_of(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"^\s*https?://([^/:\s]+)", str(url))
    return m.group(1) if m else None


def _public_host(component: dict) -> str | None:
    host = _host_of((component.get("configuration") or {}).get("oidcUrl"))
    if host:
        return host
    for h in str((component.get("settings") or {}).get("allowedHosts") or "").split(","):
        h = h.strip()
        if h and not h.endswith(".svc.cluster.local"):
            return h
    return None


def _rewrite_strings(node, hosts: Hosts):
    if isinstance(node, dict):
        return {k: _rewrite_strings(v, hosts) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_strings(v, hosts) for v in node]
    if isinstance(node, str):
        return hosts.rewrite(node)
    return node


# --------------------------------------------------------------------------- #
# Semantic model of the migration (the expected result, used as a check)
# --------------------------------------------------------------------------- #

def _superuser_token(items: list[dict]):
    for item in items:
        if item.get("is_superuser") is True and item.get("token") is not None:
            return item
    return None


def superuser_token_value(item: dict, secrets: dict) -> str:
    """The superuser token as a plain value: the token itself, or the
    configuration.secrets entry a `value_from: {env: <name>}` token points at."""
    token = item["token"]
    if isinstance(token, dict):
        env = ((token.get("value_from") or {}).get("env")) if isinstance(token.get("value_from"), dict) else None
        value = (secrets or {}).get(env) if env else None
        if not isinstance(value, str):
            raise MigrationError("objecten superuser token is not a plain value and its value_from env is not "
                                 "in objecten.configuration.secrets; set "
                                 "objecten.configuration.secrets.create_required_objecttypen_token by hand")
        return value
    return token


def _plain_token(token, secrets: dict):
    """A token as a string: the token itself, or the configuration.secrets
    value a `value_from: {env: <name>}` token points at (None if unknown)."""
    if isinstance(token, str):
        return token
    if isinstance(token, dict) and isinstance(token.get("value_from"), dict):
        value = (secrets or {}).get(token["value_from"].get("env"))
        return value if isinstance(value, str) else None
    return None


def token_remap(objecten_items: list[dict], objecttypen_items: list[dict],
                objecten_secrets: dict | None = None,
                objecttypen_secrets: dict | None = None) -> tuple[dict[str, str], list[str]]:
    """objecttypen token -> objecten token for identifiers in both with another token.

    Tokens given as `value_from: {env: ...}` are resolved through the
    component's configuration.secrets, so the rewrite applies to the secret
    values (REP_..._REP placeholders) that consumers use.

    Returns (rewrite map, identifiers that clash but cannot be rewritten
    automatically: a token cannot be resolved to a string, or the objecttypen
    token is also the token of another objecten item).
    """
    by_ident = {i.get("identifier"): i.get("token") for i in objecten_items}
    # Tokens of objecten's own tokenauth items: the file-wide rewrite must never
    # turn one of them into another item's token (two items, one token).
    ob_plain = {_plain_token(t, objecten_secrets or {}) for t in by_ident.values()} - {None}
    remap: dict[str, str] = {}
    manual: list[str] = []
    for item in objecttypen_items:
        ident = item.get("identifier")
        if ident not in by_ident:
            continue
        token = _plain_token(item.get("token"), objecttypen_secrets or {})
        ob_token = _plain_token(by_ident[ident], objecten_secrets or {})
        if token is not None and token == ob_token:
            continue
        if token is not None and ob_token is not None and len(token) >= MIN_REWRITE_TOKEN_LEN \
                and token not in ob_plain:
            remap[token] = ob_token
        else:
            manual.append(str(ident))
    return remap, manual


def plan_tokenauth(objecten_items: list[dict], objecttypen_items: list[dict]) -> list[dict]:
    """objecttypen tokenauth items to copy into objecten (identifier only in objecttypen)."""
    existing_ids = {i.get("identifier") for i in objecten_items}
    existing_tokens = {str(i.get("token")): i.get("identifier") for i in objecten_items}
    plan = []
    for item in objecttypen_items:
        ident, token = item.get("identifier"), str(item.get("token"))
        if ident in existing_ids:
            continue  # duplicate, or a clash where the objecten token wins
        if token in existing_tokens:
            raise MigrationError(
                f"objecttypen tokenauth item {ident!r} uses the same token as objecten item "
                f"{existing_tokens[token]!r} - tokens must be unique in Open Object; resolve by hand")
        plan.append(item)
        existing_ids.add(ident)
        existing_tokens[token] = ident
    return plan


def expected_data(objecten_data: dict, objecttypen_data: dict) -> dict:
    data = copy.deepcopy(objecten_data)
    removed_services = set()
    for item in (data.get("objecttypes") or {}).get("items") or []:
        if "service_identifier" in item:
            removed_services.add(item.pop("service_identifier"))
    zc = data.get("zgw_consumers") or {}
    if zc.get("services"):
        zc["services"] = [s for s in zc["services"] if s.get("identifier") not in removed_services]
    data.pop("sites_config", None)
    data.pop("sites_config_enable", None)
    items = (data.get("tokenauth") or {}).get("items") or []
    for item in items:
        item.pop("fields", None)
        item.pop("use_fields", None)
    for item in plan_tokenauth(items, (objecttypen_data.get("tokenauth") or {}).get("items") or []):
        moved = copy.deepcopy(item)
        moved.pop("fields", None)
        moved.pop("use_fields", None)
        items.append(moved)
    return data


def expected_values(doc: dict, hosts: Hosts, image_repo: str | None) -> dict:
    out = copy.deepcopy(doc)
    ot = out.pop("objecttypen")
    out = _rewrite_strings(out, hosts)
    ob = out["objecten"]
    od = load_safe(doc["objecten"]["configuration"]["data"]) or {}
    td = load_safe(ot["configuration"].get("data") or "") or {}
    sites = (od.get("sites_config") or {}).get("items") or []
    settings = ob.setdefault("settings", {})
    settings["siteDomain"] = sites[0]["domain"] if sites else hosts.new_public
    orig = [h.strip() for h in str(doc["objecten"]["settings"].get("allowedHosts") or "").split(",") if h.strip()]
    allowed = [h if h == hosts.old_public else hosts.rewrite(h) for h in orig]
    if hosts.old_public not in orig:
        allowed.append(hosts.old_public)
    settings["allowedHosts"] = ",".join(allowed)
    cfg = ob["configuration"]
    secrets = cfg.get("secrets") or {}
    for k, v in _rewrite_strings(ot["configuration"].get("secrets") or {}, hosts).items():
        # keycloak_client_secret differs by design: after the merge only objecten's Keycloak client is left.
        if k in secrets and secrets[k] != v and k != "keycloak_client_secret":
            raise MigrationError(f"objecten and objecttypen both define configuration.secrets.{k} with "
                                 f"different values; rename one of them by hand first")
        secrets.setdefault(k, v)
    su = _superuser_token((od.get("tokenauth") or {}).get("items") or [])
    secrets["create_required_objecttypen_token"] = superuser_token_value(
        su, (doc["objecten"]["configuration"].get("secrets") or {}))
    cfg["secrets"] = secrets
    cfg["data"] = expected_data(_rewrite_strings(od, hosts), _rewrite_strings(td, hosts))
    if "create_required_objecttypen_job" in ot and "create_required_objecttypen_job" not in doc["objecten"]:
        ob["create_required_objecttypen_job"] = _rewrite_strings(ot["create_required_objecttypen_job"], hosts)
    if image_repo:
        ob.setdefault("image", {})["repository"] = image_repo
    adapter = (out.get("kiss") or {}).get("adapter") or {}
    if "objecttypen" in adapter:
        moved = {k: v for k, v in (adapter.pop("objecttypen") or {}).items() if k != "token"}
        target = adapter.setdefault("objecten", {})
        for k, v in moved.items():
            target.setdefault(k, v)
    mi = out.get("mi") or {}
    if isinstance(mi.get("targets"), list):
        mi["targets"] = [t for t in mi["targets"] if not (isinstance(t, dict) and t.get("component") == "objecttypen")]
    if isinstance(out.get("zac"), dict):
        out["zac"].pop("objecttypenApi", None)
    return out


def normalise(doc: dict) -> dict:
    """objecten.configuration.data compared as parsed YAML, everything else as-is."""
    doc = copy.deepcopy(doc)
    cfg = ((doc.get("objecten") or {}).get("configuration") or {})
    if isinstance(cfg.get("data"), str):
        cfg["data"] = load_safe(cfg["data"]) or {}
    return doc


# --------------------------------------------------------------------------- #
# Line edits
# --------------------------------------------------------------------------- #

def _scalar_line(line: str, new_value: str) -> str:
    """Replace the scalar value on a `key: value` line, keeping the key and quote style."""
    m = re.match(r"^(\s*[^:#]+:\s*)(['\"]?)(.*?)(\2)(\s*(#.*)?)$", line)
    if not m:
        raise MigrationError(f"cannot rewrite line: {line!r}")
    return f"{m.group(1)}{m.group(2)}{new_value}{m.group(2)}{m.group(5) or ''}"


def edit_data(inner: str, objecttypen_inner: str) -> str:
    """Line edits on objecten's configuration.data text (see module docstring)."""
    lines = inner.split("\n")
    rt = _rt_yaml()
    root = rt.load(inner)
    t_lines = objecttypen_inner.split("\n")
    t_root = rt.load(objecttypen_inner) or {}
    total = len(lines)
    ed = Edits()

    removed_services = set()
    ot_items = (root.get("objecttypes") or {}).get("items") or []
    if ot_items:
        s, e = path_range(lines, root, ["objecttypes", "items"], total)
        for idx, item in enumerate(ot_items):
            if "service_identifier" in item:
                removed_services.add(str(item["service_identifier"]))
                i_s, i_e = item_range(lines, ot_items, idx, e)
                k_s, k_e = key_range(lines, item, "service_identifier", i_e)
                ed.delete(k_s, k_e)
    services = (root.get("zgw_consumers") or {}).get("services") or []
    if services:
        s, e = path_range(lines, root, ["zgw_consumers", "services"], total)
        for idx, svc in enumerate(services):
            if str(svc.get("identifier")) in removed_services:
                ed.delete(*item_range(lines, services, idx, e))
    for key in ("sites_config_enable", "sites_config"):
        if key in root:
            ed.delete(*key_range(lines, root, key, total))

    items = (root.get("tokenauth") or {}).get("items")
    if items is None:
        raise MigrationError("objecten configuration.data has no tokenauth.items")
    items_s, items_e = path_range(lines, root, ["tokenauth", "items"], total)
    for idx, item in enumerate(items):
        i_s, i_e = item_range(lines, items, idx, items_e)
        for key in ("fields", "use_fields"):
            if key in item:
                ed.delete(*key_range(lines, item, key, i_e))
    dash_col = items.lc.item(0)[1] - 2 if items else _indent(lines[items_s]) + 2

    t_items = (t_root.get("tokenauth") or {}).get("items") or []
    plain_items = load_safe(inner)["tokenauth"]["items"]
    plain_t_items = (load_safe(objecttypen_inner) or {}).get("tokenauth", {}).get("items") or []
    planned = {id(i) for i in plan_tokenauth(plain_items, plain_t_items)}
    moved: list[str] = []
    t_total = len(t_lines)
    if t_items:
        t_s, t_e = path_range(t_lines, t_root, ["tokenauth", "items"], t_total)
        for idx, item in enumerate(t_items):
            plain = plain_t_items[idx]
            if id(plain) not in planned:
                continue
            i_s, i_e = item_range(t_lines, t_items, idx, t_e)
            drop = set()
            for key in ("fields", "use_fields"):
                if key in item:
                    k_s, k_e = key_range(t_lines, item, key, i_e)
                    drop.update(range(k_s, k_e))
            block = [t_lines[n] for n in range(i_s, i_e) if n not in drop]
            src_dash = t_items.lc.item(idx)[1] - 2
            moved += reindent(block, dash_col - src_dash)
    if moved:
        ed.insert(items_e, moved)
    return "\n".join(ed.apply(lines))


def migrate_text(text: str, image_repo: str | None) -> tuple[str, list[str]]:
    """Return (new_text, notes). Raises MigrationError."""
    notes: list[str] = []
    lines = text.split("\n")
    total = len(lines)
    root = _rt_yaml().load(text)
    doc = load_safe(text)
    if not isinstance(doc, dict) or "objecttypen" not in doc:
        return text, notes
    if "objecten" not in doc:
        raise MigrationError("has an objecttypen block but no objecten block")

    old = _public_host(doc["objecttypen"])
    new = _public_host(doc["objecten"])
    if not old or not new:
        raise MigrationError("cannot determine the public objecttypen/objecten hostnames")
    hosts = Hosts(old, new)
    image_note = None
    current_repo = (doc["objecten"].get("image") or {}).get("repository")
    if not image_repo and current_repo:
        # Same mirror, new image, under the strip-registry name (see
        # mirror-strip-registry.py): <acr>/maykinmedia/objects-api, or the legacy
        # component-named <acr>/objecten, -> <acr>/maykinmedia/open-object
        m = re.match(r"^(.*/)?(?:maykinmedia/objects-api|objecten)$", str(current_repo))
        if m:
            image_repo = f"{m.group(1) or ''}maykinmedia/open-object"
            image_note = (f"objecten.image.repository {current_repo} -> {image_repo}: "
                          "mirror maykinmedia/open-object there before deploying")
    od_plain = load_safe(doc["objecten"]["configuration"].get("data") or "") or {}
    td_plain = load_safe((doc["objecttypen"].get("configuration") or {}).get("data") or "") or {}
    ob_tokens = (od_plain.get("tokenauth") or {}).get("items") or []
    ot_tokens = (td_plain.get("tokenauth") or {}).get("items") or []
    hosts.tokens, manual_clashes = token_remap(
        ob_tokens, ot_tokens,
        (doc["objecten"].get("configuration") or {}).get("secrets") or {},
        (doc["objecttypen"].get("configuration") or {}).get("secrets") or {})
    su = _superuser_token(ob_tokens)
    if not su:
        raise MigrationError("objecten tokenauth has no is_superuser item to run the "
                             "create-required-objecttypen job with; add one by hand first")
    if not isinstance(doc["objecten"].get("settings"), dict) or "allowedHosts" not in doc["objecten"]["settings"]:
        raise MigrationError("objecten.settings.allowedHosts is not set; add it (with the objecten "
                             "hostname) by hand first")

    ed = Edits()
    ob, ot = root["objecten"], root["objecttypen"]

    # objecttypen block: removed; some of its lines are moved first
    ot_s, ot_e = key_range(lines, root, "objecttypen", total)
    ed.delete(ot_s, ot_e)

    ob_s, ob_e = key_range(lines, root, "objecten", total)
    ob_child = child_indent(lines, ob_s, ob_e)

    # objecten.settings: siteDomain + allowedHosts
    st_s, st_e = key_range(lines, ob, "settings", ob_e)
    sites = (od_plain.get("sites_config") or {}).get("items") or []
    site_domain = sites[0]["domain"] if sites else new
    if "siteDomain" not in ob["settings"]:
        ed.insert(st_s + 1, [" " * child_indent(lines, st_s, st_e) + f"siteDomain: {site_domain}"])
    ah_line = ob["settings"].lc.key("allowedHosts")[0]
    allowed = [h.strip() for h in str(ob["settings"]["allowedHosts"]).split(",") if h.strip()]
    keep = "__KEEP_OLD_OBJECTTYPEN_HOST__"  # protects the old host from the hostname rewrite
    allowed = [keep if h == old else h for h in allowed] + ([] if old in allowed else [keep])
    ed.replace(ah_line, ah_line + 1, [_scalar_line(lines[ah_line], ",".join(allowed))])

    # objecten.configuration.secrets: objecttypen's secrets + the job token
    cfg = ob["configuration"]
    cf_s, cf_e = key_range(lines, ob, "configuration", ob_e)
    cf_child = child_indent(lines, cf_s, cf_e)
    secret_lines: list[str] = []
    ot_cfg = ot["configuration"]
    tc_s, tc_e = key_range(lines, ot, "configuration", ot_e)
    if ot_cfg.get("secrets"):
        o_s, o_e = key_range(lines, ot_cfg, "secrets", tc_e)
        for k in ot_cfg["secrets"]:
            if k not in (cfg.get("secrets") or {}):
                k_s, k_e = key_range(lines, ot_cfg["secrets"], k, o_e)
                secret_lines += lines[k_s:k_e]
    su_token = superuser_token_value(su, cfg.get("secrets") or {})
    token_quoted = f'"{su_token}"'
    if cfg.get("secrets"):
        se_s, se_e = key_range(lines, cfg, "secrets", cf_e)
        sec_child = child_indent(lines, se_s, se_e)
        new_secret = [" " * sec_child + f"create_required_objecttypen_token: {token_quoted}"]
        src_child = child_indent(lines, *key_range(lines, ot_cfg, "secrets", tc_e)) if secret_lines else sec_child
        ed.insert(se_e, reindent(secret_lines, sec_child - src_child) + new_secret)
    else:
        sec_child = cf_child + 2
        src_child = child_indent(lines, *key_range(lines, ot_cfg, "secrets", tc_e)) if secret_lines else sec_child
        ed.insert(cf_s + 1, [" " * cf_child + "secrets:"] + reindent(secret_lines, sec_child - src_child)
                  + [" " * sec_child + f"create_required_objecttypen_token: {token_quoted}"])

    # objecten.configuration.data
    d_s, d_e = key_range(lines, cfg, "data", cf_e)
    header = lines[d_s]
    if not re.search(r":\s*\|[-+]?\s*(#.*)?$", header):
        raise MigrationError("objecten.configuration.data is not a literal block (|)")
    content = lines[d_s + 1:d_e]
    ind = min((_indent(c) for c in content if c.strip()), default=cf_child + 2)
    inner = "\n".join(c[ind:] if c.strip() else "" for c in content)
    t_d_s, t_d_e = key_range(lines, ot_cfg, "data", tc_e)
    t_content = lines[t_d_s + 1:t_d_e]
    t_ind = min((_indent(c) for c in t_content if c.strip()), default=0)
    t_inner = "\n".join(c[t_ind:] if c.strip() else "" for c in t_content)
    new_inner = edit_data(inner, t_inner)
    ed.replace(d_s + 1, d_e, [(" " * ind + l) if l.strip() else "" for l in new_inner.split("\n")])

    # objecten.create_required_objecttypen_job: moved from objecttypen
    tail: list[str] = []
    if "create_required_objecttypen_job" in ot and "create_required_objecttypen_job" not in ob:
        j_s, j_e = key_range(lines, ot, "create_required_objecttypen_job", ot_e)
        tail += reindent(lines[j_s:j_e], ob_child - _indent(lines[j_s]))
    if image_repo:
        if "image" in ob and "repository" in ob["image"]:
            r_line = ob["image"].lc.key("repository")[0]
            ed.replace(r_line, r_line + 1, [_scalar_line(lines[r_line], image_repo)])
        elif "image" in ob:
            i_s, i_e = key_range(lines, ob, "image", ob_e)
            ed.insert(i_s + 1, [" " * child_indent(lines, i_s, i_e) + f"repository: {image_repo}"])
        else:
            tail += [" " * ob_child + "image:", " " * (ob_child + 2) + f"repository: {image_repo}"]
    if tail:
        ed.insert(ob_e, tail)

    # kiss.adapter.objecttypen -> kiss.adapter.objecten
    adapter = (root.get("kiss") or {}).get("adapter") if isinstance(root.get("kiss"), dict) else None
    if isinstance(adapter, dict) and "objecttypen" in adapter:
        k_s, k_e = key_range(lines, root, "kiss", total)
        a_s, a_e = key_range(lines, root["kiss"], "adapter", k_e)
        t_s, t_e = key_range(lines, adapter, "objecttypen", a_e)
        ed.delete(t_s, t_e)
        kot = adapter["objecttypen"] or {}
        if kot:
            if "objecten" not in adapter:
                raise MigrationError("kiss.adapter.objecttypen without kiss.adapter.objecten; merge by hand")
            o_s, o_e = key_range(lines, adapter, "objecten", a_e)
            keep = adapter["objecten"]
            block: list[str] = []
            for k in kot:
                if k == "token" or k in keep:
                    continue
                c_s, c_e = key_range(lines, kot, k, t_e)
                block += lines[c_s:c_e]
            if block:
                ed.insert(o_e, reindent(block, child_indent(lines, o_s, o_e) - child_indent(lines, t_s, t_e)))

    # mi.targets: drop objecttypen
    mi = root.get("mi")
    if isinstance(mi, dict) and isinstance(mi.get("targets"), list):
        m_s, m_e = key_range(lines, root, "mi", total)
        tg_s, tg_e = key_range(lines, mi, "targets", m_e)
        for idx, t in enumerate(mi["targets"]):
            if isinstance(t, dict) and t.get("component") == "objecttypen":
                ed.delete(*item_range(lines, mi["targets"], idx, tg_e))

    # zac.objecttypenApi: drop (ZAC reads only objectenApi)
    zac = root.get("zac")
    if isinstance(zac, dict) and "objecttypenApi" in zac:
        z_s, z_e = key_range(lines, root, "zac", total)
        ed.delete(*key_range(lines, zac, "objecttypenApi", z_e))

    out = "\n".join(ed.apply(lines))
    out = hosts.rewrite(out).replace("__KEEP_OLD_OBJECTTYPEN_HOST__", old)

    # Check: the edited file must parse to exactly the intended values
    want = normalise(expected_values(doc, hosts, image_repo))
    got = normalise(load_safe(out))
    if want != got:
        raise MigrationError("self-check failed: the edited file does not match the intended values "
                             f"({_first_difference(want, got)}); nothing written")

    ob_secrets = (doc["objecten"].get("configuration") or {}).get("secrets") or {}
    ob_by_token = {_plain_token(i.get("token"), ob_secrets): i.get("identifier") for i in ob_tokens}
    for old_token, new_token in sorted(hosts.tokens.items(), key=lambda kv: str(ob_by_token.get(kv[1]))):
        ident = ob_by_token.get(new_token)
        uses = len(re.findall(rf"(?<![\w-]){re.escape(new_token)}(?![\w-])", out)) - \
            len(re.findall(rf"(?<![\w-]){re.escape(new_token)}(?![\w-])", text))
        notes.append(f"token {ident!r}: objecten and objecttypen had different tokens; the objecten token "
                     f"wins. {uses} consumer value(s) that used the objecttypen token now use the objecten "
                     "token. Clients outside these values must switch too.")
    for ident in manual_clashes:
        notes.append(f"token {ident!r}: objecten and objecttypen have different tokens, and the objecttypen "
                     "token cannot be rewritten automatically (a token is not a plain value, or it is also the "
                     "token of another objecten item); the objecten token wins - point consumers of the "
                     "objecttypen token at it by hand")
    for item in plan_tokenauth(ob_tokens, ot_tokens):
        notes.append(f"token {item.get('identifier')!r} existed only in objecttypen and is copied; "
                     "drop it if no client uses it any more")
    own_ids = [i.get("identifier") for i in (od_plain.get("tokenauth") or {}).get("items") or []]
    dupes = sorted({i for i in own_ids if own_ids.count(i) > 1}, key=str)
    if dupes:
        notes.append(f"objecten tokenauth already lists {', '.join(map(str, dupes))} more than once "
                     "(pre-existing, left as is)")
    left = sorted(set(re.findall(r"[\w.-]*objecttypen[\w.-]*\.(?:nl|com|org|local|internal)\b", out)) - {old})
    if left:
        notes.append(f"objecttypen hostnames still present (check by hand): {', '.join(left)}")
    if image_note:
        notes.append(image_note)
    elif not image_repo and current_repo:
        notes.append(f"objecten.image.repository is overridden ({current_repo}): point it at a mirror "
                     "of maykinmedia/open-object (--objecten-image-repository)")
    notes.append(f"objecttypen host {old} -> {new}; kept in objecten.settings.allowedHosts, siteDomain {site_domain}")
    return out, notes


def _first_difference(a, b, path="") -> str:
    if type(a) is not type(b):
        return f"{path or '/'}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                return f"{path}.{k}: only in {'result' if k in b else 'expected'}"
            if a[k] != b[k]:
                return _first_difference(a[k], b[k], f"{path}.{k}")
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items expected, {len(b)} found"
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_difference(x, y, f"{path}[{i}]")
    return f"{path}: values differ"


def migrate_gateway(text: str) -> str:
    """Repoint the objecttypen-nginx ExternalName Service to objecten."""
    docs = text.split("\n---")
    out = []
    for d in docs:
        if re.search(r"(?m)^\s*name:\s*objecttypen-nginx\s*$", d) and re.search(r"(?m)^\s*type:\s*ExternalName\s*$", d):
            d = re.sub(r"(?m)^(\s*externalName:\s*['\"]?)objecttypen\.", r"\1objecten.", d)
        out.append(d)
    return "\n---".join(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

ACTION = "ACTION "
DUPLICATE_DOC = "values-deltas.md, 'One zgw_consumers service per api_root'"


def _objecten_hosts(objecten: dict) -> set[str]:
    """Hostnames objecten answers on: siteDomain, allowedHosts and the oidcUrl host."""
    settings = objecten.get("settings") or {}
    hosts = {h.strip() for h in str(settings.get("allowedHosts") or "").split(",") if h.strip()}
    for value in (settings.get("siteDomain"), _host_of((objecten.get("configuration") or {}).get("oidcUrl"))):
        if value:
            hosts.add(str(value).strip())
    return hosts


def _is_objecten_root(api_root: str, hosts: set[str]) -> bool:
    host = _host_of(api_root)
    return bool(host) and (host in hosts or re.fullmatch(r"objecten\.[a-z0-9-]+\.svc\.cluster\.local", host) is not None)


def _service_identifier_refs(node, old: str, path=()):
    """Paths of every `*_service_identifier: <old>` in a parsed configuration.data."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).endswith("_service_identifier") and value == old:
                yield path + (key,)
            else:
                yield from _service_identifier_refs(value, old, path + (key,))
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from _service_identifier_refs(value, old, path + (idx,))


def _get_path(node, path):
    for step in path:
        node = node[step]
    return node


# The old objecttypen token that Open Formulieren's and Open Zaak's objecten
# services often send: no objecten tokenauth item has it, so every call answers
# 401. Per component, the objecten identifier whose token replaces it, and the
# permission mode that item must have (None: switch anyway, report a CHECK when
# the item has no permissions).
OBJECTTYPEN_TOKEN = "REP_OBJECTEN_CREDENTIALS_OBJECTTYPEN_TOKEN_REP"
OBJECTTYPEN_TOKEN_HEADER = f"Token {OBJECTTYPEN_TOKEN}"
SWITCH_IDENTIFIER = {"openformulieren": "formulier"}
SWITCH_REQUIRED_MODE = {"openformulieren": "read_and_write"}
# Open Zaak keeps that token: objecten gets a read-only tokenauth item for it
# instead (zaak, the other candidate, is ZAC's own token). The secret name still
# says OBJECTTYPEN; no new Key Vault secret is needed.
OPENZAAK_ITEM = "openzaak"
OPENZAAK_SECRET_ENV = "objecten_credentials_openzaak_token"


def _permission_summary(item: dict) -> str:
    modes = [p.get("mode") for p in item.get("permissions") or [] if isinstance(p, dict)]
    if not modes:
        return "no permissions"
    counts = {m: modes.count(m) for m in sorted(set(modes), key=str)}
    return ", ".join(f"{n} objecttype(s) {m}" for m, n in counts.items())


def _switch_header(objecten: dict, component: str, header,
                   checks: list[str] | None = None) -> tuple[str | None, str | None]:
    """Switch `header` from the old objecttypen token to this component's objecten token.

    Returns:
      (new header_value, None): `header` is the old objecttypen token and objecten
        has a token for this component (with the required permission mode);
      (None, reason): it is the old objecttypen token, but it can't be switched;
      (None, None): nothing to switch, because `header` is not the old
        objecttypen token, the component has no switch, or the old objecttypen
        token is also the token of an objecten tokenauth item.
    A switched item without permissions adds a CHECK line to `checks`."""
    ident = SWITCH_IDENTIFIER.get(component)
    if header != OBJECTTYPEN_TOKEN_HEADER or ident is None:
        return None, None
    conf = objecten.get("configuration") or {}
    secrets = conf.get("secrets") or {}
    try:
        items = ((load_safe(conf.get("data") or "") or {}).get("tokenauth") or {}).get("items") or []
    except YAMLError:
        return None, "objecten's configuration.data does not parse"
    tokens = {_plain_token(i.get("token"), secrets) for i in items if isinstance(i, dict)}
    if header[len("Token "):] in tokens:
        return None, None  # an objecten token after all: nothing to switch
    item = next((i for i in items if isinstance(i, dict) and i.get("identifier") == ident), None)
    if item is None:
        return None, f"objecten has no tokenauth item '{ident}'"
    mode = SWITCH_REQUIRED_MODE.get(component)
    if mode and not any(isinstance(p, dict) and p.get("mode") == mode for p in item.get("permissions") or []):
        return None, f"objecten's tokenauth item '{ident}' has no {mode} permission"
    token = _plain_token(item.get("token"), secrets)
    if not token:
        return None, f"the token of objecten's tokenauth item '{ident}' cannot be resolved"
    if checks is not None and not item.get("is_superuser") and not item.get("permissions"):
        checks.append(f"CHECK {component}: objecten's tokenauth item '{ident}' has no permissions; give it read "
                      f"access to the objecttypes {component} uses")
    return f"Token {token}", None


def _switched_note(objecten: dict, component: str, sid: str, new_header: str) -> str:
    ident = SWITCH_IDENTIFIER[component]
    try:
        items = ((load_safe((objecten.get("configuration") or {}).get("data") or "") or {})
                 .get("tokenauth") or {}).get("items") or []
    except YAMLError:
        items = []
    item = next((i for i in items if isinstance(i, dict) and i.get("identifier") == ident), {})
    perms = "superuser" if item.get("is_superuser") else _permission_summary(item)
    return f"SWITCHED {component}: {sid} token objecttypen -> {ident} ({new_header}; {ident}: {perms})"


def _objecten_tokens(objecten: dict) -> tuple[list[dict], dict]:
    """(objecten's tokenauth items, objecten's configuration.secrets). Raises YAMLError."""
    conf = objecten.get("configuration") or {}
    items = ((load_safe(conf.get("data") or "") or {}).get("tokenauth") or {}).get("items") or []
    return [i for i in items if isinstance(i, dict)], conf.get("secrets") or {}


def _is_objecten_token(objecten: dict, token: str) -> bool:
    try:
        items, secrets = _objecten_tokens(objecten)
    except YAMLError:
        return False
    return any(_plain_token(i.get("token"), secrets) == token for i in items)


def _plan_openzaak_item(objecten: dict, header) -> tuple[dict | None, str | None]:
    """Plan objecten's read-only tokenauth item 'openzaak' for Open Zaak's old objecttypen token.

    Returns:
      (plan, None): `header` is the old objecttypen token, no objecten item has
        it yet, and the 'zaak' item gives the objecttypes to copy (read_only);
      (None, reason): it is the old objecttypen token, but the item can't be
        added (an ACTION);
      (None, None): nothing to do, because `header` is not the old objecttypen
        token, or that token is already an objecten token (the 'openzaak' item
        from an earlier run, or another item)."""
    if header != OBJECTTYPEN_TOKEN_HEADER:
        return None, None
    try:
        items, secrets = _objecten_tokens(objecten)
    except YAMLError:
        return None, "objecten's configuration.data does not parse"
    if any(_plain_token(i.get("token"), secrets) == OBJECTTYPEN_TOKEN for i in items):
        return None, None
    if any(i.get("identifier") == OPENZAAK_ITEM for i in items):
        return None, (f"objecten has a tokenauth item '{OPENZAAK_ITEM}' with another token; give it "
                      f"{OBJECTTYPEN_TOKEN} or point Open Zaak's objecten-api at its token")
    zaak = next((i for i in items if i.get("identifier") == "zaak"), None)
    object_types = [p["object_type"] for p in (zaak or {}).get("permissions") or []
                    if isinstance(p, dict) and p.get("object_type") is not None]
    if not object_types:
        return None, (f"objecten has no 'zaak' tokenauth item with objecttype permissions to copy; add a "
                      f"read_only item '{OPENZAAK_ITEM}' with token {OBJECTTYPEN_TOKEN} by hand")
    value_from = isinstance(zaak.get("token"), dict)
    if value_from and secrets.get(OPENZAAK_SECRET_ENV) not in (None, OBJECTTYPEN_TOKEN):
        return None, (f"objecten.configuration.secrets.{OPENZAAK_SECRET_ENV} exists with another value; add the "
                      f"'{OPENZAAK_ITEM}' item by hand")
    return {"value_from": value_from, "add_secret": value_from and OPENZAAK_SECRET_ENV not in secrets,
            "contact_person": zaak.get("contact_person"), "email": zaak.get("email"),
            "object_types": object_types}, None


# Words YAML 1.1 reads as a boolean or null when they are unquoted.
YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null", "nil", "none"}


def _flow(value) -> str:
    """A scalar or a {value_from: {env: ...}} mapping as one YAML line."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if (isinstance(value, str) and re.fullmatch(r"[A-Za-z][\w.@ -]*", value) and not value.endswith(" ")
            and value.lower() not in YAML_WORDS):
        return value
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _quoted(value) -> str:
    """A string scalar in double quotes, as the environment values write object type UUIDs and placeholders."""
    if not isinstance(value, str):
        return _flow(value)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _openzaak_item(plan: dict) -> dict:
    token = {"value_from": {"env": OPENZAAK_SECRET_ENV}} if plan["value_from"] else OBJECTTYPEN_TOKEN
    item = {"identifier": OPENZAAK_ITEM, "token": token}
    for key in ("contact_person", "email"):
        if plan[key] is not None:
            item[key] = plan[key]
    item["is_superuser"] = False
    item["permissions"] = [{"object_type": ot, "mode": "read_only"} for ot in plan["object_types"]]
    return item


def _openzaak_item_lines(plan: dict, dash_col: int) -> list[str]:
    item = _openzaak_item(plan)
    pad = " " * dash_col
    out = [f"{pad}- identifier: {item['identifier']}",
           f"{pad}  token: " + (_flow(item["token"]) if isinstance(item["token"], dict) else f'"{item["token"]}"')]
    out += [f"{pad}  {key}: {_flow(item[key])}" for key in ("contact_person", "email") if key in item]
    out += [f"{pad}  is_superuser: false", f"{pad}  permissions:"]
    for perm in item["permissions"]:
        # Quoted like the environment values write object types: an unquoted
        # placeholder (REP_..._REP) fails the SSC quoting check.
        out += [f"{pad}    - object_type: {_quoted(perm['object_type'])}", f"{pad}      mode: read_only"]
    return out


def _value_paths(node, value, path=()):
    """Paths of every scalar equal to `value` in a parsed configuration.data."""
    if isinstance(node, dict):
        for key, child in node.items():
            yield from _value_paths(child, value, path + (key,))
    elif isinstance(node, list):
        for idx, child in enumerate(node):
            yield from _value_paths(child, value, path + (idx,))
    elif node == value:
        yield path


def merge_objecttypen_services(text: str) -> tuple[str, list[str], list[str]]:
    """Return (new_text, notes, actions) for the duplicate zgw_consumers api_root
    the objecttypen merge leaves behind.

    After the merge a component's objecttypen service (objecttypen-api in Open
    Formulieren, objecttypen-service in Open Beheer) points at the objecten
    api_root. When the component also has an objecten service there, its config
    job fails on zgw_consumers' unique api_root. Per component and objecten
    api_root (compared exactly, as the database does): with exactly one
    objecttypen service and one other service, the objecttypen service is
    removed and every *_service_identifier that named it is repointed at the
    other one. Open Formulieren's old objecttypen token on the kept service is
    switched to objecten's `formulier` token (see _switch_header); a single
    service at the objecten api_root that sends it (one merged before) is
    switched too. Open Zaak keeps the old objecttypen token on its
    objecten-api: objecten gets a read-only tokenauth item `openzaak` with that
    token instead (see _plan_openzaak_item). Any other component that still
    sends it is an ACTION. Otherwise, only when their tokens differ is the
    token left as an ACTION: whether the kept token is an objecten token with
    the right permissions cannot be checked here. Any other duplicate at an
    objecten api_root is an ACTION to fix by hand. Duplicates at other
    api_roots are not this migration's and are left alone."""
    notes: list[str] = []
    actions: list[str] = []
    doc = load_safe(text)
    if not isinstance(doc, dict) or not isinstance(doc.get("objecten"), dict) or "objecttypen" in doc:
        return text, notes, actions
    hosts = _objecten_hosts(doc["objecten"])
    plans: dict[str, list[tuple[str | None, str, str | None]]] = {}
    merged: set[tuple[str, str]] = set()
    single: list[tuple[str, dict]] = []
    openzaak_plan: dict | None = None

    def old_token_left(component: str, sid: str, header) -> None:
        """Open Zaak: plan the 'openzaak' item. Any other component without a
        switch that still sends the old objecttypen token: an ACTION."""
        nonlocal openzaak_plan
        if component == "openzaak":
            plan, reason = _plan_openzaak_item(doc["objecten"], header)
            if plan and openzaak_plan is None:
                openzaak_plan = plan
                n = len(plan["object_types"])
                notes.append(f"ADDED objecten: tokenauth item '{OPENZAAK_ITEM}' (read_only on {n} objecttype(s)) "
                             f"for Open Zaak's {sid} token")
            elif reason:
                actions.append(f"{ACTION}openzaak: {sid} sends the old objecttypen token, which is not an objecten "
                               f"token: {reason} ({DUPLICATE_DOC})")
            elif header != OBJECTTYPEN_TOKEN_HEADER:
                try:
                    items, secrets = _objecten_tokens(doc["objecten"])
                except YAMLError:
                    items, secrets = [], {}
                zaak = next((i for i in items if i.get("identifier") == "zaak"), None)
                if zaak and header == f"Token {_plain_token(zaak.get('token'), secrets)}":
                    notes.append(f"CHECK openzaak: {sid} sends ZAC's 'zaak' token, so Open Zaak and ZAC share one "
                                 f"credential. If an earlier version of this script switched it, set its "
                                 f"header_value back to {OBJECTTYPEN_TOKEN_HEADER} and run the script again: it "
                                 f"then adds a read-only '{OPENZAAK_ITEM}' item ({DUPLICATE_DOC})")
        elif header == OBJECTTYPEN_TOKEN_HEADER and component not in SWITCH_IDENTIFIER \
                and not _is_objecten_token(doc["objecten"], OBJECTTYPEN_TOKEN):
            actions.append(f"{ACTION}{component}: {sid} sends the old objecttypen token, which is not an objecten "
                           f"token, and this script defines no switch for {component}. Give it a working objecten "
                           f"token ({DUPLICATE_DOC})")

    for component, cfg in doc.items():
        if component == "objecten" or not isinstance(cfg, dict):
            continue
        conf = cfg.get("configuration")
        if not isinstance(conf, dict) or not isinstance(conf.get("data"), str):
            continue
        try:
            inner = load_safe(conf["data"])
        except Exception as e:  # templated or broken YAML: report, do not guess
            notes.append(f"CHECK {component}: configuration.data does not parse ({type(e).__name__}); "
                         "check its zgw_consumers api_roots by hand")
            continue
        zc = inner.get("zgw_consumers") if isinstance(inner, dict) else None
        services = zc.get("services") if isinstance(zc, dict) else None
        if not isinstance(services, list):
            continue
        by_root: dict[str, list[dict]] = {}
        for svc in services:
            if isinstance(svc, dict) and svc.get("api_root") and _is_objecten_root(str(svc["api_root"]), hosts):
                by_root.setdefault(str(svc["api_root"]), []).append(svc)
        for api_root, svcs in by_root.items():
            if len(svcs) < 2:
                single.extend((component, svc) for svc in svcs)
                continue
            ids = [str(s["identifier"]) if s.get("identifier") else "<no identifier>" for s in svcs]
            ot = [s for s in svcs if s.get("identifier") and "objecttype" in str(s["identifier"])]
            keep = [s for s in svcs if s.get("identifier") and "objecttype" not in str(s["identifier"])]
            if len(ot) != 1 or len(keep) != 1 or len(svcs) != 2:
                actions.append(f"{ACTION}{component}: zgw_consumers services {', '.join(ids)} share api_root "
                               f"{api_root}; its config job fails on the unique api_root. Keep one service, point "
                               f"every *_service_identifier at it and give it a working objecten token ({DUPLICATE_DOC})")
                continue
            old_id, keep_id = str(ot[0]["identifier"]), str(keep[0]["identifier"])
            old_token, keep_token = ot[0].get("header_value"), keep[0].get("header_value")
            new_header, no_switch = _switch_header(doc["objecten"], component, keep_token, notes)
            plans.setdefault(component, []).append((old_id, keep_id, new_header))
            merged.add((component, keep_id))
            notes.append(f"{component}: removed zgw_consumers service {old_id} (same api_root {api_root} as "
                         f"{keep_id}) and pointed its *_service_identifier references at {keep_id}")
            if new_header:
                notes.append(_switched_note(doc["objecten"], component, keep_id, new_header))
                continue
            if no_switch:
                notes.append(f"{component}: {keep_id} sends the old objecttypen token and is not switched: {no_switch}")
            else:
                old_token_left(component, keep_id, keep_token)
            if old_token != keep_token:
                actions.append(f"{ACTION}{component}: {keep_id} now serves the Objects and the Objecttypen API with "
                               f"its own token ({keep_token}); the removed {old_id} sent {old_token}. Check that "
                               f"{keep_id}'s token is an objecten token with the permissions {component} needs; a "
                               f"value_from env token comes from the {component}-configuration-secrets Secret "
                               f"({component}.configuration.secrets) ({DUPLICATE_DOC})")
    # A service at the objecten api_root that was not merged (Open Zaak's
    # objecten-api, or Open Formulieren's when merged by an earlier version of
    # this script) can still send the old objecttypen token.
    for component, svc in single:
        sid = svc.get("identifier")
        if not sid or (component, str(sid)) in merged:
            continue
        new_header, no_switch = _switch_header(doc["objecten"], component, svc.get("header_value"), notes)
        if new_header:
            plans.setdefault(component, []).append((None, str(sid), new_header))
            notes.append(_switched_note(doc["objecten"], component, str(sid), new_header))
        elif no_switch:
            actions.append(f"{ACTION}{component}: {sid} sends the old objecttypen token, which is not an objecten "
                           f"token, and is not switched: {no_switch}. Give it a working objecten token "
                           f"({DUPLICATE_DOC})")
        else:
            old_token_left(component, str(sid), svc.get("header_value"))
    if not plans and openzaak_plan is None:
        return text, notes, actions

    lines = text.split("\n")
    root = _rt_yaml().load(text)
    ed = Edits()
    expected_inner: dict[str, object] = {}
    for component, merges in plans.items():
        comp = root[component]
        _, c_e = key_range(lines, root, component, len(lines))
        _, cf_e = key_range(lines, comp, "configuration", c_e)
        d_s, d_e = key_range(lines, comp["configuration"], "data", cf_e)
        if not re.search(r":\s*\|[-+]?\s*(#.*)?$", lines[d_s]):
            raise MigrationError(f"{component}.configuration.data is not a literal block (|)")
        content = lines[d_s + 1:d_e]
        ind = min((_indent(c) for c in content if c.strip()), default=_indent(lines[d_s]) + 2)
        inner_text = "\n".join(c[ind:] if c.strip() else "" for c in content)
        i_lines = inner_text.split("\n")
        i_root = _rt_yaml().load(inner_text)
        plain = load_safe(inner_text)
        i_ed = Edits()
        services = i_root["zgw_consumers"]["services"]
        _, s_e = path_range(i_lines, i_root, ["zgw_consumers", "services"], len(i_lines))
        for old_id, keep_id, new_header in merges:
            if new_header:
                k_idx = next(n for n, s in enumerate(services)
                             if isinstance(s, dict) and str(s.get("identifier")) == keep_id)
                line = services[k_idx].lc.key("header_value")[0]
                i_ed.replace(line, line + 1, [_scalar_line(i_lines[line], new_header)])
                next(s for s in plain["zgw_consumers"]["services"]
                     if isinstance(s, dict) and str(s.get("identifier")) == keep_id)["header_value"] = new_header
            if old_id is None:  # token switch only
                continue
            idx = next(n for n, s in enumerate(services) if isinstance(s, dict) and str(s.get("identifier")) == old_id)
            i_ed.delete(*item_range(i_lines, services, idx, s_e))
            plain["zgw_consumers"]["services"] = [s for s in plain["zgw_consumers"]["services"]
                                                  if not (isinstance(s, dict) and str(s.get("identifier")) == old_id)]
            for path in list(_service_identifier_refs(load_safe(inner_text), old_id)):
                parent = _get_path(i_root, path[:-1])
                line = parent.lc.key(path[-1])[0]
                i_ed.replace(line, line + 1, [_scalar_line(i_lines[line], keep_id)])
                _get_path(plain, path[:-1])[path[-1]] = keep_id
        # Only *_service_identifier keys are repointed: a reference under any
        # other key would still name the removed service.
        for old_id, _, _ in merges:
            left = next(_value_paths(plain, old_id), None) if old_id is not None else None
            if left is not None:
                raise MigrationError(f"{component}: the removed zgw_consumers service {old_id} is still referenced "
                                     f"at {'.'.join(map(str, left))}; point it at the kept service by hand")
        new_inner = "\n".join(i_ed.apply(i_lines))
        ed.replace(d_s + 1, d_e, [(" " * ind + line) if line.strip() else "" for line in new_inner.split("\n")])
        expected_inner[component] = plain
    want = copy.deepcopy(doc)
    if openzaak_plan is not None:
        comp = root["objecten"]
        _, c_e = key_range(lines, root, "objecten", len(lines))
        _, cf_e = key_range(lines, comp, "configuration", c_e)
        d_s, d_e = key_range(lines, comp["configuration"], "data", cf_e)
        if not re.search(r":\s*\|[-+]?\s*(#.*)?$", lines[d_s]):
            raise MigrationError("objecten.configuration.data is not a literal block (|)")
        content = lines[d_s + 1:d_e]
        ind = min((_indent(c) for c in content if c.strip()), default=_indent(lines[d_s]) + 2)
        inner_text = "\n".join(c[ind:] if c.strip() else "" for c in content)
        i_lines = inner_text.split("\n")
        i_root = _rt_yaml().load(inner_text)
        items = i_root["tokenauth"]["items"]
        _, items_e = path_range(i_lines, i_root, ["tokenauth", "items"], len(i_lines))
        i_ed = Edits()
        i_ed.insert(items_e, _openzaak_item_lines(openzaak_plan, items.lc.item(0)[1] - 2))
        new_inner = "\n".join(i_ed.apply(i_lines))
        ed.replace(d_s + 1, d_e, [(" " * ind + line) if line.strip() else "" for line in new_inner.split("\n")])
        plain = load_safe(inner_text)
        plain["tokenauth"]["items"].append(_openzaak_item(openzaak_plan))
        expected_inner["objecten"] = plain
        if openzaak_plan["add_secret"]:
            s_s, s_e = key_range(lines, comp["configuration"], "secrets", cf_e)
            if not comp["configuration"]["secrets"]:
                raise MigrationError("objecten.configuration.secrets is empty or a flow mapping")
            ed.insert(s_e, [" " * child_indent(lines, s_s, s_e) + f'{OPENZAAK_SECRET_ENV}: "{OBJECTTYPEN_TOKEN}"'])
            want["objecten"]["configuration"]["secrets"][OPENZAAK_SECRET_ENV] = OBJECTTYPEN_TOKEN
    out = "\n".join(ed.apply(lines))

    # Check: only the planned configuration.data blocks changed, exactly as intended
    got = load_safe(out)
    for component, plain in expected_inner.items():
        got_inner = load_safe(got[component]["configuration"]["data"])
        if got_inner != plain:
            raise MigrationError(f"self-check failed for {component} zgw_consumers merge "
                                 f"({_first_difference(plain, got_inner)}); nothing written")
        got[component]["configuration"]["data"] = want[component]["configuration"]["data"] = None
    if got != want:
        raise MigrationError(f"self-check failed: the zgw_consumers merge changed more than intended "
                             f"({_first_difference(want, got)}); nothing written")
    return out, notes, actions


def process(path: str, args) -> tuple[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate_text(text, args.objecten_image_repository)
        new, merge_notes, actions = merge_objecttypen_services(new)
    except Exception as e:  # noqa: BLE001 -- unexpected file shape: report, never write half a migration
        return "error", [error_note(e)]
    notes += merge_notes + actions
    changes = [(path, text, new)] if new != text else []
    migrated_doc = load_safe(new)
    has_objecten = isinstance(migrated_doc, dict) and "objecten" in migrated_doc \
        and "objecttypen" not in migrated_doc
    if not args.no_gateway and not has_objecten:
        notes.append("no objecten block in podiumd.yml (deployed from elsewhere?): services-gateway.yml "
                     "left alone, its objecttypen may still be running")
    if not args.no_gateway and has_objecten:
        gw = os.path.join(os.path.dirname(path), "services-gateway.yml")
        if os.path.exists(gw):
            with open(gw, encoding="utf-8") as f:
                gtext = f.read()
            gnew = migrate_gateway(gtext)
            if gnew != gtext:
                changes.append((gw, gtext, gnew))
                notes.append("services-gateway.yml: objecttypen-nginx ExternalName -> objecten")
    if not changes:
        return "unchanged", notes
    for p, old, new in changes:
        if args.dry_run:
            sys.stdout.write(unified_diff(p, old, new))
        else:
            write_lf(p, new)
    return "migrated", notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="podiumd.yml files (default: all under --gemeenten-dir)")
    parser.add_argument("--gemeenten-dir",
                        help="directory with <gemeente>/<env>/podiumd.yml (used when no files are given)")
    parser.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    parser.add_argument("--no-gateway", action="store_true", help="do not touch services-gateway.yml")
    parser.add_argument("--objecten-image-repository", metavar="REPO",
                        help="set objecten.image.repository (e.g. an ACR mirror of maykinmedia/open-object)")
    args = parser.parse_args()

    if not args.files and not args.gemeenten_dir:
        parser.error("give podiumd.yml files or --gemeenten-dir")
    files = args.files or sorted(glob.glob(os.path.join(os.path.expanduser(args.gemeenten_dir), "*", "*", "podiumd.yml")))
    if not files:
        print("No podiumd.yml files found.", file=sys.stderr)
        return 1
    counts = {"migrated": 0, "unchanged": 0, "error": 0}
    pending: list[tuple[str, str]] = []
    added = False
    for path in files:
        status, notes = process(path, args)
        counts[status] += 1
        out = sys.stderr if args.dry_run else sys.stdout
        print(f"[{status}] {path}", file=out)
        for n in notes:
            print(f"    - {n}", file=out)
        pending += [(path, n) for n in notes if n.startswith(ACTION)]
        added = added or any(n.startswith("ADDED objecten") for n in notes)
    out = sys.stderr if args.dry_run else sys.stdout
    need_action = len({p for p, _ in pending})
    print(f"\n{counts['migrated']} migrated, {counts['unchanged']} unchanged, {counts['error']} error(s), "
          f"{need_action} need action", file=out)
    if pending:
        print("\nNeeds action before the deploy (the config job fails otherwise):", file=out)
        for p, n in pending:
            print(f"  {p}: {n[len(ACTION):]}", file=out)
    print("Before deploying an environment: run `import_objecttypes` in its objecten (3.6.x) - see "
          "docs/apps/objecten/openobject-migration.md.", file=out)
    if added:
        print(f"Where the '{OPENZAAK_ITEM}' item was added: check that the secret behind {OBJECTTYPEN_TOKEN} differs "
              "from every other objecten token of that environment (Open Object refuses a duplicate token).",
              file=out)
    if counts["error"]:
        return 1
    return 2 if pending else 0


if __name__ == "__main__":
    sys.exit(main())
