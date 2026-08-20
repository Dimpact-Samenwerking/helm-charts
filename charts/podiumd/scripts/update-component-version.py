#!/usr/bin/env python3
"""
Bump a component's app image version and Helm chart version in
charts/podiumd/Chart.yaml + values.yaml — but only after verify-component-
version.py confirms both versions actually exist upstream. Refuses to touch
either file if that verification fails.

Either version (or both) may already be at the requested value — that's
not an error: whichever one is unchanged is reported and left untouched,
and only the file(s) that actually need a change get written. If both are
already current, nothing is written at all.

Usage:
    update-component-version.py <component> <app-version> <chart-version>

Examples:
    update-component-version.py zac 5.4.3 1.0.297
    update-component-version.py zgw-office-addin v0.9.352 0.0.92
    update-component-version.py openformulieren 3.5.6 1.12.0
        # if 1.12.0 is already the pinned chart version, Chart.yaml is left
        # untouched and only values.yaml's image tag is bumped

Writes:
  - charts/podiumd/Chart.yaml: the dependency's "version:" field
  - charts/podiumd/values.yaml: the app's own image "tag:" field(s)
    (COMPONENT_IMAGE_PATHS below — same convention as verify-component-
    version.py), set to "<app-version>@sha256:<digest>".

The upstream repository for each image path is read from the TARGET chart
version's own values.yaml (pulled via helm, same as verify-component-
version.py) rather than podiumd's own values.yaml — podiumd's override
often leaves "repository:" unset entirely, relying on the sub-chart's
default (e.g. openformulieren).

Every other byte in both files is left untouched — only the "version:" /
"tag:" values change, not formatting, comments, or quoting style. Refuses
to write if a target line can't be located unambiguously.

After writing, re-render the chart (verify-podiumd.py or /helm-render-all)
to confirm before committing.

Also updates the docs for the current podiumd target version (Chart.yaml's
own "version:"), if they exist (run set-doc-baseline.py first if not):
  - <baseline>-to-<target>-upgrade.md: the component's "Component versions"
    table row (added if not yet mentioned, updated in place if it is) and,
    for a brand-new mention, a "### <component> <old> → <new> ..." Changes
    section with the usual Helm-chart/image-tag-pin bullets.
  - <baseline>-to-<target>-values-deltas.md: a bullet describing the app/
    chart bump, plus one line per values.yaml key that was added, removed,
    or renamed under this component between the old and new values.yaml
    (backtick-quoted, matching the convention verify-podiumd.py checks for).
  - docs/images/images-<target>.yaml, if an image tag actually changed: the
    "# <N> changes:" numbered header list (added or updated), and any
    existing entry's version/digest/comment (updated in place). An entry
    that doesn't exist yet is NOT invented — the correct "name:" is an ACR
    mirror slug that can't be derived here (see docs/images/acr-mirror-
    naming.md); the exact url/version/digest to add are printed instead.

The component's display name in all of this is its values.yaml key (e.g.
"zgw-office-addin") — not a polished label like "ZGW Office Add-in" — since
there's no reliable source for that mapping. Rename it by hand afterward if
you want the polished form.
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import find_dependency as _find_dependency
from lib.chart import get_path, pull_chart_values
from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.procutil import run
from lib.registry import parse_repo, registry_tag_exists
from lib.upgradedoc import (
    canonical_version_cell, diff_keys, extract_source_version, find_grouped_preceding_comment_line,
    normalize_name, normalize_version, pair_renames, parse_upgrade_doc_rows, replace_version_pair,
    resolve_entry_path,
)

VERIFY_SCRIPT = SCRIPT_DIR / "verify-component-version.py"
CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"
VALUES_YAML = SCRIPT_DIR.parents[0] / "values.yaml"
DOC_DIR = SCRIPT_DIR.parents[0] / "docs" / "_UPGRADE_PATHS"
IMAGES_DIR = SCRIPT_DIR.parents[0] / "docs" / "images"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s) — must stay in sync with verify-component-version.py's copy.
COMPONENT_IMAGE_PATHS = {
    "zgw-office-addin": ["frontend.image", "backend.image"],
}
DEFAULT_IMAGE_PATHS = ["image"]

NUMBER_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen"]
CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)(?P<count_word>\w+)\s+changes?:\s*$", re.IGNORECASE)
CHANGES_ITEM_RE = re.compile(r"^#\s*(?P<num>\d+)\.\s+(?P<rest>.+)$")
NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    dep = _find_dependency(deps, name_or_alias)
    if dep is None:
        raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")
    return dep


def resolve_repos(dep, chart_version, paths):
    """Pull the target chart version and read ITS OWN values.yaml to find
    each path's default "repository:" — podiumd's own values.yaml may leave
    "repository:" entirely unset, relying on the sub-chart's default."""
    sub_values = pull_chart_values(dep, chart_version)
    repos = {}
    for path in paths:
        repo = get_path(sub_values, f"{path}.repository")
        if not isinstance(repo, str) or not repo:
            raise SystemExit(
                f"error: no repository found at {path}.repository in {dep['name']}'s own values.yaml"
            )
        repos[path] = repo
    return repos


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


