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

Exit code: 1 when a file has an error, or under --check when a file needs
migrating; else 0.

Usage:
  pip install ruamel.yaml
  python3 migrate-eck-resources-4.10.0.py --dry-run --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-eck-resources-4.10.0.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-eck-resources-4.10.0.py path/to/podiumd.yml ...
"""

from __future__ import annotations

import argparse
import copy
import sys

from migrate_common import MigrationError
from migrate_common import load_rt
from migrate_common import load_safe
from migrate_common import plain_scalar
from migrate_common import run
from migrate_common import seq_offset
from ruamel.yaml.comments import CommentedMap, CommentedSeq

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


def _emit(value, col: int, offset: int) -> list[str]:
    """Block YAML lines for a dict/list of plain scalars, keys at column col."""
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(" " * col + f"{key}:")
                lines += _emit(item, col + 2 if isinstance(item, dict) else col + offset, offset)
            else:
                # A copied quantity such as requests.cpu: "3" must stay a string.
                text = plain_scalar(item) if isinstance(item, str) else item
                lines.append(" " * col + f"{key}: {text}")
    else:  # a list of mappings: "- " at col, keys at col + 2
        for item in value:
            body = _emit(item, col + 2, offset)
            lines.append(" " * col + "- " + body[0].lstrip())
            lines += body[1:]
    return lines


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


def _ensure(parent: CommentedMap, parent_line: int, parent_col: int, missing: dict, ins: Inserts, offset: int,
            where: str) -> None:
    """Add the keys of `missing` that `parent` (at path `where`) lacks, recursing into existing mappings.

    Existing mappings go first: when one is parent's last key, its inserts and a new
    sibling block anchor at the same line, and inserts keep the order they are added in.
    The other way round, limits.cpu would land inside a new requests block.
    """
    for key, value in missing.items():
        existing = parent.get(key)
        if isinstance(value, dict) and key in parent:
            # `resources:` without a value has nothing to add keys to.
            if not isinstance(existing, CommentedMap):
                raise MigrationError(f"{where}.{key} is not a mapping; add the resources by hand")
            key_line, key_col = parent.lc.key(key)
            _ensure(existing, key_line, key_col, value, ins, offset, f"{where}.{key}")
    for key, value in missing.items():
        if key not in parent:
            # Block lines after a {...} mapping do not parse.
            if parent.fa.flow_style():
                raise MigrationError(f"{where} is a flow-style mapping ({{...}}); add the resources by hand")
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


def _ensure_container(spec: CommentedMap, name: str, resources: dict, ins: Inserts, where: str) -> None:
    """Add the resources to container `name` in spec.containers, or add that container."""
    containers = spec["containers"]
    if not isinstance(containers, CommentedSeq) or not containers or containers.fa.flow_style():
        raise MigrationError(f"{where}.containers is empty or not a block list; add the resources by hand")
    key_line, key_col = spec.lc.key("containers")
    offset = seq_offset(containers, key_col, 2)
    for index, container in enumerate(containers):
        if isinstance(container, CommentedMap) and container.get("name") == name:
            line, col = containers.lc.item(index)
            _ensure(container, line, col - 2, {"resources": _fitted(resources, container.get("resources"))},
                    ins, offset, f"{where}.containers[{name}]")
            return
    dash_col = key_col + offset
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


def migrate_text(text: str, _args: argparse.Namespace | None = None) -> tuple[str, list[str]]:
    """Return (new_text, notes). Raises MigrationError."""
    doc = load_rt(text)
    if not isinstance(doc, CommentedMap):
        return text, []
    want = load_safe(text)
    ins = Inserts()
    notes: list[str] = []

    for path, name, resources in NODESET_TARGETS:
        node_sets = _get(doc, path)
        if node_sets is None:
            continue
        if not isinstance(node_sets, CommentedSeq):
            raise MigrationError(f"{'.'.join(path)} is not a block list; add the resources by hand")
        if not node_sets:
            continue
        # Indent new lists like this one.
        offset = seq_offset(node_sets, _get(doc, path[:-1]).lc.key(path[-1])[1], 2)
        for index, node_set in enumerate(node_sets):
            line, col = node_sets.lc.item(index)
            set_name = node_set.get("name", index)
            where = f"{'.'.join(path)}[{set_name}]"
            before = len(ins.ops)
            pod_template = node_set.get("podTemplate")
            spec = pod_template.get("spec") if isinstance(pod_template, CommentedMap) else None
            if isinstance(spec, CommentedMap) and "containers" in spec:
                _ensure_container(spec, name, resources, ins, f"{where}.podTemplate.spec")
            else:
                _ensure(node_set, line, col - 2,
                        {"podTemplate": {"spec": {"containers": [{"name": name, "resources": resources}]}}},
                        ins, offset, where)
            expected_set = _get(want, path)[index]
            _expected_container(expected_set.setdefault("podTemplate", {}).setdefault("spec", {}), name, resources)
            if len(ins.ops) > before:
                notes.append(f"{where}: {name} resources")

    for path, name, resources in PODTEMPLATE_TARGETS:
        spec = _get(doc, (*path, "spec"))
        if not isinstance(spec, CommentedMap) or "containers" not in spec:
            continue  # no containers in the override: the chart's container resources apply
        before = len(ins.ops)
        _ensure_container(spec, name, resources, ins, f"{'.'.join(path)}.spec")
        _expected_container(_get(want, (*path, "spec")), name, resources)
        if len(ins.ops) > before:
            notes.append(f"{'.'.join(path)}: {name} resources")

    if not ins.ops:
        return text, []
    out = "\n".join(ins.apply(text.split("\n")))
    if load_safe(out) != want:
        raise MigrationError("self-check failed: the edited file does not match the intended values; nothing written")
    return out, notes


if __name__ == "__main__":
    sys.exit(run(__doc__, migrate_text))
