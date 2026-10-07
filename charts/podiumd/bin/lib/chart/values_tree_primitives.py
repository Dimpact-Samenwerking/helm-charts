"""Values-tree and dependency-list primitives; no other lib.chart.* imports."""

import re

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlValue
from lib.yaml_types import scalar_text

UTF8_BOM = b"\xef\xbb\xbf"


def get_path(node: YamlValue, dotted_path: str) -> YamlValue:
    """The value at `dotted_path` (e.g. "openzaak.image.tag") in `node`, or None if absent."""
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def text_at(node: YamlValue, dotted_path: str) -> str | None:
    """get_path, as the scalar text Helm renders there (see scalar_text):
    None when the value is missing or not a string or number."""
    return scalar_text(get_path(node, dotted_path))


def mapping_at(node: YamlValue, dotted_path: str) -> YamlMapping:
    """get_path when the value is a mapping, else {} (e.g. an empty "global:" reads as None)."""
    value = get_path(node, dotted_path)
    return value if isinstance(value, dict) else {}


def deep_merge(base: YamlMapping, overlay: YamlMapping):
    """Merge overlay into base in place, the way Helm layers values: a
    mapping in both is merged key by key, any other overlay value
    replaces base's."""
    for key, value in overlay.items():
        sub = base.get(key)
        if isinstance(value, dict) and isinstance(sub, dict):
            deep_merge(sub, value)
        else:
            base[key] = value


def replace_scalar_value(line: str, new_value: str) -> str:
    """Replace a "key: <value>" line's scalar, keeping indent, quotes, "&anchor" and trailing comment.

    Avoids a load/dump round trip that would lose comments. Dropping an
    "&anchor" would break every "*anchor" alias to it.
    """
    m = re.match(
        r'^(?P<indent>\s*)(?P<key>[^:\n]+:)\s*(?P<anchor>&\S+\s+)?(?P<quote>["\']?)'
        r"(?P<value>.*?)(?P=quote)\s*(?P<comment>#.*)?\s*$",
        line,
    )
    if not m:
        msg = f"error: could not parse line for replacement: {line!r}"
        raise SystemExit(msg)
    anchor = m.group("anchor") or ""
    quote = m.group("quote")
    comment = f"  {m.group('comment')}" if m.group("comment") else ""
    return f"{m.group('indent')}{m.group('key')} {anchor}{quote}{new_value}{quote}{comment}\n"


def same_name(a: str, b: str) -> bool:
    """True if two component or image names match, ignoring case."""
    return a.casefold() == b.casefold()


def values_key_of(dep: ChartDependency) -> str:
    """The values.yaml key of a Chart.yaml dependency: its alias, or its
    name when it has no (or an empty) alias."""
    return dep.get("alias") or dep["name"]


def dep_for_values_key(deps: list[ChartDependency], values_key: str) -> ChartDependency | None:
    """The Chart.yaml dependency whose values_key_of equals `values_key`,
    or None when no dependency owns that key (e.g. an orphan top-level
    values.yaml block with no separate chart, like frankgateway)."""
    return next((dep for dep in deps if values_key_of(dep) == values_key), None)


def find_dependency(deps: list[ChartDependency], name_or_alias: str) -> ChartDependency | None:
    """The dependency matching this name or alias, or None; no I/O.

    An exact match wins, otherwise case is ignored. Exits when several
    match ignoring case.
    """
    for dep in deps:
        if name_or_alias in (dep["name"], dep.get("alias")):
            return dep
    matches = [
        dep for dep in deps if same_name(dep["name"], name_or_alias) or same_name(dep.get("alias") or "", name_or_alias)
    ]
    if len(matches) > 1:
        names = ", ".join(values_key_of(dep) for dep in matches)
        msg = f"error: '{name_or_alias}' matches more than one dependency ignoring case: {names}"
        raise SystemExit(msg)
    return matches[0] if matches else None