def current_chart_version():
    return str(yaml.safe_load(CHART_YAML.read_text(encoding="utf-8"))["version"])


def images_manifest_path(target):
    return IMAGES_DIR / f"images-{target}.yaml"


def find_baseline_docs(target):
    """(baseline, upgrade_path, values_deltas_path) for the single
    <baseline>-to-<target>-*.md doc set for this podiumd version, or
    (None, None, None) if the upgrade doc doesn't exist yet — run
    set-doc-baseline.py first to scaffold it."""
    matches = list(DOC_DIR.glob(f"*-to-{target}-upgrade.md"))
    if len(matches) != 1:
        return None, None, None
    m = re.match(rf"^(?P<baseline>\d+\.\d+\.\d+)-to-{re.escape(target)}-upgrade\.md$", matches[0].name)
    if not m:
        return None, None, None
    baseline = m.group("baseline")
    values_deltas_path = DOC_DIR / f"{baseline}-to-{target}-values-deltas.md"
    return baseline, matches[0], (values_deltas_path if values_deltas_path.is_file() else None)


def load_baseline_values(baseline):
    """values.yaml as it actually was at the release these docs are written
    against (resolved via git) — NOT "before this script's own edit". This
    script only ever writes an image tag, never a schema change, so a
    before/after-this-run comparison would always be empty regardless of
    what actually changed for this component since the real baseline;
    comparing against the true baseline is the only way to catch a values.yaml
    schema change (new/removed/renamed key) made by hand as part of this hop,
    whenever during the hop that edit happened. Returns None if the baseline
    can't be resolved (e.g. that release hasn't been tagged yet) — callers
    then skip key-change detection rather than comparing against nothing
    meaningful."""
    repo_root = find_repo_root(VALUES_YAML.parent)
    if repo_root is None:
        return None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(baseline))
    if ref is None:
        return None
    rel_values_path = VALUES_YAML.relative_to(repo_root)
    return git_show_yaml(repo_root, ref, str(rel_values_path))


def find_component_row(rows, friendly):
    norm_friendly = normalize_name(friendly)
    for row in rows:
        if norm_friendly in normalize_name(row["name"]):
            return row
    return None


