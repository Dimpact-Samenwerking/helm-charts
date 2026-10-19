#!/usr/bin/env python3
"""Add CPU and memory resources to the ECK Elasticsearch and Kibana overrides in gemeente values.

ECK sets only memory (2Gi) on the Elasticsearch and Kibana containers when the
custom resource's podTemplate gives them no resources, and no CPU at all.
PodiumD 4.10.0 sets them in the chart (`kiss-eck` in values.yaml). An
environment that overrides `kiss-eck.eck-elasticsearch.nodeSets` replaces that
list, though (Helm does not merge lists), so the chart's resources never reach
it. The same holds for `openinwoner.eck-elasticsearch.nodeSets`, which every
environment sets itself.

This script adds the resources to those overrides, at the right place:

  kiss-eck.eck-elasticsearch.nodeSets[]     container "elasticsearch"
  openinwoner.eck-elasticsearch.nodeSets[]  container "elasticsearch"
  kiss-eck.eck-kibana.podTemplate           container "kibana", only when the
                                            override lists containers itself
                                            (otherwise the chart's apply)

It creates whatever is missing (podTemplate, spec, containers, the container,
resources, requests, limits) and adds only missing keys: a value that is
already set, such as an environment's own memory, stays as it is. The added
values are the chart defaults:

  elasticsearch  requests cpu 250m, memory 2Gi; limits cpu 2000m, memory 2Gi
  kibana         requests cpu 100m, memory 2Gi; limits cpu 1000m, memory 2Gi

An added limit is never below a request the environment set, and an added
request never above a limit it set (e.g. requests.memory 4Gi alone gets
limits.memory 4Gi, not 2Gi).

2Gi memory is what ECK already used, so only the CPU is new. ECK restarts the
Elasticsearch nodes one at a time, and Kibana once, on the next deploy.

The file is edited line by line: only new lines are inserted, so comments,
quoting and REP_..._REP placeholders stay as they are. Before writing, the
script checks that the edited file parses to exactly the original values plus
the added keys; it refuses to write a file that does not. Running it twice is
safe: the second run changes nothing.

Usage:
  pip install ruamel.yaml
  python3 migrate-eck-resources-4.10.0.py --dry-run --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-eck-resources-4.10.0.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-eck-resources-4.10.0.py path/to/podiumd.yml ...
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

ELASTICSEARCH = {"requests": {"cpu": "250m", "memory": "2Gi"}, "limits": {"cpu": "2000m", "memory": "2Gi"}}
KIBANA = {"requests": {"cpu": "100m", "memory": "2Gi"}, "limits": {"cpu": "1000m", "memory": "2Gi"}}

# (path to the nodeSets list, container name, resources)
NODESET_TARGETS = [
    (("kiss-eck", "eck-elasticsearch", "nodeSets"), "elasticsearch", ELASTICSEARCH),
    (("openinwoner", "eck-elasticsearch", "nodeSets"), "elasticsearch", ELASTICSEARCH),
]
# (path to the podTemplate, container name, resources): only when it lists containers
PODTEMPLATE_TARGETS = [
    (("kiss-eck", "eck-kibana", "podTemplate"), "kibana", KIBANA),
]


class MigrationError(Exception):
    pass


def _load_rt(text: str):
    yaml = YAML()
    yaml.preserve_quotes = True
    return yaml.load(text)


def _load_safe(text: str):
    return YAML(typ="safe").load(text)


def _get(node, path):
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


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


def _child_col(mapping: CommentedMap, parent_col: int) -> int:
    """The column of a mapping's keys; parent column + 2 for an empty one."""
    for key in mapping:
        return mapping.lc.key(key)[1]
    return parent_col + 2


def _emit(value, col: int, seq_offset: int) -> list[str]:
    """Block YAML lines for a dict/list of plain scalars, keys at column col."""
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(" " * col + f"{key}:")
                lines += _emit(item, col + 2 if isinstance(item, dict) else col + seq_offset, seq_offset)
            else:
                lines.append(" " * col + f"{key}: {item}")
    else:  # a list of mappings: "- " at col, keys at col + 2
        for item in value:
            body = _emit(item, col + 2, seq_offset)
            lines.append(" " * col + "- " + body[0].lstrip())
            lines += body[1:]
    return lines


