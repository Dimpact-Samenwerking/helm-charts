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
  - objecttypen's tokenauth items are merged in, so every token that used to
    work against the Objecttypen API keeps working against objecten. Items
    with the same identifier and token are dropped as duplicates; same
    identifier with another token is renamed to `<identifier>-objecttypen`.

  Consumers (every string value, including embedded configuration.data)
  - The public objecttypen hostname and `objecttypen.<ns>.svc.cluster.local`
    are replaced by the objecten ones: ita.*.type, zac.objecttypenApi.url,
    kiss objectTypeUrl's, omc endpoints, openformulieren's objecttypen-api
    service api_root, ... (only objecten.settings.allowedHosts keeps the old
    hostname, see above).
  - kiss.adapter.objecttypen is folded into kiss.adapter.objecten (its token
    is dropped: the adapter uses the objecten token).
  - mi.targets entries for component objecttypen are removed.

  services-gateway.yml (next to podiumd.yml, skip with --no-gateway)
  - The `objecttypen-nginx` ExternalName Service is repointed to
    objecten.<ns>.svc.cluster.local, so the existing HTTPRoute for the old
    hostname reaches objecten (IN-2597).

The file is edited in place, line by line: only the lines that change are
touched, so comments, quoting, indentation and REP_..._REP placeholders stay
as they are. Before writing, the script checks that the edited file parses to
exactly the intended values; it refuses to write a file that does not.

Not done by this script (reported as reminders):
  - objecten.image.repository: an override `<registry>/maykinmedia/objects-api`
    (a mirror of the old image), or a mirror under the legacy component name
    `<registry>/objecten`, becomes `<registry>/maykinmedia/open-object`: the
    name mirror-strip-registry.py gives the new image. That image must be
    mirrored there before deploying. Any other override is left alone and
    reported. --objecten-image-repository sets it explicitly.
  - Per environment, before deploying: run `import_objecttypes` in the old
    objecten (3.6.x; PodiumD 4.9.x ships 3.6.2) so every objecttype exists locally.

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
import difflib
import glob
import os
import re
import sys
from dataclasses import dataclass, field

try:
    from ruamel.yaml import YAML
except ImportError:
    print("ERROR: ruamel.yaml is required. Install with: pip install ruamel.yaml", file=sys.stderr)
    sys.exit(1)

GEMEENTEN_DIR = os.path.expanduser("~/projects/dimpact/ssctwente/Applications/applications/gemeenten")
RENAME_SUFFIX = "-objecttypen"


class MigrationError(Exception):
    """The file cannot be migrated automatically."""


# --------------------------------------------------------------------------- #
# YAML helpers
# --------------------------------------------------------------------------- #

def _rt_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    return y


def _safe_load(text: str):
    return YAML(typ="safe", pure=True).load(text)


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

    def rewrite(self, text: str) -> str:
        text = re.sub(rf"(?<![\w.-]){re.escape(self.old_public)}(?![\w-])", self.new_public, text)
        return re.sub(r"(?<![\w.-])objecttypen\.([a-z0-9-]+)\.svc\.cluster\.local(?![\w-])",
                      r"objecten.\1.svc.cluster.local", text)


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


def plan_tokenauth(objecten_items: list[dict], objecttypen_items: list[dict]) -> list[tuple[dict, str | None]]:
    """objecttypen tokenauth items to add, with their new identifier (None = keep)."""
    existing_ids = {i.get("identifier") for i in objecten_items}
    existing_tokens = {str(i.get("token")): i.get("identifier") for i in objecten_items}
    plan = []
    for item in objecttypen_items:
        ident, token = item.get("identifier"), str(item.get("token"))
        if token in existing_tokens:
            if existing_tokens[token] != ident:
                raise MigrationError(
                    f"objecttypen tokenauth item {ident!r} uses the same token as objecten item "
                    f"{existing_tokens[token]!r} - tokens must be unique in Open Object; resolve by hand")
            continue  # identical item: already there
        new_ident = None
        if ident in existing_ids:
            new_ident = f"{ident}{RENAME_SUFFIX}"
            if new_ident in existing_ids:
                raise MigrationError(f"cannot rename objecttypen tokenauth item {ident!r}: {new_ident!r} exists")
        plan.append((item, new_ident))
        existing_ids.add(new_ident or ident)
        existing_tokens[token] = new_ident or ident
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
    for item, new_ident in plan_tokenauth(items, (objecttypen_data.get("tokenauth") or {}).get("items") or []):
        moved = copy.deepcopy(item)
        moved.pop("fields", None)
        moved.pop("use_fields", None)
        if new_ident:
            moved["identifier"] = new_ident
        items.append(moved)
    return data