def update_component_table(text, friendly, old_app, new_app, old_chart, new_chart):
    """Update this component's "Component versions" table row if it's
    already mentioned, or append a new row if it isn't. Returns
    (new_text, action) where action is "updated" or "added" (or None if the
    doc has no table at all to append to)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)

    app_cell = canonical_version_cell(old_app, new_app) if old_app else new_app
    chart_cell = canonical_version_cell(old_chart, new_chart) if old_chart else new_chart

    if row is not None:
        old_line = lines[row["line_index"]]
        cells = [c.strip() for c in old_line.strip().strip("|").split("|")]
        cells[1] = app_cell
        cells[2] = chart_cell
        suffix = "\n" if old_line.endswith("\n") else ""
        lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + suffix
        return "".join(lines), "updated"

    new_row_line = f"| {friendly} | {app_cell} | {chart_cell} | - |\n"
    if rows:
        insert_at = rows[-1]["line_index"] + 1
    else:
        insert_at = None
        for i, line in enumerate(lines):
            if re.match(r"^\|\s*:?-+:?\s*\|", line.strip()):
                insert_at = i + 1
        if insert_at is None:
            return text, None
    lines.insert(insert_at, new_row_line)
    return "".join(lines), "added"


def find_changes_section(text, friendly):
    """Whether a "### ..." heading already mentions this component."""
    norm_friendly = normalize_name(friendly)
    for line in text.splitlines():
        m = re.match(r"^###\s+(.+)$", line)
        if m and norm_friendly in normalize_name(m.group(1)):
            return True
    return False


def make_changes_section(friendly, target, chart_name, values_key, old_app, new_app,
                          old_chart, new_chart, image_paths):
    chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
    chart_suffix = f" (chart {old_chart} → {new_chart})" if chart_changed else f" (chart {new_chart}, unchanged)"
    lines = [f"### {friendly} {old_app} → {new_app}{chart_suffix}\n\n"]
    lines.append(f"PodiumD {target} upgrades **{friendly}** from app version {old_app}\n")
    lines.append(f"to {new_app}.\n\n")
    if chart_changed:
        lines.append(f"- Helm chart `{chart_name}` `{old_chart}` → `{new_chart}` in\n")
        lines.append("  `charts/podiumd/Chart.yaml`.\n")
    for path in image_paths:
        lines.append(f"- Image tag pin `{values_key}.{path}.tag` `{old_app}` → `{new_app}` in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    lines.append(f"- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def insert_changes_section(text, section_text):
    """Append section_text as a new "### ..." block at the end of the
    "## Changes" section (right before the next "## " heading, or EOF)."""
    lines = text.splitlines(keepends=True)
    changes_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Changes":
            changes_idx = i
            break
    if changes_idx is None:
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text + section_text
    insert_at = len(lines)
    for i in range(changes_idx + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            insert_at = i
            break
    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def values_delta_bullet(friendly, old_app, new_app, old_chart, new_chart):
    app_changed = normalize_version(old_app) != normalize_version(new_app)
    chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
    app_bit = f"`{old_app} → {new_app}`" if app_changed else f"`{new_app}` (unchanged)"
    chart_bit = f"`{old_chart} → {new_chart}`" if chart_changed else f"`{new_chart}`, unchanged"
    note = "image tag only" if not chart_changed else "chart + image tag"
    return f"- **{friendly}** app {app_bit} (chart {chart_bit}) — {note}.\n"


def describe_key_changes(values_key, baseline_subtree, current_subtree):
    """One "- Key `<dotted>` was added/removed/renamed to `<dotted>`." line
    per top-level key change under this component — backtick-quoted,
    matching the convention verify-podiumd.py's own check looks for.

    Paths passed to diff_keys/pair_renames are relative to the subtree
    itself (path=()), NOT prefixed with values_key — pair_renames's own
    lookups walk baseline_subtree/current_subtree directly, so a
    values_key-prefixed path would never resolve (silently comparing None
    to None, which can pair completely unrelated keys as a false rename).
    values_key is prepended only for the displayed dotted string."""
    diffs = list(diff_keys(baseline_subtree, current_subtree))
    added = [p for kind, p in diffs if kind == "added"]
    removed = [p for kind, p in diffs if kind == "removed"]
    renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)

    def dotted(path):
        return ".".join((values_key,) + path)

    lines = []
    for path in added:
        lines.append(f"- Key `{dotted(path)}` was added.\n")
    for path in removed:
        lines.append(f"- Key `{dotted(path)}` was removed.\n")
    for old_path, new_path in renamed:
        lines.append(f"- Key `{dotted(old_path)}` was renamed to `{dotted(new_path)}`.\n")
    return lines


def append_to_doc(text, new_lines):
    if not new_lines:
        return text
    if text and not text.endswith("\n\n"):
        text = text.rstrip("\n") + "\n\n"
    return text + "".join(new_lines)


def values_tree_path_for(values_key, image_path):
    """The find_image_tag_paths key for a COMPONENT_IMAGE_PATHS-style dotted
    path (e.g. "frontend.image") under this component's values_key."""
    segments = image_path.split(".")
    return (values_key,) + tuple(segments[:-1])


