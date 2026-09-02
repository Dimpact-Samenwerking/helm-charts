"""Update the docs for a shared image basename's version bump — the
"Component versions" table row, "## Changes" section, values-deltas
bullet, and images-<target>.yaml entry, all keyed by the basename/
repository itself rather than any one consuming component's values-tree
path. Used only when a basename bump (lib.image_version.
update_image_version) actually touches more than one Chart.yaml
component — a bump resolving to exactly one component (e.g. via a
dependency alias like "openklant") gets the SAME full-fidelity treatment
update-component-version itself uses (lib.component_docs, real chart
version), not this module.

Convention confirmed against docs/_UPGRADE_PATHS/4.8.1-to-4.8.2-
upgrade.md: curl/nginx-unprivileged/busybox each got their own table row
(Helm chart column "-") and a "### <name> ..." Changes block listing
every place they're pinned. The row naturally sorts after every real
component — lib.upgradedoc.component_order_key's own "unmatched sorts
last" rule already produces that with no special-casing needed here,
since a bare basename never matches a Chart.yaml dependency by name."""
import re

from lib.chart import canonical_sidecar_row_names, get_path, replace_scalar_value
from lib.component_docs import (
    CHANGES_HEADER_RE, CHANGES_ITEM_RE, NUMBER_WORDS, insert_changes_section, remove_changes_section,
    update_component_table,
)
from lib.upgradedoc import (
    extract_source_version, find_image_tag_paths, find_preceding_comment_line, normalize_name,
    parse_upgrade_doc_rows, replace_version_pair,
)


