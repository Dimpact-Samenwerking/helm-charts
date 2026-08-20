#!/usr/bin/env python3
"""
Bump a component's app image version and Helm chart version in
charts/podiumd/Chart.yaml + values.yaml — but only after verify-component-
version.py confirms both versions actually exist upstream. Refuses to touch
either file if that verification fails.

Usage:
    update-component-version.py <component> <app-version> <chart-version>

Examples:
    update-component-version.py zac 5.4.3 1.0.297
    update-component-version.py zgw-office-addin v0.9.352 0.0.92

Writes:
  - charts/podiumd/Chart.yaml: the dependency's "version:" field
  - charts/podiumd/values.yaml: the app's own image "tag:" field(s)
    (COMPONENT_IMAGE_PATHS below — same convention as verify-component-
    version.py), set to "<app-version>@sha256:<digest>" using the digest
    verify-component-version.py just confirmed upstream.

Every other byte in both files is left untouched — only the "version:" /
"tag:" values change, not formatting, comments, or quoting style. Refuses
to write if a target line can't be located unambiguously.

After writing, re-render the chart (verify-podiumd.py or /helm-render-all)
to confirm before committing.
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
VERIFY_SCRIPT = SCRIPT_DIR / "verify-component-version.py"
CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"
VALUES_YAML = SCRIPT_DIR.parents[0] / "values.yaml"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s) — must stay in sync with verify-component-version.py's copy.
COMPONENT_IMAGE_PATHS = {
    "zgw-office-addin": ["frontend.image", "backend.image"],
}
DEFAULT_IMAGE_PATHS = ["image"]

MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)
TOKEN_ENDPOINTS = {
    "docker.io": "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
    "ghcr.io": "https://ghcr.io/token?scope=repository:{repo}:pull",
}
MANIFEST_HOSTS = {
    "docker.io": "registry-1.docker.io",
}


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    for dep in deps:
        if dep["name"] == name_or_alias or dep.get("alias") == name_or_alias:
            return dep
    raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")


def get_path(node, dotted_path):
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def parse_repo(repository):
    """Split a Docker-style repository string into (registry_host, repo_path)
    using the standard Docker convention: the first path segment is a
    registry host only if it contains a "." or ":" (or is "localhost");
    otherwise the whole string is a Docker Hub repository — official images
    with no namespace (e.g. "python") live under "library/" on the registry
    API even though that prefix is omitted in the human-readable form."""
    first, sep, _ = repository.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first, repository[len(first) + 1:]
    if not sep:
        return "docker.io", f"library/{repository}"
    return "docker.io", repository


def registry_tag_exists(registry_host, repo, tag):
    """Return (exists, digest) for <repo>:<tag> on the given registry host,
    using an anonymous pull token where the registry requires one — same
    flow as /fetch-image-digest."""
    headers = {"Accept": MANIFEST_ACCEPT}
    token_url_tmpl = TOKEN_ENDPOINTS.get(registry_host)
    if token_url_tmpl:
        token = json.loads(urllib.request.urlopen(token_url_tmpl.format(repo=repo)).read())["token"]
        headers["Authorization"] = f"Bearer {token}"
    api_host = MANIFEST_HOSTS.get(registry_host, registry_host)
    req = urllib.request.Request(f"https://{api_host}/v2/{repo}/manifests/{tag}", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return True, resp.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        raise


def find_block_end(lines, block_start, indent):
    """The exclusive end index of the block starting at block_start (a key
    line at `indent`): the next non-blank, non-comment line at indent <=
    that level, or EOF."""
    for i in range(block_start + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip(" ")) <= indent:
            return i
    return len(lines)


def find_child_key_line(lines, key, parent_indent, block_start, block_end):
    """The immediate child "<key>:" line inside [block_start, block_end) —
    smallest indent strictly greater than parent_indent, so a same-named key
    nested deeper inside a grandchild block is never mistaken for it."""
    key_re = re.compile(rf'^(\s*){re.escape(key)}:\s*(.*)$')
    candidates = []
    for i in range(block_start, block_end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = key_re.match(line)
        if m:
            indent = len(m.group(1))
            if indent > parent_indent:
                candidates.append((indent, i))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def locate_dotted_key_line(lines, dotted_path):
    """Walk a dotted path (e.g. "zac.opa.image.tag") down through nested
    mapping blocks, returning (line_index, indent) of the final key, or None
    if any segment can't be found unambiguously."""
    segments = dotted_path.split(".")
    indent, start, end = -1, 0, len(lines)
    idx = None
    for seg in segments:
        idx = find_child_key_line(lines, seg, indent, start, end)
        if idx is None:
            return None
        indent = len(lines[idx]) - len(lines[idx].lstrip(" "))
        start = idx + 1
        end = find_block_end(lines, idx, indent)
    return idx, indent