def find_matching_images_entry(entries, entry_line_indices, target_path):
    for index, (entry, line_idx) in enumerate(zip(entries, entry_line_indices)):
        if resolve_entry_path(entry["name"], [target_path]) == target_path:
            return entry, line_idx, index
    return None, None, None


def update_images_manifest_entry(lines, entries, entry_line_indices, index, new_tag, values_key):
    """Update an existing entry's version/digest fields and its preceding
    comment's version pair in place. The comment may be shared across
    several of this component's entries (e.g. zgw-office-addin's frontend +
    backend, listed as one block under one comment) — found via the same
    top-level-component grouping as find_grouped_preceding_comment_line,
    not just the line directly above this entry. Returns True if anything
    changed."""
    entry_line_idx = entry_line_indices[index]
    new_app_version, digest = new_tag.split("@", 1)
    block_end = len(lines)
    for i in range(entry_line_idx + 1, len(lines)):
        if re.match(r"^-\s*name:", lines[i]) or not lines[i].strip():
            block_end = i
            break

    changed = False
    for i in range(entry_line_idx, block_end):
        m = re.match(r"^\s*(version|digest):", lines[i])
        if not m:
            continue
        new_value = new_app_version if m.group(1) == "version" else digest
        lines[i] = replace_scalar_value(lines[i], new_value)
        changed = True

    def component_of(entry):
        return values_key if normalize_name(values_key) in normalize_name(entry["name"]) else None

    def same_group(entry_a, entry_b):
        return (component_of(entry_a) is not None
                and component_of(entry_a) == component_of(entry_b)
                and entry_a.get("version") == entry_b.get("version"))

    comment_idx = find_grouped_preceding_comment_line(
        lines, entries, entry_line_indices, index, same_group)
    if comment_idx is not None:
        current_source = extract_source_version(lines[comment_idx])
        if current_source:
            lines[comment_idx] = replace_version_pair(lines[comment_idx], current_source, new_app_version)
            changed = True
    return changed