def _seq_offset(doc) -> int:
    """How far this file indents "- " under its key (0 or 2), from its first block sequence.

    ruamel reports an item's column after its "- ", hence the - 2.
    """
    def walk(node, col):
        if isinstance(node, CommentedMap):
            for key, value in node.items():
                key_col = node.lc.key(key)[1]
                if isinstance(value, CommentedSeq) and value and isinstance(value[0], CommentedMap):
                    return value.lc.item(0)[1] - 2 - key_col
                found = walk(value, key_col)
                if found is not None:
                    return found
        return None
    found = walk(doc, 0)
    return found if found is not None and found >= 0 else 2


class Inserts:
    """Lines to insert after given 0-based lines, applied bottom-up."""

    def __init__(self) -> None:
        self.ops: list[tuple[int, list[str]]] = []

    def after(self, line: int, new: list[str]) -> None:
        self.ops.append((line, new))

    def apply(self, lines: list[str]) -> list[str]:
        """Bottom-up; inserts after the same line keep the order they were added in."""
        out = list(lines)
        ordered = sorted(enumerate(self.ops), key=lambda op: (op[1][0], op[0]), reverse=True)
        for _, (line, new) in ordered:
            out[line + 1:line + 1] = new
        return out


def _ensure(parent: CommentedMap, parent_line: int, parent_col: int, missing: dict, ins: Inserts, offset: int) -> None:
    """Add the keys of `missing` that `parent` lacks, recursing into existing mappings.

    Existing mappings go first: when one is parent's last key, its inserts and a new
    sibling block anchor at the same line, and inserts keep the order they are added in.
    The other way round, limits.cpu would land inside a new requests block.
    """
    for key, value in missing.items():
        existing = parent.get(key)
        if isinstance(value, dict) and isinstance(existing, CommentedMap):
            key_line, key_col = parent.lc.key(key)
            _ensure(existing, key_line, key_col, value, ins, offset)
    for key, value in missing.items():
        if key not in parent:
            last = _last_line(parent, parent_line)
            ins.after(last, _emit({key: value}, _child_col(parent, parent_col), offset))


_UNITS = {"m": 0.001, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}


def _quantity(value) -> float:
    """A Kubernetes quantity ("250m", "2", "4Gi", "4096Mi") as a number."""
    text = str(value).strip()
    for unit in sorted(_UNITS, key=len, reverse=True):
        if text.endswith(unit):
            return float(text[: -len(unit)]) * _UNITS[unit]
    return float(text)


def _fitted(resources: dict, current) -> dict:
    """`resources` with each added limit at least the set request, each added request at most the set limit.

    An environment that sets only requests.memory: 4Gi must not get limits.memory: 2Gi:
    Kubernetes rejects a pod whose request is above its limit.
    """
    current = current if isinstance(current, dict) else {}
    requests = current.get("requests") if isinstance(current.get("requests"), dict) else {}
    limits = current.get("limits") if isinstance(current.get("limits"), dict) else {}
    fitted = copy.deepcopy(resources)
    for key in fitted["limits"]:
        try:
            if key in requests and key not in limits and _quantity(requests[key]) > _quantity(fitted["limits"][key]):
                fitted["limits"][key] = requests[key]
            if key in limits and key not in requests and _quantity(limits[key]) < _quantity(fitted["requests"][key]):
                fitted["requests"][key] = limits[key]
        except ValueError:
            raise MigrationError(f"resources {key} is not a plain quantity; add the resources by hand") from None
    return fitted


def _ensure_container(spec: CommentedMap, spec_line: int, spec_col: int, name: str, resources: dict,
                      ins: Inserts, offset: int) -> None:
    if "containers" not in spec:
        _ensure(spec, spec_line, spec_col, {"containers": [{"name": name, "resources": resources}]}, ins, offset)
        return
    containers = spec["containers"]
    if not isinstance(containers, CommentedSeq) or not containers or containers.fa.flow_style():
        raise MigrationError("podTemplate.spec.containers is empty or not a block list; add the resources by hand")
    for index, container in enumerate(containers):
        if isinstance(container, CommentedMap) and container.get("name") == name:
            line, col = containers.lc.item(index)
            _ensure(container, line, col - 2, {"resources": _fitted(resources, container.get("resources"))},
                    ins, offset)
            return
    key_line, key_col = spec.lc.key("containers")
    dash_col = containers.lc.item(0)[1] - 2 if containers else key_col + offset
    ins.after(_last_line(containers, key_line), _emit([{"name": name, "resources": resources}], dash_col, offset))


def _expected_container(spec: dict, name: str, resources: dict) -> None:
    containers = spec.setdefault("containers", [])
    container = next((c for c in containers if isinstance(c, dict) and c.get("name") == name), None)
    if container is None:
        containers.append({"name": name, "resources": copy.deepcopy(resources)})
        return
    current = container.setdefault("resources", {})
    for kind, values in _fitted(resources, current).items():
        target = current.setdefault(kind, {})
        for key, value in values.items():
            target.setdefault(key, value)