def expected_values(doc: dict, hosts: Hosts, image_repo: str | None) -> dict:
    out = copy.deepcopy(doc)
    ot = out.pop("objecttypen")
    out = _rewrite_strings(out, hosts)
    ob = out["objecten"]
    od = _safe_load(doc["objecten"]["configuration"]["data"]) or {}
    td = _safe_load(ot["configuration"].get("data") or "") or {}
    sites = (od.get("sites_config") or {}).get("items") or []
    settings = ob.setdefault("settings", {})
    settings["siteDomain"] = sites[0]["domain"] if sites else hosts.new_public
    allowed = [h.strip() for h in str(settings.get("allowedHosts") or "").split(",") if h.strip()]
    if hosts.old_public not in allowed:
        allowed.append(hosts.old_public)
    settings["allowedHosts"] = ",".join(allowed)
    cfg = ob["configuration"]
    secrets = cfg.get("secrets") or {}
    for k, v in (ot["configuration"].get("secrets") or {}).items():
        secrets.setdefault(k, v)
    su = _superuser_token((od.get("tokenauth") or {}).get("items") or [])
    secrets["create_required_objecttypen_token"] = su["token"]
    cfg["secrets"] = secrets
    cfg["data"] = expected_data(_rewrite_strings(od, hosts), _rewrite_strings(td, hosts))
    if "create_required_objecttypen_job" in ot:
        ob["create_required_objecttypen_job"] = ot["create_required_objecttypen_job"]
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
    return out


def normalise(doc: dict) -> dict:
    """objecten.configuration.data compared as parsed YAML, everything else as-is."""
    doc = copy.deepcopy(doc)
    cfg = ((doc.get("objecten") or {}).get("configuration") or {})
    if isinstance(cfg.get("data"), str):
        cfg["data"] = _safe_load(cfg["data"]) or {}
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
    plain_items = _safe_load(inner)["tokenauth"]["items"]
    plain_t_items = (_safe_load(objecttypen_inner) or {}).get("tokenauth", {}).get("items") or []
    plan = plan_tokenauth(plain_items, plain_t_items)
    planned = {id(i): n for i, n in plan}
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
            new_ident = planned[id(plain)]
            if new_ident:
                id_line = item.lc.key("identifier")[0] - i_s
                if id_line in range(len(block)):
                    block[id_line] = _scalar_line(block[id_line], new_ident)
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
    doc = _safe_load(text)
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
    od_plain = _safe_load(doc["objecten"]["configuration"].get("data") or "") or {}
    su = _superuser_token((od_plain.get("tokenauth") or {}).get("items") or [])
    if not su:
        raise MigrationError("objecten tokenauth has no is_superuser item to run the "
                             "create-required-objecttypen job with; add one by hand first")

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
    if old not in allowed:
        allowed.append("__KEEP_OLD_OBJECTTYPEN_HOST__")
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
    su_token = su["token"]
    if isinstance(su_token, dict):
        raise MigrationError("objecten superuser token is not a plain value; set "
                             "objecten.configuration.secrets.create_required_objecttypen_token by hand")
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

    out = "\n".join(ed.apply(lines))
    out = hosts.rewrite(out).replace("__KEEP_OLD_OBJECTTYPEN_HOST__", old)

    # Check: the edited file must parse to exactly the intended values
    want = normalise(expected_values(doc, hosts, image_repo))
    got = normalise(_safe_load(out))
    if want != got:
        raise MigrationError("self-check failed: the edited file does not match the intended values "
                             f"({_first_difference(want, got)}); nothing written")

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

def _diff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def process(path: str, args) -> tuple[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate_text(text, args.objecten_image_repository)
    except MigrationError as e:
        return "error", [str(e)]
    except Exception as e:  # unexpected file shape: report, never write half a migration
        return "error", [f"unexpected {type(e).__name__}: {str(e).splitlines()[0][:200]}"]
    changes = [(path, text, new)] if new != text else []
    if not args.no_gateway:
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
            sys.stdout.write(_diff(p, old, new))
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
    return "migrated", notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="podiumd.yml files (default: all under --gemeenten-dir)")
    parser.add_argument("--gemeenten-dir", default=GEMEENTEN_DIR,
                        help="directory with <gemeente>/<env>/podiumd.yml (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    parser.add_argument("--no-gateway", action="store_true", help="do not touch services-gateway.yml")
    parser.add_argument("--objecten-image-repository", metavar="REPO",
                        help="set objecten.image.repository (e.g. an ACR mirror of maykinmedia/open-object)")
    args = parser.parse_args()

    files = args.files or sorted(glob.glob(os.path.join(os.path.expanduser(args.gemeenten_dir), "*", "*", "podiumd.yml")))
    if not files:
        print("No podiumd.yml files found.", file=sys.stderr)
        return 1
    counts = {"migrated": 0, "unchanged": 0, "error": 0}
    for path in files:
        status, notes = process(path, args)
        counts[status] += 1
        out = sys.stderr if args.dry_run else sys.stdout
        print(f"[{status}] {path}", file=out)
        for n in notes:
            print(f"    - {n}", file=out)
    out = sys.stderr if args.dry_run else sys.stdout
    print(f"\n{counts['migrated']} migrated, {counts['unchanged']} unchanged, {counts['error']} error(s)", file=out)
    print("Before deploying an environment: run `import_objecttypes` in its objecten (3.6.x) - see "
          "docs/apps/objecten/openobject-migration.md.", file=out)
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
