#!/usr/bin/env python3
"""Add HSTS and nosniff to every HTTPRoute rule in an environment's ssl-gateway.yml (IN-3162).

Several PodiumD apps send no Strict-Transport-Security and/or no
X-Content-Type-Options header (PABC, ITA, OMC, Open Archiefbeheer, Open Beheer,
Open Formulieren). HSTS belongs at the edge, where TLS terminates. nosniff is an
application concern, but it has only one value, so the edge can add it safely
until every vendor sends it. The edge here is NGINX Gateway Fabric: the
HTTPRoutes in <gemeente>/<env>/ssl-gateway.yml (ExternalsPodiumD and SSC's
hosting repo); the podiumd chart does not render routes.

The script gives every rule of every HTTPRoute one response header filter:

  - type: ResponseHeaderModifier
    responseHeaderModifier:
      set:
        - name: Strict-Transport-Security
          value: max-age=31536000
        - name: X-Content-Type-Options
          value: nosniff

`set` replaces a value the app sends itself, so the header is never sent twice.
X-Frame-Options and Content-Security-Policy frame-ancestors are deliberately not
set: an app embedded in an iframe (Open Formulieren in Open Inwoner) must decide
that itself, and an edge value would replace the app's own.

Per rule:
  - no ResponseHeaderModifier yet: the filter above is added after the rule's
    last filter (or as a new `filters:` list when the rule has none);
  - a ResponseHeaderModifier already there: only the missing headers are added to
    its `set` list. A header that is already set, added or removed there keeps the
    environment's choice (e.g. its own HSTS max-age with includeSubDomains);
  - a rule that redirects (RequestRedirect) or has no backendRefs is skipped: no
    backend answers it, so no response headers can be modified.

Other documents (Services, SnippetsFilter, SnippetsPolicy, Gateway) and other
fields are left alone. The file is edited line by line: only new lines are
inserted, so comments, quoting and the file's layout stay as they are. Before
writing, the script checks that the edited file parses to exactly the original
documents plus the added headers; it refuses to write a file that does not.
Running it twice is safe: the second run changes nothing.

Usage:
  pip install ruamel.yaml
  python3 migrate-gateway-security-headers.py --dry-run --gemeenten-dir <repo>/applications/gemeenten
  python3 migrate-gateway-security-headers.py --gemeenten-dir <repo>/applications/gemeenten
  python3 migrate-gateway-security-headers.py --check --gemeenten-dir <repo>/applications/gemeenten
  python3 migrate-gateway-security-headers.py path/to/ssl-gateway.yml ...
"""

from __future__ import annotations

import argparse
import copy
import difflib
import glob
import os
import sys

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
except ImportError:  # pragma: no cover
    sys.exit("ruamel.yaml is required: pip install ruamel.yaml")

DEFAULT_HSTS_MAX_AGE = 31536000
HEADER_FILTER = "ResponseHeaderModifier"
NO_BACKEND_FILTERS = {"RequestRedirect"}


class MigrationError(Exception):
    pass


def headers(hsts_max_age: int) -> list[dict]:
    return [
        {"name": "Strict-Transport-Security", "value": f"max-age={hsts_max_age}"},
        {"name": "X-Content-Type-Options", "value": "nosniff"},
    ]


def _load_rt_all(text: str) -> list:
    yaml = YAML()
    yaml.preserve_quotes = True
    return list(yaml.load_all(text))


def _load_safe_all(text: str) -> list:
    return list(YAML(typ="safe").load_all(text))


def _last_line(node, start_line: int) -> int:
    """The last line (0-based) a block node occupies, from ruamel's line info."""
    last = start_line
    if isinstance(node, CommentedMap):
        for key, value in node.items():
            key_line, _ = node.lc.key(key)
            value_line, _ = node.lc.value(key)
            last = max(last, key_line, value_line, _last_line(value, value_line))
    elif isinstance(node, CommentedSeq):
        for index, item in enumerate(node):
            item_line, _ = node.lc.item(index)
            last = max(last, item_line, _last_line(item, item_line))
    elif isinstance(node, str) and "\n" in node.rstrip("\n"):
        last = max(last, start_line + node.rstrip("\n").count("\n") + 1)
    return last


def _block_seq(node, what: str) -> CommentedSeq:
    # An empty list can only be written in flow style ([]), so it is refused too.
    if not isinstance(node, CommentedSeq) or not node or node.fa.flow_style():
        raise MigrationError(f"{what} is not a block list; add the headers by hand")
    return node


