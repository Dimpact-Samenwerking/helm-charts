"""Generic values-tree/dependency-list primitives with no dependency on
any other lib.chart.* module: dotted-path lookup, in-place scalar-line
replacement, Chart.yaml dependency lookup, and version/repository-string
helpers. Pure, no filesystem access except own_template_files_
referencing/resolve_values_path_source (which just walk a chart's own
on-disk templates/ tree)."""

import re

from pathlib import Path

import yaml

UTF8_BOM = b"\xef\xbb\xbf"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s), for components that ship more than one independently-versioned
# image — now lives in charts/podiumd/etc/settings.yaml's own
# "component_resolution.image_paths" (see lib.settings.
# component_resolution_image_paths and that file's own comment for the
# zgw-office-addin/keycloak-operator/openbao/internetaakafhandeling/
# kiss-chart/eck-operator reasoning), with "component_resolution.
# default_image_paths" (lib.settings.component_resolution_default_
# image_paths) as the fallback for any unregistered component.
# component_image_paths/image_paths_for below resolve them.


def get_path(node, dotted_path):
    """The value at `dotted_path` (e.g. "openzaak.image.tag") inside the
    parsed values-tree `node`, or None if any segment is missing or a
    non-dict is encountered before the path is fully consumed."""
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def replace_scalar_value(line, new_value):
    """Replace a "key: <value>" line's scalar value, preserving indent, key,
    quote style, any "&anchor" tag (e.g. "tag: &keycloakImageVersion
    "26.7.2""), and any trailing comment. Used to bump a version/tag pin in
    place without a full yaml.safe_load+dump round trip, which would lose
    comments and reformat the rest of the file.

    The "&anchor" preservation matters even though this function itself
    has no idea whether anything ELSE in the file aliases this exact
    line via "*anchor" (see update-component-version's own is_alias_
    reference_line, which handles the ALIAS side of this — a line that
    only ever *reads* an anchor's value, never defines one, and must be
    skipped rather than written at all): dropping the anchor tag here,
    on the DEFINING line itself, would silently sever any "*anchor"
    reference elsewhere in the same file, turning it into a YAML parse
    error (an alias to an undefined anchor) on the very next load —
    confirmed empirically before this fix (a bare "tag: &keycloakImage
    Version "26.7.2"" line came back as "tag: 26.7.3", the anchor tag
    gone entirely)."""
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


def values_key_of(dep: dict) -> str:
    """The values.yaml key of a Chart.yaml dependency: its alias, or its
    name when it has no (or an empty) alias."""
    return dep.get("alias") or dep["name"]


def dep_for_values_key(deps: list[dict], values_key: str) -> dict | None:
    """The Chart.yaml dependency whose values_key_of equals `values_key`,
    or None when no dependency owns that key (e.g. an orphan top-level
    values.yaml block with no separate chart, like frankgateway)."""
    return next((dep for dep in deps if values_key_of(dep) == values_key), None)


def find_dependency(deps, name_or_alias):
    """The Chart.yaml dependency entry matching this name or alias, or None
    if there isn't one — pure lookup, no I/O; callers load `deps` themselves
    (usually `chart_yaml["dependencies"]`) and decide how to report a miss.
    An exact match wins; otherwise the match ignores case. Exits when
    more than one dependency matches ignoring case."""
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


def require_dependency(chart_yaml: Path, name_or_alias: str) -> dict:
    """find_dependency on `chart_yaml`'s dependencies; exits with an
    error naming `chart_yaml` when none matches."""
    deps = yaml.safe_load(chart_yaml.read_text(encoding="utf-8"))["dependencies"]
    dep = find_dependency(deps, name_or_alias)
    if dep is None:
        msg = f"error: no dependency named or aliased '{name_or_alias}' found in {chart_yaml}"
        raise SystemExit(msg)
    return dep


def own_template_files_referencing(chart_dir, key):
    """Sorted paths (relative to chart_dir) of every file under podiumd's
    OWN templates/ that contains a literal ".Values.<key>" reference —
    deterministic text search, the same convention lib.checks.
    dead_values._own_template_subchart_refs already uses for the analogous
    ".Subcharts.<name>" question, just the other direction (which FILES
    reference a given top-level key, rather than which keys a file
    references) and for the far more common ".Values.<key>" access
    pattern. Deliberately coarse: a hit means the file references this
    top-level key SOMEWHERE, not necessarily the exact nested path a
    caller is asking about — real per-subpath attribution would need an
    actual template parse (Helm's own `include`/helper indirection
    defeats a plain text search at that finer granularity), so this
    stops at "which file(s) reference this top-level key at all" rather
    than guess any more precisely than that. [] if templates/ doesn't
    exist or nothing matches — never fabricated."""
    templates_dir = chart_dir / "templates"
    if not templates_dir.is_dir():
        return []
    pattern = re.compile(rf"\.Values\.{re.escape(key)}\b")
    return [
        str(path.relative_to(chart_dir))
        for path in sorted(templates_dir.rglob("*.yaml"))
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="replace"))
    ]