def update_images_manifest(images_path, friendly, values_key, old_app, new_app, old_chart, new_chart,
                            paths_to_update, repos, new_tags_by_path):
    """Update the "# <N> changes:" header list and any existing entries'
    version/digest/comment for this component. Returns (changes_action,
    entry_names_updated, missing_entries) where missing_entries is
    [(image_path, repo, new_tag), ...] for components with no existing
    entry — never invented, since the correct "name:" (ACR mirror slug)
    can't be derived here."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    header_idx = None
    for i, line in enumerate(lines):
        if CHANGES_HEADER_RE.match(line):
            header_idx = i
            break

    changes_action = None
    if header_idx is not None:
        item_indices = []
        block_end = header_idx + 1
        for i in range(header_idx + 1, len(lines)):
            if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
                break
            block_end = i + 1
            if re.match(r"^#\s*\d+\.", lines[i]):
                item_indices.append(i)

        norm_friendly = normalize_name(friendly)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_friendly in normalize_name(m.group("rest")):
                match_idx = idx
                break

        chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
        chart_bit = f"{old_chart} -> {new_chart}" if chart_changed else f"{new_chart}, unchanged"
        item_text = f"{friendly} {old_app} -> {new_app} (chart {chart_bit})."

        if match_idx is not None:
            m = CHANGES_ITEM_RE.match(lines[match_idx])
            lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
            changes_action = "updated"
        else:
            new_num = len(item_indices) + 1
            insert_at = block_end if item_indices else header_idx + 1
            lines.insert(insert_at, f"#   {new_num}. {item_text}\n")
            count_word = NUMBER_WORDS[new_num] if new_num < len(NUMBER_WORDS) else str(new_num)
            noun = "change" if new_num == 1 else "changes"
            header_m = CHANGES_HEADER_RE.match(lines[header_idx])
            lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
            changes_action = "added"

    entries = yaml.safe_load("".join(lines)) or []
    if not isinstance(entries, list):
        entries = []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]

    entry_updates, missing_entries = [], []
    for path in paths_to_update:
        target_path = values_tree_path_for(values_key, path)
        entry, entry_idx, index = find_matching_images_entry(entries, entry_line_indices, target_path)
        if entry is None:
            missing_entries.append((path, repos[path], new_tags_by_path[path]))
            continue
        if update_images_manifest_entry(
                lines, entries, entry_line_indices, index, new_tags_by_path[path], values_key):
            entry_updates.append(entry["name"])

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates, missing_entries


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
    chart_unchanged = str(dep["version"]) == str(chart_version)
    if chart_unchanged:
        print(f"Chart version already {chart_version} — unchanged")
    else:
        print(f"Chart version: {dep['version']} -> {chart_version}")

    values = yaml.safe_load(VALUES_YAML.read_text(encoding="utf-8")) or {}
    paths_to_update = []
    old_app_by_path = {}
    for path in image_paths:
        current_tag = get_path(values, f"{values_key}.{path}.tag") or ""
        current_version = current_tag.split("@", 1)[0]
        old_app_by_path[path] = current_version or None
        if current_version == app_version:
            print(f"{values_key}.{path}: app version already {app_version} — unchanged")
        else:
            print(f"{values_key}.{path}: app version {current_version or '(none)'} -> {app_version}")
            paths_to_update.append(path)

    if chart_unchanged and not paths_to_update:
        print()
        print("Nothing to update — component is already at the requested versions.")
        sys.exit(0)

    new_tags_by_path = {}
    if paths_to_update:
        print()
        print(f"=== Resolving digests for {component} {app_version} (chart {chart_version}) ===")
        repos = resolve_repos(dep, chart_version, paths_to_update)
        for path in paths_to_update:
            host, repo_path = parse_repo(repos[path])
            exists, digest = registry_tag_exists(host, repo_path, app_version)
            if not exists or not digest:
                print(f"error: {host}/{repo_path}:{app_version} unexpectedly missing on re-check")
                sys.exit(1)
            new_tags_by_path[path] = f"{app_version}@{digest}"
            print(f"  {values_key}.{path}: {host}/{repo_path}:{app_version} -> {digest}")

    if not chart_unchanged:
        print()
        print(f"=== Writing {CHART_YAML} ===")
        old_v, new_v = update_chart_yaml(chart_name, chart_version)
        print(f"  {old_v}  ->  {new_v}")

    if paths_to_update:
        print()
        print(f"=== Writing {VALUES_YAML} ===")
        for dotted, old_v, new_v in update_values_yaml(values_key, paths_to_update, new_tags_by_path):
            print(f"  {dotted}:")
            print(f"    {old_v}")
            print(f"    {new_v}")

    target = current_chart_version()
    friendly = values_key
    old_chart = str(dep["version"])
    old_app = old_app_by_path.get(image_paths[0])

    baseline, upgrade_path, values_deltas_path = find_baseline_docs(target)
    if upgrade_path is None:
        print()
        print(f"No upgrade doc found for target {target} — run set-doc-baseline.py first "
              f"to scaffold it; skipping doc updates.")
    else:
        text = upgrade_path.read_text(encoding="utf-8")
        new_text, table_action = update_component_table(text, friendly, old_app, app_version,
                                                          old_chart, chart_version)
        section_exists = find_changes_section(new_text, friendly)
        section_added = False
        if table_action == "added" and not section_exists:
            section = make_changes_section(friendly, target, chart_name, values_key, old_app, app_version,
                                            old_chart, chart_version, paths_to_update)
            new_text = insert_changes_section(new_text, section)
            section_added = True

        if table_action is not None:
            upgrade_path.write_text(new_text, encoding="utf-8")
            print()
            print(f"=== Updating {upgrade_path.name} ===")
            print(f"  {table_action} table row")
            if section_added:
                print(f"  added '### {friendly} ...' Changes section")
            elif table_action == "updated" and section_exists:
                print(f"  note: a '### {friendly} ...' Changes section already exists — "
                      f"update its version numbers by hand if needed")

    if values_deltas_path is not None:
        text = values_deltas_path.read_text(encoding="utf-8")
        new_lines = [values_delta_bullet(friendly, old_app, app_version, old_chart, chart_version)]
        current_values_after = yaml.safe_load(VALUES_YAML.read_text(encoding="utf-8")) or {}
        current_subtree = current_values_after.get(values_key, {})
        baseline_values_at_release = load_baseline_values(baseline)
        if baseline_values_at_release is None:
            print()
            print(f"  note: could not resolve baseline {baseline} to a git ref — skipping "
                  f"added/removed/renamed key detection for values-deltas.md")
        else:
            baseline_subtree = (baseline_values_at_release.get(values_key, {})
                                 if isinstance(baseline_values_at_release, dict) else {})
            new_lines.extend(describe_key_changes(values_key, baseline_subtree, current_subtree))

        no_changes_claimed = bool(NO_CHANGES_CLAIMED_RE.search(text))
        values_deltas_path.write_text(append_to_doc(text, new_lines), encoding="utf-8")
        print()
        print(f"=== Updating {values_deltas_path.name} ===")
        for line in new_lines:
            print(f"  {line.rstrip()}")
        if no_changes_claimed:
            print("  note: doc claims 'no gemeente podiumd.yml changes are required' — that's about "
                  "gemeente ACTION, not about whether anything changed, so it may still hold; "
                  "double-check it's still true now that this bullet's been added")
    elif upgrade_path is not None:
        print()
        print(f"No values-deltas.md found for baseline {baseline} — skipping that update.")

    if paths_to_update:
        images_path = images_manifest_path(target)
        if images_path.is_file():
            changes_action, entry_updates, missing_entries = update_images_manifest(
                images_path, friendly, values_key, old_app, app_version, old_chart, chart_version,
                paths_to_update, repos, new_tags_by_path,
            )
            print()
            print(f"=== Updating {images_path.name} ===")
            if changes_action:
                print(f"  {changes_action} 'changes:' list entry")
            for name in entry_updates:
                print(f"  updated entry '{name}'")
            if missing_entries:
                print("  No existing entry for the following — add manually (see "
                      "docs/images/acr-mirror-naming.md for the correct 'name:' ACR mirror slug):")
                for path, repo, new_tag in missing_entries:
                    new_app_version, digest = new_tag.split("@", 1)
                    print(f"    # {friendly} — {old_app_by_path.get(path) or '(none)'} -> {new_app_version}")
                    print("    - name: <ACR-mirror-name>")
                    print(f"      url: {repo}")
                    print(f'      version: "{new_app_version}"')
                    print(f'      digest: "{digest}"')
        else:
            print()
            print(f"No images-{target}.yaml found — skipping that update.")

    print()
    print("Done. Re-render the chart to confirm (verify-podiumd.py or /helm-render-all) before committing.")


if __name__ == "__main__":
    main()