def _scalar(value) -> str:
    """A header value as a plain scalar, quoted only when YAML would read it differently."""
    text = str(value)
    safe = YAML(typ="safe").load(f"k: {text}")
    return text if safe == {"k": text} else "'" + text.replace("'", "''") + "'"


def _header_lines(items: list[dict], dash_col: int) -> list[str]:
    lines = []
    for item in items:
        lines.append(" " * dash_col + f"- name: {_scalar(item['name'])}")
        lines.append(" " * (dash_col + 2) + f"value: {_scalar(item['value'])}")
    return lines


def _filter_lines(items: list[dict], dash_col: int, offset: int) -> list[str]:
    """A ResponseHeaderModifier filter item, its "- " at dash_col."""
    body = dash_col + 2
    return [
        " " * dash_col + f"- type: {HEADER_FILTER}",
        " " * body + "responseHeaderModifier:",
        " " * (body + 2) + "set:",
        *_header_lines(items, body + 2 + offset),
    ]


def _seq_offset(seq: CommentedSeq, key_col: int, default: int) -> int:
    """How far a block list indents "- " under its key; ruamel reports an item's column after its "- "."""
    if seq:
        found = seq.lc.item(0)[1] - 2 - key_col
        if found >= 0:
            return found
    return default


class Inserts:
    """Lines to insert after given 0-based lines, applied bottom-up."""

    def __init__(self) -> None:
        self.ops: list[tuple[int, list[str]]] = []

    def after(self, line: int, new: list[str]) -> None:
        self.ops.append((line, new))

    def apply(self, lines: list[str]) -> list[str]:
        out = list(lines)
        ordered = sorted(enumerate(self.ops), key=lambda op: (op[1][0], op[0]), reverse=True)
        for _, (line, new) in ordered:
            out[line + 1:line + 1] = new
        return out


def _named(items, name: str) -> bool:
    return any(isinstance(i, dict) and str(i.get("name", "")).lower() == name.lower() for i in items or [])


def _migrate_rule(rule: CommentedMap, rule_line: int, rule_col: int, want_rule: dict, wanted: list[dict],
                  offset: int, ins: Inserts) -> str | None:
    """Plan the inserts for one rule and apply the same change to want_rule. Returns a note or None."""
    filters = rule.get("filters")
    types = [f.get("type") for f in filters or [] if isinstance(f, dict)]
    if NO_BACKEND_FILTERS & set(types) or not rule.get("backendRefs"):
        return "skipped (redirect or no backendRefs)"

    if "filters" not in rule:
        ins.after(_last_line(rule, rule_line),
                  [" " * rule_col + "filters:", *_filter_lines(wanted, rule_col + offset, offset)])
        want_rule["filters"] = [{"type": HEADER_FILTER, "responseHeaderModifier": {"set": copy.deepcopy(wanted)}}]
        return "added"
    filters = _block_seq(filters, "filters")
    key_line, key_col = rule.lc.key("filters")
    local = _seq_offset(filters, key_col, offset)

    existing = [i for i, f in enumerate(filters) if isinstance(f, dict) and f.get("type") == HEADER_FILTER]
    if not existing:
        ins.after(_last_line(filters, key_line), _filter_lines(wanted, key_col + local, local))
        want_rule["filters"].append({"type": HEADER_FILTER, "responseHeaderModifier": {"set": copy.deepcopy(wanted)}})
        return "added"

    index = existing[0]
    modifier = filters[index].get("responseHeaderModifier")
    if not isinstance(modifier, CommentedMap):
        raise MigrationError("a ResponseHeaderModifier filter has no responseHeaderModifier mapping; fix it by hand")
    present = [*(modifier.get("set") or []), *(modifier.get("add") or [])]
    removed = modifier.get("remove") or []
    missing = [h for h in wanted if not _named(present, h["name"])
               and not any(str(r).lower() == h["name"].lower() for r in removed)]
    if not missing:
        return None
    want_set = want_rule["filters"][index]["responseHeaderModifier"].setdefault("set", [])
    want_set.extend(copy.deepcopy(missing))
    if "set" in modifier:
        set_list = _block_seq(modifier["set"], "responseHeaderModifier.set")
        set_line, set_col = modifier.lc.key("set")
        if not set_list:
            raise MigrationError("responseHeaderModifier.set is empty; add the headers by hand")
        ins.after(_last_line(set_list, set_line),
                  _header_lines(missing, set_col + _seq_offset(set_list, set_col, local)))
    else:
        mod_line, mod_col = filters[index].lc.key("responseHeaderModifier")
        child_col = modifier.lc.key(next(iter(modifier)))[1] if modifier else mod_col + 2
        ins.after(_last_line(modifier, mod_line), [" " * child_col + "set:", *_header_lines(missing, child_col + local)])
    return "completed"