def resolve_values_path_source(chart_dir, deps, path):
    """A short, human-readable description of WHERE a values-tree
    `path`'s own top-level key actually comes from — the real Chart.yaml
    dependency chart+version it belongs to (matching alias or name, via
    find_dependency), or, for a native/orphan top-level key with no
    owning dependency at all (directly templated in podiumd's OWN
    templates/*.yaml — e.g. "apiproxy", "frankgateway", "keycloak",
    "global"), which of podiumd's own local template file(s) actually
    reference it (see own_template_files_referencing) — so a reader
    knows exactly where to look instead of grepping by hand,
    deterministically either way, never a name-based guess. Shared by
    every caller that needs to attribute a values-tree path back to its
    source (lib.checks.digest_pinning's own shared-image-usage report and
    check_subchart_image_visibility's findings) so the two can never
    describe the same thing differently."""
    dep = find_dependency(deps, path[0])
    if dep is not None:
        return f"chart {dep['name']}@{dep['version']}"
    files = own_template_files_referencing(chart_dir, path[0])
    if files:
        return f"local: {', '.join(files)}"
    return "local: no referencing template found"


def find_app_versions(values, values_key, image_paths):
    """[(image_path, tag), ...] for every image_paths entry (see
    image_paths_for) that has an explicit tag override under
    values[values_key] — empty if the component relies entirely on its
    chart's own image defaults. Used by show-component-baseline-version,
    via component_state_at_baseline below — show-image-baseline-version
    resolves a single image pin directly instead (lib.image.version.
    resolve_scoped_matches), never a whole component's app-version list,
    so it has no need for this."""
    base = values.get(values_key, {}) if isinstance(values, dict) else {}
    versions = []
    for path in image_paths:
        tag = get_path(base, f"{path}.tag")
        if tag:
            versions.append((path, tag))
    return versions


def version_of(tag):
    """The version half of a tag string, dropping any trailing
    "@sha256:<digest>" suffix — a bare, non-digest-pinned tag is returned
    unchanged."""
    return tag.split("@", 1)[0]


KEY_LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[\w.\-]+):(?:\s|$)")


def dotted_key_path(lines, line_index):
    """The dotted path of keys enclosing lines[line_index] (inclusive),
    reconstructed purely from indentation — e.g. "openzaak.image.tag" for
    a "tag:" line nested under "openzaak: > image:". A plain-text
    stand-in for a full YAML-document walk, used by digest-pin scanning
    (lib.image.digests/fix-image-digests), which already has the exact
    source line (and its digest/comment) from a regex match on raw
    `lines` — a full re-parse would lose that line-number association."""
    stack = []
    for raw in lines[: line_index + 1]:
        m = KEY_LINE_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, m.group("key")))
    return ".".join(key for _, key in stack)


def strip_registry_host(url):
    """Drop the leading registry host from an image url, keep the rest —
    the same rule as scripts/mirror-strip-registry.py's own
    strip_registry (this chart's images-manifest naming convention, see
    docs/images/acr-mirror-naming.md): a first path segment counts as a
    registry host when it contains "." or ":" (docker.io, quay.io,
    ghcr.io, gcr.io, host:port, ...) or is "localhost"; anything else
    (already-bare "library/redis") is returned unchanged. Duplicated
    here rather than imported — that script lives outside this
    package's own lib/ layout, and the rule is small and stable enough
    not to be worth reaching across for."""
    url = url.strip().split("@", 1)[0]
    head, _, rest = url.partition("/")
    if rest and ("." in head or ":" in head or head == "localhost"):
        return rest
    return url


def find_images(node, path=""):
    """Recursively walk a parsed values.yaml tree, yielding (path, repository,
    tag) for every dict that has both a "repository" and a "tag" key."""
    images = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            repo, tag = node["repository"], node["tag"]
            if repo and tag not in (None, ""):
                images.append((path or "(root)", repo, tag))
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            images.extend(find_images(value, child_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            images.extend(find_images(item, f"{path}[{i}]"))
    return images