def migrate_text(text: str) -> tuple[str, list[str]]:
    """Return (new_text, notes). Raises MigrationError."""
    doc = _load_rt(text)
    if not isinstance(doc, CommentedMap):
        return text, []
    want = copy.deepcopy(_load_safe(text))
    offset = _seq_offset(doc)
    ins = Inserts()
    notes: list[str] = []

    for path, name, resources in NODESET_TARGETS:
        node_sets = _get(doc, path)
        if node_sets is None:
            continue
        if not isinstance(node_sets, CommentedSeq):
            raise MigrationError(f"{'.'.join(path)} is not a block list; add the resources by hand")
        # Indent new lists like this one: ruamel reports an item's column after its "- ".
        key_col = _get(doc, path[:-1]).lc.key(path[-1])[1]
        local = node_sets.lc.item(0)[1] - 2 - key_col if node_sets else offset
        for index, node_set in enumerate(node_sets):
            line, col = node_sets.lc.item(index)
            set_name = node_set.get("name", index)
            pod_template = node_set.get("podTemplate")
            if pod_template is None or (isinstance(pod_template, CommentedMap) and "spec" not in pod_template):
                _ensure(node_set, line, col - 2,
                        {"podTemplate": {"spec": {"containers": [{"name": name, "resources": resources}]}}}, ins, local)
            else:
                spec = pod_template["spec"]
                spec_line, spec_col = pod_template.lc.key("spec")
                if not isinstance(spec, CommentedMap):
                    raise MigrationError(f"{'.'.join(path)}[{set_name}].podTemplate.spec is not a mapping")
                _ensure_container(spec, spec_line, spec_col, name, resources, ins, local)
            expected_set = _get(want, path)[index]
            _expected_container(expected_set.setdefault("podTemplate", {}).setdefault("spec", {}), name, resources)
            notes.append(f"{'.'.join(path)}[{set_name}]: {name} resources")

    for path, name, resources in PODTEMPLATE_TARGETS:
        spec = _get(doc, (*path, "spec"))
        if not isinstance(spec, CommentedMap) or "containers" not in spec:
            continue  # no containers in the override: the chart's container resources apply
        spec_line, spec_col = _get(doc, path).lc.key("spec")
        _ensure_container(spec, spec_line, spec_col, name, resources, ins, offset)
        _expected_container(_get(want, (*path, "spec")), name, resources)
        notes.append(f"{'.'.join(path)}: {name} resources")

    if not ins.ops:
        return text, []
    out = "\n".join(ins.apply(text.split("\n")))
    if _load_safe(out) != want:
        raise MigrationError("self-check failed: the edited file does not match the intended values; nothing written")
    return out, notes


def process(path: str, dry_run: bool) -> tuple[str, list[str]]:
    # Universal newlines read CRLF as LF; a migrated file is written with LF only, on every OS.
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new, notes = migrate_text(text)
    except MigrationError as e:
        return "error", [str(e)]
    except Exception as e:  # unexpected file shape: report, never write half a migration
        return "error", [f"unexpected {type(e).__name__}: {str(e).splitlines()[0][:200]}"]
    if new == text:
        return "unchanged", notes
    if dry_run:
        sys.stdout.write("".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                                      f"a/{path}", f"b/{path}")))
    else:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    return "migrated", notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="podiumd.yml files (default: all under --gemeenten-dir)")
    parser.add_argument("--gemeenten-dir", help="SSCHostingSync applications/gemeenten directory")
    parser.add_argument("--dry-run", action="store_true", help="print a unified diff, write nothing")
    args = parser.parse_args()
    files = list(args.files)
    if args.gemeenten_dir:
        files += sorted(glob.glob(os.path.join(args.gemeenten_dir, "*", "*", "podiumd.yml")))
    if not files:
        parser.error("give podiumd.yml files or --gemeenten-dir")
    counts = {"migrated": 0, "unchanged": 0, "error": 0}
    for path in files:
        status, notes = process(path, args.dry_run)
        counts[status] += 1
        if status != "unchanged" or notes:
            print(f"[{status}] {path}", file=sys.stderr)
            for note in notes:
                print(f"    - {note}", file=sys.stderr)
    print(f"{counts['migrated']} migrated, {counts['unchanged']} unchanged, {counts['error']} error(s)", file=sys.stderr)
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