def replace_scalar_value(line, new_value):
    """Replace a "key: <value>" line's scalar value, preserving indent, key,
    quote style, and any trailing comment."""
    m = re.match(r'^(?P<indent>\s*)(?P<key>[^:\n]+:)\s*(?P<quote>["\']?)'
                 r'(?P<value>.*?)(?P=quote)\s*(?P<comment>#.*)?\s*$', line)
    if not m:
        raise SystemExit(f"error: could not parse line for replacement: {line!r}")
    quote = m.group("quote")
    comment = f"  {m.group('comment')}" if m.group("comment") else ""
    return f"{m.group('indent')}{m.group('key')} {quote}{new_value}{quote}{comment}\n"


def update_chart_yaml(chart_name, new_chart_version):
    lines = CHART_YAML.read_text(encoding="utf-8").splitlines(keepends=True)
    entry_re = re.compile(r'^(\s*)-\s*name:\s*(\S+)\s*$')
    block = None
    for i, line in enumerate(lines):
        m = entry_re.match(line)
        if m and m.group(2) == chart_name:
            block = (i, len(m.group(1)))
            break
    if block is None:
        raise SystemExit(f"error: could not find '- name: {chart_name}' in {CHART_YAML}")
    entry_line, entry_indent = block
    block_end = find_block_end(lines, entry_line, entry_indent)
    version_line = find_child_key_line(lines, "version", entry_indent, entry_line, block_end)
    if version_line is None:
        raise SystemExit(f"error: could not find 'version:' under '- name: {chart_name}' in {CHART_YAML}")

    old_line = lines[version_line]
    lines[version_line] = replace_scalar_value(old_line, new_chart_version)
    CHART_YAML.write_text("".join(lines), encoding="utf-8")
    return old_line.strip(), lines[version_line].strip()


def update_values_yaml(values_key, image_paths, new_tags_by_path):
    lines = VALUES_YAML.read_text(encoding="utf-8").splitlines(keepends=True)
    changes = []
    for path in image_paths:
        dotted = f"{values_key}.{path}.tag"
        located = locate_dotted_key_line(lines, dotted)
        if located is None:
            raise SystemExit(f"error: could not find '{dotted}' in {VALUES_YAML}")
        line_idx, _ = located
        old_line = lines[line_idx]
        lines[line_idx] = replace_scalar_value(old_line, new_tags_by_path[path])
        changes.append((dotted, old_line.strip(), lines[line_idx].strip()))
    VALUES_YAML.write_text("".join(lines), encoding="utf-8")
    return changes


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    component, app_version, chart_version = sys.argv[1], sys.argv[2], sys.argv[3]

    print(f"=== Running verify-component-version.py {component} {app_version} {chart_version} ===")
    result = subprocess.run([sys.executable, str(VERIFY_SCRIPT), component, app_version, chart_version])
    if result.returncode != 0:
        print()
        print("FAIL: verify-component-version.py did not pass — refusing to change any files")
        sys.exit(1)

    dep = find_dependency(component)
    chart_name = dep["name"]
    values_key = dep.get("alias", dep["name"])
    image_paths = COMPONENT_IMAGE_PATHS.get(component, DEFAULT_IMAGE_PATHS)

    print()
    print(f"=== Resolving digests for {component} {app_version} ===")
    values = yaml.safe_load(VALUES_YAML.read_text(encoding="utf-8")) or {}
    new_tags_by_path = {}
    for path in image_paths:
        repo = get_path(values, f"{values_key}.{path}.repository")
        if not isinstance(repo, str) or not repo:
            print(f"error: no repository found at {values_key}.{path}.repository in {VALUES_YAML}")
            sys.exit(1)
        host, repo_path = parse_repo(repo)
        exists, digest = registry_tag_exists(host, repo_path, app_version)
        if not exists or not digest:
            print(f"error: {host}/{repo_path}:{app_version} unexpectedly missing on re-check")
            sys.exit(1)
        new_tags_by_path[path] = f"{app_version}@{digest}"
        print(f"  {values_key}.{path}: {host}/{repo_path}:{app_version} -> {digest}")

    print()
    print(f"=== Writing {CHART_YAML} ===")
    old_v, new_v = update_chart_yaml(chart_name, chart_version)
    print(f"  {old_v}  ->  {new_v}")

    print()
    print(f"=== Writing {VALUES_YAML} ===")
    for dotted, old_v, new_v in update_values_yaml(values_key, image_paths, new_tags_by_path):
        print(f"  {dotted}:")
        print(f"    {old_v}")
        print(f"    {new_v}")

    print()
    print("Done. Re-render the chart to confirm (verify-podiumd.py or /helm-render-all) before committing.")


if __name__ == "__main__":
    main()