def require_dependency(chart_yaml: Path, name_or_alias: str) -> ChartDependency:
    """find_dependency on `chart_yaml`'s dependencies; exits with an
    error naming `chart_yaml` when none matches."""
    deps = load_chart_dependencies(chart_yaml)
    dep = find_dependency(deps, name_or_alias)
    if dep is None:
        msg = f"error: no dependency named or aliased '{name_or_alias}' found in {chart_yaml}"
        raise SystemExit(msg)
    return dep


def own_template_files_referencing(chart_dir: Path, key: str) -> list[str]:
    """Sorted chart_dir-relative paths of podiumd's templates/ files containing ".Values.<key>".

    Top-level key granularity only: helper indirection defeats finer text
    search. [] if nothing matches.
    """
    templates_dir = chart_dir / "templates"
    if not templates_dir.is_dir():
        return []
    pattern = re.compile(rf"\.Values\.{re.escape(key)}\b")
    return [
        str(path.relative_to(chart_dir))
        for path in sorted(templates_dir.rglob("*.yaml"))
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="replace"))
    ]


def resolve_values_path_source(chart_dir: Path, deps: list[ChartDependency], path: tuple[str, ...]) -> str:
    """Where `path`'s top-level key comes from: its dependency chart and version, or the templates using it."""
    dep = find_dependency(deps, path[0])
    if dep is not None:
        return f"chart {dep['name']}@{dep['version']}"
    files = own_template_files_referencing(chart_dir, path[0])
    if files:
        return f"local: {', '.join(files)}"
    return "local: no referencing template found"


def find_app_versions(values: YamlMapping | None, values_key: str, image_paths: list[str]) -> list[tuple[str, str]]:
    """[(image_path, tag), ...] for each of `image_paths` with a tag override under values[values_key]."""
    base: YamlValue = values.get(values_key, {}) if isinstance(values, dict) else {}
    versions: list[tuple[str, str]] = []
    for path in image_paths:
        tag = text_at(base, f"{path}.tag")
        if tag:
            versions.append((path, tag))
    return versions


def version_of(tag: str) -> str:
    """`tag` without a trailing "@sha256:<digest>"."""
    return tag.split("@", 1)[0]


def image_version_changed(old_tag: str | None, new_tag: str | None) -> bool:
    """Whether an image pin's version (not just its digest) changed; a pin new at this path counts as changed."""
    if new_tag is None:
        return False
    return old_tag is None or version_of(old_tag) != version_of(new_tag)


KEY_LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[\w.\-]+):(?:\s|$)")


def dotted_key_path(lines: list[str], line_index: int) -> str:
    """The dotted key path of lines[line_index] (inclusive), from indentation alone.

    E.g. "openzaak.image.tag". Lets digest-pin scanning keep the line
    number a full YAML parse would lose.
    """
    stack: list[tuple[int, str]] = []
    for raw in lines[: line_index + 1]:
        m = KEY_LINE_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, m.group("key")))
    return ".".join(key for _, key in stack)


def strip_registry_host(url: str) -> str:
    """`url` without its registry host (first segment with "." or ":", or "localhost").

    Same rule as scripts/mirror-strip-registry.py, duplicated because that
    script is outside lib/.
    """
    url = url.strip().split("@", 1)[0]
    head, _, rest = url.partition("/")
    if rest and ("." in head or ":" in head or head == "localhost"):
        return rest
    return url


def find_images(node: YamlValue, path: str = "") -> list[tuple[str, str, str]]:
    """Recursively walk a parsed values.yaml tree, yielding (path, repository,
    tag) for every dict that has both a non-empty "repository" and "tag"
    scalar (as the text Helm renders, see scalar_text)."""
    images: list[tuple[str, str, str]] = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            repo, tag = scalar_text(node["repository"]), scalar_text(node["tag"])
            if repo and tag:
                images.append((path or "(root)", repo, tag))
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            images.extend(find_images(value, child_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            images.extend(find_images(item, f"{path}[{i}]"))
    return images
