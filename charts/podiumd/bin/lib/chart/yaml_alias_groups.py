"""Dotted values paths that share one scalar through YAML anchors and aliases."""

import functools

from collections.abc import Iterator
from pathlib import Path

import yaml

_MERGE_TAG = "tag:yaml.org,2002:merge"


def _mapping_pairs(node: yaml.MappingNode) -> Iterator[tuple[str, yaml.Node]]:
    """(key, value) pairs of `node` with "<<" merges expanded; explicit keys win over merged ones."""
    explicit = {k.value for k, _ in node.value if isinstance(k, yaml.ScalarNode) and k.tag != _MERGE_TAG}
    for key_node, value_node in node.value:
        if key_node.tag == _MERGE_TAG:
            sources = value_node.value if isinstance(value_node, yaml.SequenceNode) else [value_node]
            for source in sources:
                if isinstance(source, yaml.MappingNode):
                    yield from ((k, v) for k, v in _mapping_pairs(source) if k not in explicit)
        elif isinstance(key_node, yaml.ScalarNode):
            yield key_node.value, value_node


def _collect(node: yaml.Node, path: tuple[str, ...], paths_by_node: dict[int, list[str]]) -> None:
    if isinstance(node, yaml.MappingNode):
        for key, value in _mapping_pairs(node):
            _collect(value, (*path, key), paths_by_node)
    elif isinstance(node, yaml.ScalarNode) and path:
        paths_by_node.setdefault(id(node), []).append(".".join(path))


@functools.lru_cache(maxsize=8)
def alias_groups_in_text(text: str) -> dict[str, tuple[str, ...]]:
    """Each scalar path that shares its value with another path via an anchor, mapped to all such paths.

    Covers scalar aliases ("tag: *x"), aliases of an enclosing mapping
    ("image: *x") and "<<" merges. A group is in document order, so an
    anchor comes before its aliases. Paths inside sequences are left out.
    """
    # yaml.compose without its untyped stub.
    root = yaml.SafeLoader(text).get_single_node()
    if root is None:
        return {}
    paths_by_node: dict[int, list[str]] = {}
    _collect(root, (), paths_by_node)
    groups: dict[str, tuple[str, ...]] = {}
    for paths in paths_by_node.values():
        if len(paths) > 1:
            group = tuple(paths)
            groups.update(dict.fromkeys(group, group))
    return groups


def alias_groups(values_path: Path) -> dict[str, tuple[str, ...]]:
    """alias_groups_in_text of the file at `values_path`."""
    return alias_groups_in_text(values_path.read_text(encoding="utf-8"))