def make_image_changes_section(basename, target, old_version, new_version, pinned):
    """The "### <basename> <old> → <new>" Changes block for a shared
    image basename bump. `pinned` is [(dotted_path, old_version), ...]
    for every values.yaml tag pin actually bumped (see
    lib.image_version.update_image_version's own return value) — listed
    individually rather than assuming one uniform "old" version, since a
    basename's various pins aren't guaranteed to have all started at the
    exact same one."""
    lines = [f"### {basename} {old_version} → {new_version}\n\n"]
    lines.append(f"PodiumD {target} upgrades the shared **{basename}** image to {new_version},\n")
    lines.append("pinned at:\n\n")
    for path, path_old_version in pinned:
        lines.append(f"- `{path}` `{path_old_version}` → `{new_version}`\n")
    lines.append(f"\n- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def image_delta_bullet(basename, old_version, new_version, pin_count):
    plural = "s" if pin_count != 1 else ""
    return f"- **{basename}** image `{old_version} → {new_version}` — pinned at {pin_count} place{plural} in `values.yaml`.\n"


def add_missing_sidecar_rows(text, chart_dir, deps, target_values, baseline_values, target):
    """Insert a new "Component versions" table row + matching "### ..."
    Changes section for every canonical sidecar/shared-image name (see
    lib.chart.canonical_sidecar_row_names — "<values_key> - <basename>"
    for a sidecar nested under a real dependency, bare "<basename>" for
    a shared "global" image) whose tag changed vs baseline but doesn't
    already have a row of its own. The sidecar/shared-image counterpart
    to lib.component_docs.add_missing_component_rows, which only ever
    covers a real Chart.yaml dependency's own row — this closes exactly
    the "sidecar/shared image ... changed vs ... but has no row" gap
    lib.docs_consistency.check_docs_consistency's own canonical_names
    loop reports.

    Always uses make_image_changes_section's own "shared image" prose/
    heading shape (chart column "-", no Helm-chart mention at all) —
    even for a sidecar nested under a real dependency — since that's the
    shape this chart's own docs actually use for every canonical sidecar
    row today (a sidecar's "chart version" is really just its owning
    dependency's, which is exactly what lib.docs_consistency's own row
    check deliberately never compares for these rows either — see its
    `actual_chart = None` for the sidecar branch). Returns (new_text,
    added_names)."""
    current_paths = dict(find_image_tag_paths(target_values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}
    canonical_names = canonical_sidecar_row_names(chart_dir, deps, target_values, current_paths.keys())

    matched_paths = {path for row in parse_upgrade_doc_rows(text)
                      for path in [canonical_names.get(row["name"])] if path is not None}

    added_names = []
    for name, path in sorted(canonical_names.items()):
        if path in matched_paths:
            continue
        current_tag = current_paths.get(path)
        baseline_tag = baseline_paths.get(path)
        if current_tag is None or current_tag == baseline_tag:
            continue
        new_app = current_tag.split("@", 1)[0]
        old_app = baseline_tag.split("@", 1)[0] if baseline_tag else None

        text, table_action = update_component_table(text, name, old_app, new_app, None, "-", deps, target_values)
        if table_action is None:
            continue  # doc has no "Component versions" table at all to insert into

        text, _ = remove_changes_section(text, name)
        dotted_path = ".".join(path) + ".tag"
        section = make_image_changes_section(name, target, old_app or new_app, new_app,
                                              [(dotted_path, old_app or new_app)])
        text = insert_changes_section(text, section, name, deps, target_values)
        added_names.append(name)

    return text, added_names


def resolve_basename_baseline_version(baseline_values, full_paths):
    """The single version every one of this basename's touched pins
    actually started at in baseline_values (the true git-resolved release
    baseline, see lib.component_docs.load_baseline_values) — None if they
    didn't all agree, or any of them isn't found there at all. A basename
    bump always targets every matching pin to the same new_version (see
    lib.image_version.update_image_version), so a uniform baseline is the
    only case update_docs_shared_image can cleanly treat as "back to
    baseline" or use as the one true "old" for a bump reconsidered more
    than once in the same release cycle (baseline -> 3, then baseline ->
    2, rather than each documenting the other's intermediate hop).
    `full_paths` is [(dotted "...tag" path, old_version), ...] as returned
    by group_changes_by_component."""
    versions = set()
    for dotted_path, _old_version in full_paths:
        tag = get_path(baseline_values, dotted_path)
        if not isinstance(tag, str) or not tag:
            return None
        versions.add(tag.split("@", 1)[0])
    return next(iter(versions)) if len(versions) == 1 else None


def update_image_manifest(images_path, basename, repository, old_version, new_version, digest):
    """Update the "# <N> changes:" header list and the images-manifest
    entry for a shared image basename bump — keyed by `repository` (an
    entry's "url:" resolving to it, host-stripped same as the "name:"
    convention docs/images/acr-mirror-naming.md documents), not a
    values-tree path. Returns (changes_action, entry_updated) —
    entry_updated is False (not an error) when no existing entry's
    "url:" matches this repository; the caller reports the correct
    name/url to add by hand instead, same convention as
    lib.component_docs.update_images_manifest's own missing_entries."""
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

        norm_basename = normalize_name(basename)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_basename in normalize_name(m.group("rest")):
                match_idx = idx
                break

        item_text = f"{basename} {old_version} -> {new_version}."

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

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    url_re = re.compile(r"^\s*url:\s*(\S+)\s*$")

    entry_line, block_end2 = None, None
    for idx in entry_line_indices:
        candidate_end = len(lines)
        for j in range(idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
                candidate_end = j
                break
        for j in range(idx, candidate_end):
            m = url_re.match(lines[j])
            if m and m.group(1).rstrip("/").endswith(repository):
                entry_line, block_end2 = idx, candidate_end
                break
        if entry_line is not None:
            break

    entry_updated = False
    if entry_line is not None:
        for i in range(entry_line, block_end2):
            m = re.match(r"^\s*(version|digest):", lines[i])
            if not m:
                continue
            new_value = new_version if m.group(1) == "version" else digest
            lines[i] = replace_scalar_value(lines[i], new_value)
            entry_updated = True
        comment_idx = find_preceding_comment_line(lines, entry_line)
        if comment_idx is not None:
            current_source = extract_source_version(lines[comment_idx])
            if current_source:
                lines[comment_idx] = replace_version_pair(lines[comment_idx], current_source, new_version)

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updated


def remove_image_manifest_entry(images_path, basename, repository, new_version, digest):
    """Counterpart to update_image_manifest for a shared-image bump that
    nets out to no change from baseline at all: still writes the matching
    entry's final version/digest, but removes the "changes:" list item
    and the entry's own preceding source comment instead of updating
    them, since there is no longer anything to document. Returns
    (changes_action, entry_updated) — same shape as update_image_manifest."""
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
        for i in range(header_idx + 1, len(lines)):
            if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
                break
            if re.match(r"^#\s*\d+\.", lines[i]):
                item_indices.append(i)

        norm_basename = normalize_name(basename)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_basename in normalize_name(m.group("rest")):
                match_idx = idx
                break

        if match_idx is not None:
            del lines[match_idx]
            remaining_indices = [i - 1 if i > match_idx else i for i in item_indices if i != match_idx]
            for new_num, idx in enumerate(remaining_indices, start=1):
                m = CHANGES_ITEM_RE.match(lines[idx])
                lines[idx] = f"#   {new_num}. {m.group('rest')}\n"
            remaining = len(remaining_indices)
            count_word = NUMBER_WORDS[remaining] if remaining < len(NUMBER_WORDS) else str(remaining)
            noun = "change" if remaining == 1 else "changes"
            header_m = CHANGES_HEADER_RE.match(lines[header_idx])
            lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
            changes_action = "removed"

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    url_re = re.compile(r"^\s*url:\s*(\S+)\s*$")

    entry_line, block_end2 = None, None
    for idx in entry_line_indices:
        candidate_end = len(lines)
        for j in range(idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
                candidate_end = j
                break
        for j in range(idx, candidate_end):
            m = url_re.match(lines[j])
            if m and m.group(1).rstrip("/").endswith(repository):
                entry_line, block_end2 = idx, candidate_end
                break
        if entry_line is not None:
            break

    entry_updated = False
    if entry_line is not None:
        for i in range(entry_line, block_end2):
            m = re.match(r"^\s*(version|digest):", lines[i])
            if not m:
                continue
            new_value = new_version if m.group(1) == "version" else digest
            lines[i] = replace_scalar_value(lines[i], new_value)
            entry_updated = True
        comment_idx = find_preceding_comment_line(lines, entry_line)
        if comment_idx is not None and extract_source_version(lines[comment_idx]):
            del lines[comment_idx]

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updated
