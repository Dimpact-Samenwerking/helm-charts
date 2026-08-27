"""Update the docs for a shared image basename's version bump — the
"Component versions" table row, "## Changes" section, values-deltas
bullet, and images-<target>.yaml entry, all keyed by the basename/
repository itself rather than any one consuming component's values-tree
path. Used only when a basename bump (lib.image_version.
update_image_version) actually touches more than one Chart.yaml
component — a bump resolving to exactly one component (e.g. via a
dependency alias like "openklant") gets the SAME full-fidelity treatment
update-component-version.py itself uses (lib.component_docs, real chart
version), not this module.

Convention confirmed against docs/_UPGRADE_PATHS/4.8.1-to-4.8.2-
upgrade.md: curl/nginx-unprivileged/busybox each got their own table row
(Helm chart column "-") and a "### <name> ..." Changes block listing
every place they're pinned. The row naturally sorts after every real
component — lib.upgradedoc.component_order_key's own "unmatched sorts
last" rule already produces that with no special-casing needed here,
since a bare basename never matches a Chart.yaml dependency by name."""
import re

from lib.chart import replace_scalar_value
from lib.component_docs import CHANGES_HEADER_RE, CHANGES_ITEM_RE, NUMBER_WORDS
from lib.upgradedoc import extract_source_version, find_preceding_comment_line, normalize_name, replace_version_pair


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
