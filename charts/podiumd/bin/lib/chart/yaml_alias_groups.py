"""Values paths that share one scalar through YAML anchors and aliases, and the line each scalar is on."""

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


def _scalar_nodes(node: yaml.Node, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], yaml.ScalarNode]]:
    """(path, node) for every scalar under a mapping, in document order; an alias yields its anchor's node."""
    if isinstance(node, yaml.MappingNode):
        for key, value in _mapping_pairs(node):
            yield from _scalar_nodes(value, (*path, key))
    elif isinstance(node, yaml.ScalarNode) and path:
        yield path, node


@functools.lru_cache(maxsize=8)
def _scalars_in_text(text: str) -> tuple[tuple[tuple[str, ...], yaml.ScalarNode], ...]:
    """_scalar_nodes of the whole document; () for an empty one."""
    # yaml.compose without its untyped stub.
    root = yaml.SafeLoader(text).get_single_node()
    return () if root is None else tuple(_scalar_nodes(root))


def alias_groups_in_text(text: str) -> dict[str, tuple[str, ...]]:
    """Each scalar path that shares its value with another path via an anchor, mapped to all such paths.

    Covers scalar aliases ("tag: *x"), aliases of an enclosing mapping
    ("image: *x") and "<<" merges. A group is in document order, so an
    anchor comes before its aliases. Paths inside sequences are left out.
    """
    paths_by_node: dict[int, list[str]] = {}
    for path, node in _scalars_in_text(text):
        paths_by_node.setdefault(id(node), []).append(".".join(path))
    groups: dict[str, tuple[str, ...]] = {}
    for paths in paths_by_node.values():
        if len(paths) > 1:
            group = tuple(paths)
            groups.update(dict.fromkeys(group, group))
    return groups


def alias_groups(values_path: Path) -> dict[str, tuple[str, ...]]:
    """alias_groups_in_text of the file at `values_path`."""
    return alias_groups_in_text(values_path.read_text(encoding="utf-8"))


def scalar_lines_in_text(text: str) -> dict[tuple[str, ...], int]:
    """{path: 1-based line of its scalar value} for every scalar outside a sequence.

    An aliased path gets the line of its anchor, where the literal value is
    written: the line a writer must change.
    """
    return {path: node.start_mark.line + 1 for path, node in _scalars_in_text(text)}