def migrate_text(text: str, hsts_max_age: int = DEFAULT_HSTS_MAX_AGE) -> tuple[str, list[str]]:
    """Return (new_text, notes). Raises MigrationError."""
    docs = _load_rt_all(text)
    want = copy.deepcopy(_load_safe_all(text))
    wanted = headers(hsts_max_age)
    ins = Inserts()
    notes: list[str] = []
    for doc, want_doc in zip(docs, want):
        if not isinstance(doc, CommentedMap) or doc.get("kind") != "HTTPRoute":
            continue
        name = (doc.get("metadata") or {}).get("name", "?")
        rules = (doc.get("spec") or {}).get("rules")
        if not rules:
            continue
        rules = _block_seq(rules, f"HTTPRoute {name} spec.rules")
        # A whole route's change in one note; per-rule details only when they differ.
        results = []
        for index, rule in enumerate(rules):
            if not isinstance(rule, CommentedMap):
                raise MigrationError(f"HTTPRoute {name} rule {index + 1} is not a mapping")
            line, col = rules.lc.item(index)
            try:
                results.append(_migrate_rule(rule, line, col, want_doc["spec"]["rules"][index], wanted,
                                             _seq_offset(rules, doc["spec"].lc.key("rules")[1], 2), ins))
            except MigrationError as e:
                raise MigrationError(f"HTTPRoute {name} rule {index + 1}: {e}") from None
        done = [r for r in results if r]
        if not done:
            continue
        if len(set(done)) == 1 and len(done) == len(results):
            notes.append(f"{name}: {done[0]}")
        else:
            notes.append(f"{name}: " + ", ".join(f"rule {i + 1} {r}" for i, r in enumerate(results) if r))

    if not ins.ops:
        return text, notes
    out = "\n".join(ins.apply(text.split("\n")))
    if _load_safe_all(out) != want:
        raise MigrationError("self-check failed: the edited file does not match the intended routes; nothing written")
    return out, notes


def process(path: str, args) -> tuple[str, list[str]]:
    # Universal newlines read CRLF as LF; a migrated file is written with LF only, on every OS.
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate_text(text, args.hsts_max_age)
    except MigrationError as e:
        return "error", [str(e)]
    except Exception as e:  # unexpected file shape: report, never write half a migration
        return "error", [f"unexpected {type(e).__name__}: {str(e).splitlines()[0][:200]}"]
    changes = [n for n in notes if " added" in n or " completed" in n or n.endswith((": added", ": completed"))]
    if new == text:
        return "unchanged", notes
    if args.check:
        return "needs migration", changes
    if args.dry_run:
        sys.stdout.write("".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                                      f"a/{path}", f"b/{path}")))
    else:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    return "migrated", notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="ssl-gateway.yml files (default: all under --gemeenten-dir)")
    parser.add_argument("--gemeenten-dir", help="directory with <gemeente>/<env>/ssl-gateway.yml (used when no files are given)")
    parser.add_argument("--hsts-max-age", type=int, default=DEFAULT_HSTS_MAX_AGE,
                        help=f"HSTS max-age in seconds (default {DEFAULT_HSTS_MAX_AGE}, one year)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 when a file needs migrating")
    args = parser.parse_args()

    if not args.files and not args.gemeenten_dir:
        parser.error("give ssl-gateway.yml files or --gemeenten-dir")
    if args.hsts_max_age <= 0:
        parser.error("--hsts-max-age must be positive")
    files = args.files or sorted(glob.glob(os.path.join(os.path.expanduser(args.gemeenten_dir), "*", "*", "ssl-gateway.yml")))
    if not files:
        print("No ssl-gateway.yml files found.", file=sys.stderr)
        return 1
    counts: dict[str, int] = {"migrated": 0, "needs migration": 0, "unchanged": 0, "error": 0}
    out = sys.stderr if args.dry_run else sys.stdout
    for path in files:
        status, notes = process(path, args)
        counts[status] += 1
        print(f"[{status}] {path}", file=out)
        for note in notes:
            print(f"    - {note}", file=out)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v or k in ("unchanged", "error"))
    print(f"\n{summary}", file=out)
    return 1 if counts["error"] or counts["needs migration"] else 0


if __name__ == "__main__":
    sys.exit(main())
