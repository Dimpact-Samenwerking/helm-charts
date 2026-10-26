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
    environment's choice (e.g. its own HSTS max-age with includeSubDomains).
    A choice weaker than the script's own gets a warning (in every mode, without
    changing the exit code): HSTS removed, without max-age or with a max-age
    below --hsts-max-age, and X-Content-Type-Options removed or not nosniff;
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
import re
import sys

from migrate_common import MigrationError
from migrate_common import load_rt_all
from migrate_common import load_safe
from migrate_common import load_safe_all
from migrate_common import run
from ruamel.yaml.comments import CommentedMap, CommentedSeq

DEFAULT_HSTS_MAX_AGE = 31536000
HEADER_FILTER = "ResponseHeaderModifier"
NO_BACKEND_FILTERS = {"RequestRedirect"}
WARNING = "warning: "


def headers(hsts_max_age: int) -> list[dict]:
    return [
        {"name": "Strict-Transport-Security", "value": f"max-age={hsts_max_age}"},
        {"name": "X-Content-Type-Options", "value": "nosniff"},
    ]


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
    safe = load_safe(f"k: {text}")
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


def _value(items, name: str) -> str | None:
    for i in items or []:
        if isinstance(i, dict) and str(i.get("name", "")).lower() == name.lower():
            return str(i.get("value", ""))
    return None


def _weaker(present: list, removed: list, hsts_max_age: int) -> list[str]:
    """What an existing ResponseHeaderModifier sets weaker than the script would."""
    found = []
    removed_names = {str(r).lower() for r in removed}
    if "strict-transport-security" in removed_names:
        found.append("removes Strict-Transport-Security")
    hsts = _value(present, "Strict-Transport-Security")
    if hsts is not None:
        age = re.search(r"max-age\s*=\s*\"?(\d+)", hsts, re.IGNORECASE)
        if not age:
            found.append(f"Strict-Transport-Security has no max-age ({hsts!r})")
        elif int(age.group(1)) < hsts_max_age:
            found.append(f"Strict-Transport-Security max-age={age.group(1)} is below {hsts_max_age}")
    if "x-content-type-options" in removed_names:
        found.append("removes X-Content-Type-Options")
    nosniff = _value(present, "X-Content-Type-Options")
    if nosniff is not None and nosniff.strip().lower() != "nosniff":
        found.append(f"X-Content-Type-Options is {nosniff!r}, not nosniff")
    return found


def _migrate_rule(rule: CommentedMap, rule_line: int, rule_col: int, want_rule: dict, wanted: list[dict],
                  offset: int, ins: Inserts, warnings: list[str], hsts_max_age: int) -> str | None:
    """Plan the inserts for one rule and apply the same change to want_rule. Returns a note or None.

    A header the rule already sets weaker than wanted is appended to warnings; it is kept as it is.
    """
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
    warnings.extend(_weaker(present, removed, hsts_max_age))
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
    docs = load_rt_all(text)
    want = load_safe_all(text)
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
            weak: list[str] = []
            try:
                results.append(_migrate_rule(rule, line, col, want_doc["spec"]["rules"][index], wanted,
                                             _seq_offset(rules, doc["spec"].lc.key("rules")[1], 2), ins,
                                             weak, hsts_max_age))
            except MigrationError as e:
                raise MigrationError(f"HTTPRoute {name} rule {index + 1}: {e}") from None
            notes.extend(f"{WARNING}{name} rule {index + 1} {w}; kept" for w in weak)
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
    if load_safe_all(out) != want:
        raise MigrationError("self-check failed: the edited file does not match the intended routes; nothing written")
    return out, notes


def _change_notes(notes: list[str]) -> list[str]:
    """The notes --check shows: warnings and the headers added or completed."""
    return [
        n
        for n in notes
        if n.startswith(WARNING) or " added" in n or " completed" in n or n.endswith((": added", ": completed"))
    ]


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--hsts-max-age",
        type=_positive_int,
        default=DEFAULT_HSTS_MAX_AGE,
        help=f"HSTS max-age in seconds (default {DEFAULT_HSTS_MAX_AGE}, one year)",
    )


def _migrate(text: str, args: argparse.Namespace) -> tuple[str, list[str]]:
    return migrate_text(text, args.hsts_max_age)


def _warned(_counts: dict[str, int], notes: list[list[str]]) -> str:
    warned = sum(any(n.startswith(WARNING) for n in file_notes) for file_notes in notes)
    return f"; {warned} with weaker headers kept (warnings above)" if warned else ""


if __name__ == "__main__":
    sys.exit(
        run(
            __doc__,
            _migrate,
            file_name="ssl-gateway.yml",
            add_arguments=_add_arguments,
            check_notes=_change_notes,
            summary_suffix=_warned,
        )
    )
