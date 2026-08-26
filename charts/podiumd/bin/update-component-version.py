#!/usr/bin/env python3
"""
Bump a component's app image version and Helm chart version in
charts/podiumd/Chart.yaml + values.yaml — but only after verify-component-
version.py confirms both versions actually exist upstream. Refuses to touch
either file if that verification fails; whichever version is already at
the requested value is left untouched (not an error).

Also updates the docs for the current podiumd target version, if they
exist (run set-doc-baseline.py first if not): the upgrade doc's
"Component versions" table row and Changes section, the values-deltas
doc, and docs/images/images-<target>.yaml — see find_baseline_docs,
update_component_table, and images_manifest_path for exactly what gets
rewritten vs. reported for manual review. Finally runs
update-podiumd-readme.py so README.md's values-reference table doesn't go
stale in the same commit.

The component name and the image it bumps are not the same thing (zac's
image is basename "zaakafhandelcomponent"; zgw-office-addin bumps two
distinctly-named images, frontend + backend) — an image path with an
explicit "repository:" of its own in values.yaml delegates its actual tag
update to lib.image_version.update_image_version (see
update-image-version.py), keyed by that path's own real basename, so an
image shared with some unrelated component gets updated everywhere it's
pinned. A path relying on a vendored sub-chart's own default repository
(nothing explicit to derive a basename from — e.g. openzaak,
openformulieren) resolves it the original way instead (pulls the target
chart version and reads its own values.yaml default).

Usage:
    update-component-version.py <component> <app-version> <chart-version>

Examples:
    update-component-version.py zac 5.4.3 1.0.297
    update-component-version.py zgw-office-addin v0.9.352 0.0.92
    update-component-version.py openformulieren 3.5.6 1.12.0
        # if 1.12.0 is already the pinned chart version, Chart.yaml is left
        # untouched and only values.yaml's image tag is bumped

After writing, re-render the chart (verify-podiumd.py or /helm-render-all)
to confirm before committing.
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import chart_version as _chart_version
from lib.chart import find_dependency as _find_dependency
from lib.chart import (
    check_image_versions, get_path, image_paths_for, pull_chart, pulled_chart_dir, replace_scalar_value,
)
from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.image_version import image_basename, update_image_version
from lib.procutil import run_script
from lib.upgradedoc import (
    append_to_doc, canonical_version_cell, describe_key_changes, extract_source_version,
    find_grouped_preceding_comment_line, normalize_name, normalize_version, parse_upgrade_doc_rows,
    replace_version_pair, resolve_entry_path,
)

UPDATE_README_SCRIPT = SCRIPT_DIR / "update-podiumd-readme.py"
CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"
VALUES_YAML = SCRIPT_DIR.parents[0] / "values.yaml"
DOC_DIR = SCRIPT_DIR.parents[0] / "docs" / "_UPGRADE_PATHS"
IMAGES_DIR = SCRIPT_DIR.parents[0] / "docs" / "images"

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


def verify_component_version(dep, image_paths, app_version, chart_version):
    """Pull the target chart version once and check both that it exists and
    that `image_paths` resolve to existing app image versions on their
    actual upstream registries — the single upfront gate main() runs before
    touching any file. Returns the pulled chart's own values.yaml (parsed)
    plus lib.chart.check_image_versions' results, so callers needing a
    fallback path's default repository (see check_image_versions) reuse
    this same pull/check instead of repeating it. Exits 1 (after printing
    a FAIL) if the chart version can't be pulled or an image version
    doesn't exist; never returns in that case."""
    chart_name = dep["name"]
    tmpdir = Path(tempfile.mkdtemp(prefix="update-component-version-"))
    try:
        print(f"=== Checking chart version {chart_version!r} for {chart_name} ===")
        ok_chart, stderr = pull_chart(dep, chart_version, tmpdir)
        status = "FOUND  " if ok_chart else "MISSING"
        suffix = f"  ({stderr})" if not ok_chart else ""
        print(f"  [{status}] {chart_name} {chart_version}{suffix}")
        if not ok_chart:
            print()
            print("FAIL: chart version does not exist — refusing to change any files")
            sys.exit(1)

        chart_dir = pulled_chart_dir(tmpdir)
        upstream_values = yaml.safe_load((chart_dir / "values.yaml").read_text(encoding="utf-8")) or {}

        print(f"\nChecking app version {app_version!r} for {dep.get('alias', chart_name)}:")
        image_results = check_image_versions(upstream_values, image_paths, app_version)
        ok_images = True
        for r in image_results:
            status = "FOUND  " if r["exists"] else "MISSING"
            suffix = f"  digest={r['digest']}" if r["digest"] else ""
            print(f"  [{status}] {r['host']}/{r['repo_path']}:{app_version}{suffix}")
            ok_images = ok_images and r["exists"]
        if not ok_images:
            print()
            print("FAIL: one or more app image versions do not exist yet — refusing to change any files")
            sys.exit(1)

        return {r["path"]: r for r in image_results}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
    return _chart_version(CHART_YAML)


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
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    component, app_version, chart_version = sys.argv[1], sys.argv[2], sys.argv[3]

    dep = find_dependency(component)
    chart_name = dep["name"]
    values_key = dep.get("alias", dep["name"])
    image_paths = image_paths_for(component)

    upstream_images = verify_component_version(dep, image_paths, app_version, chart_version)

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

    # A component's image basename is not always its own name (e.g.
    # zgw-office-addin bumps two distinctly-named images, frontend +
    # backend) — a path with an explicit "repository:" of its own in
    # values.yaml delegates to lib.image_version's basename-based update,
    # so an image shared with some unrelated component (e.g.
    # curlimages/curl, used by several unrelated init containers) gets
    # updated everywhere it's pinned, not just at this one dotted path. A
    # path relying on a vendored sub-chart's own default repository (e.g.
    # openzaak, openformulieren — nothing to derive a basename from) keeps
    # the original resolve-via-sub-chart-pull behavior instead.
    new_tags_by_path = {}
    repos = {}
    if paths_to_update:
        delegated_paths, fallback_paths = [], []
        for path in paths_to_update:
            explicit_repo = get_path(values, f"{values_key}.{path}.repository")
            (delegated_paths if isinstance(explicit_repo, str) and explicit_repo else fallback_paths).append(path)

        if delegated_paths:
            values_lines = VALUES_YAML.read_text(encoding="utf-8").splitlines()
            for path in delegated_paths:
                located = locate_dotted_key_line(values_lines, f"{values_key}.{path}.tag")
                if located is None:
                    raise SystemExit(f"error: could not find '{values_key}.{path}.tag' in {VALUES_YAML}")
                own_line = located[0] + 1  # 1-indexed, matches lib.image_version's line numbering
                repos[path] = get_path(values, f"{values_key}.{path}.repository")
                basename = image_basename(repos[path])
                print()
                print(f"=== Updating '{basename}' image pin(s) for {values_key}.{path} ===")
                changes = update_image_version(VALUES_YAML, basename, app_version)
                for c in changes:
                    print(f"  values.yaml:{c['line']}  ({c['repository']})")
                    print(f"    {c['old_version']}@{c['old_digest']}")
                    print(f"    {c['new_version']}@{c['new_digest']}")
                own_change = next(c for c in changes if c["line"] == own_line)
                new_tags_by_path[path] = f"{own_change['new_version']}@{own_change['new_digest']}"

        if fallback_paths:
            print()
            print(f"=== Using sub-chart default digests for: {', '.join(fallback_paths)} ===")
            for path in fallback_paths:
                r = upstream_images.get(path)
                if r is None or not r["exists"] or not r["digest"]:
                    raise SystemExit(
                        f"error: no repository found at {path}.repository in {dep['name']}'s own values.yaml"
                    )
                repos[path] = r["repository"]
                new_tags_by_path[path] = f"{app_version}@{r['digest']}"
                print(f"  {values_key}.{path}: {r['host']}/{r['repo_path']}:{app_version} -> {r['digest']}")
            print()
            print(f"=== Writing {VALUES_YAML} ===")
            for dotted, old_v, new_v in update_values_yaml(values_key, fallback_paths, new_tags_by_path):
                print(f"  {dotted}:")
                print(f"    {old_v}")
                print(f"    {new_v}")

    if not chart_unchanged:
        print()
        print(f"=== Writing {CHART_YAML} ===")
        old_v, new_v = update_chart_yaml(chart_name, chart_version)
        print(f"  {old_v}  ->  {new_v}")

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
    print("=== Regenerating README.md (update-podiumd-readme.py) ===")
    run_script([sys.executable, str(UPDATE_README_SCRIPT)])

    print()
    print("Done. Re-render the chart to confirm (verify-podiumd.py or /helm-render-all) before committing.")


if __name__ == "__main__":
    main()
