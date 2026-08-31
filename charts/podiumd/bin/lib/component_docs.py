"""Update the docs for a single component's version bump: the upgrade
doc's "Component versions" table row + "## Changes" section, the
values-deltas doc, and docs/images/images-<target>.yaml. Shared by
update-component-version (a component's own app+chart bump — old_chart
may differ from new_chart) and update-image-version (a shared image
basename's bump, applied per component it happens to affect — old_chart
always equals new_chart there, since an image-only bump never touches
Chart.yaml).

Also holds the standard-doc-set scaffolding shared by create-doc-version
and fix-doc-baseline (STANDARD_SUFFIXES/STUB_TEMPLATES/
IMAGES_STUB_TEMPLATE, existing_doc_baselines, create_missing_docs) — the
"create fresh vs. rebase existing" split lives entirely in those two
scripts' own control flow; only the shared data/scan/create pieces live
here.

Every path here (doc_dir/images_dir/values_path) is passed in explicitly
rather than read from a module-level constant, since the callers each
resolve their own CHART_DIR-relative paths independently."""
import re

import yaml

from lib.chart import replace_scalar_value
from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.upgradedoc import (
    canonical_version_cell, component_order_key, extract_source_version,
    find_grouped_preceding_comment_line, insertion_index, normalize_name, normalize_version,
    parse_upgrade_doc_changes_blocks, parse_upgrade_doc_rows, replace_version_pair, resolve_entry_path,
    values_key_order,
)

NUMBER_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen"]
CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)(?P<count_word>\w+)\s+changes?:\s*$", re.IGNORECASE)
CHANGES_ITEM_RE = re.compile(r"^#\s*(?P<num>\d+)\.\s+(?P<rest>.+)$")
NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)


def images_manifest_path(images_dir, target):
    return images_dir / f"images-{target}.yaml"


def baseline_doc_paths(doc_dir, baseline, target):
    """(upgrade_path, values_deltas_path) for the <baseline>-to-<target>-
    *.md doc set, or (None, None) if baseline is None (release-baseline
    doesn't exist yet) or the upgrade doc itself doesn't exist yet — run
    create-doc-version first to scaffold it either way."""
    if baseline is None:
        return None, None
    upgrade_path = doc_dir / f"{baseline}-to-{target}-upgrade.md"
    if not upgrade_path.is_file():
        return None, None
    values_deltas_path = doc_dir / f"{baseline}-to-{target}-values-deltas.md"
    return upgrade_path, (values_deltas_path if values_deltas_path.is_file() else None)


# The three docs verify-podiumd's check_baseline_doc_set expects for every
# target — missing ones are created as stubs, not just renamed. Shared by
# create-doc-version (creates whichever are missing for a fresh target)
# and fix-doc-baseline (renames existing ones, and falls back to the
# same fresh-create for whichever were never scaffolded at all).
STANDARD_SUFFIXES = ("upgrade", "gemeente-specific", "values-deltas")

STUB_TEMPLATES = {
    "upgrade": (
        "# Upgrade guide: PodiumD {baseline} → {target}\n\n"
        "> See the Confluence Releases page for the agreed application\n"
        "> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.\n\n"
        "TODO: describe this hop's changes.\n\n"
        "## Component versions ({target} vs {baseline})\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
        "TODO\n"
    ),
    "gemeente-specific": (
        "# Gemeente-specific notes — PodiumD {baseline} → {target}\n\n"
        "Findings for this hop that apply to a **specific gemeente or environment** —\n"
        "not to the release in general — are collected here: data quirks, local\n"
        "overrides, hosting particulars, incident follow-ups.\n\n"
        "_None recorded yet._\n\n"
        "<!-- Add entries per gemeente/environment:\n\n"
        "## <gemeente> (<env>)\n\n"
        "- What was hit, why it is specific to this environment, and the\n"
        "  fix/workaround applied.\n"
        "-->\n"
    ),
    "values-deltas": (
        "# Values deltas — PodiumD {baseline} → {target}\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
    ),
}

IMAGES_STUB_TEMPLATE = (
    "# Baseline: podiumd {baseline}. Re-verify before release.\n"
    "#\n"
    "# Images new or changed in podiumd {target} vs {baseline}.\n"
    "#\n"
    "# See docs/_UPGRADE_PATHS/{baseline}-to-{target}-upgrade.md for the operator upgrade notes.\n"
    "#\n"
    "# Digests are the OCI image index (multi-arch manifest) digest as returned in\n"
    "# the Docker-Content-Digest response header from the source registry.\n\n"
    "[]\n"
)

# The shape a doc filename's baseline segment must have — bare
# MAJOR.MINOR.PATCH, matching create-podiumd-version/change-podiumd-
# baseline's own release-baseline convention.
DOC_FILENAME_RE_TMPL = r"^(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>[\w\-]+)\.md$"


def existing_doc_baselines(doc_dir, target):
    """{suffix: [(baseline, path), ...]} for every *-to-<target>-<suffix>.md
    doc currently in doc_dir, whatever baseline each one currently names —
    the raw "what's actually there" scan. Shared by create-doc-version (to
    detect a baseline mismatch worth refusing fresh-creation over) and
    fix-doc-baseline (to know what to rename)."""
    pattern = re.compile(DOC_FILENAME_RE_TMPL.format(target=re.escape(target)))
    by_suffix = {}
    for path in doc_dir.glob(f"*-to-{target}-*.md"):
        m = pattern.match(path.name)
        if not m:
            continue
        by_suffix.setdefault(m.group("suffix"), []).append((m.group("baseline"), path))
    return by_suffix


def create_missing_docs(doc_dir, images_dir, baseline, target):
    """Create whichever of the three standard <baseline>-to-<target>-*.md
    docs, and docs/images/images-<target>.yaml, don't already exist yet,
    as TODO stubs — never overwrites an existing file. Returns the
    filenames actually created (upgrade/gemeente-specific/values-deltas
    order, images manifest last)."""
    created = []
    for suffix in STANDARD_SUFFIXES:
        path = doc_dir / f"{baseline}-to-{target}-{suffix}.md"
        if not path.is_file():
            path.write_text(STUB_TEMPLATES[suffix].format(baseline=baseline, target=target), encoding="utf-8")
            created.append(path.name)
    images_path = images_manifest_path(images_dir, target)
    if not images_path.is_file():
        images_path.write_text(IMAGES_STUB_TEMPLATE.format(baseline=baseline, target=target), encoding="utf-8")
        created.append(images_path.name)
    return created


def load_baseline_values(values_path, baseline):
    """values.yaml as it actually was at the release these docs are written
    against (resolved via git) — NOT "before this script's own edit". A
    tag-only bump never touches values.yaml's schema, so a before/after-
    this-run comparison would always be empty regardless of what actually
    changed for this component since the real baseline; comparing against
    the true baseline is the only way to catch a values.yaml schema change
    (new/removed/renamed key) made by hand as part of this hop, whenever
    during the hop that edit happened. Returns None if the baseline can't
    be resolved (e.g. that release hasn't been tagged yet) — callers then
    skip key-change detection rather than comparing against nothing
    meaningful."""
    repo_root = find_repo_root(values_path.parent)
    if repo_root is None:
        return None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(baseline))
    if ref is None:
        return None
    rel_values_path = values_path.relative_to(repo_root)
    return git_show_yaml(repo_root, ref, str(rel_values_path))


def load_baseline_state(chart_yaml_path, values_path, baseline):
    """(baseline_deps, baseline_values) as they actually were at baseline's
    resolved git ref — same ref resolution as load_baseline_values, but
    also pulls Chart.yaml so a caller can tell whether a component's own
    CHART version (not just an image tag under it) has moved from
    baseline. Feeds lib.upgradedoc.compute_changed_components, which is
    the ground truth for "has this component actually changed since
    baseline at all" — used to decide whether a bump's own "old" version
    for docs should be the true baseline (so a component bumped more than
    once in one release cycle still shows baseline → final, not
    each-intermediate-hop → final) or whether there's no longer any change
    left to document. Returns (None, None) if the baseline can't be
    resolved (e.g. that release hasn't been tagged yet) — callers then
    fall back to their own before-this-run comparison instead."""
    repo_root = find_repo_root(values_path.parent)
    if repo_root is None:
        return None, None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(baseline))
    if ref is None:
        return None, None
    rel_chart_yaml = chart_yaml_path.relative_to(repo_root)
    baseline_chart_yaml = git_show_yaml(repo_root, ref, str(rel_chart_yaml))
    if baseline_chart_yaml is None:
        return None, None
    rel_values_path = values_path.relative_to(repo_root)
    baseline_values = git_show_yaml(repo_root, ref, str(rel_values_path)) or {}
    return baseline_chart_yaml.get("dependencies", []), baseline_values


def find_component_row(rows, friendly):
    norm_friendly = normalize_name(friendly)
    for row in rows:
        if norm_friendly in normalize_name(row["name"]):
            return row
    return None


def update_component_table(text, friendly, old_app, new_app, old_chart, new_chart, deps, values):
    """Update this component's "Component versions" table row if it's
    already mentioned, or insert a new row if it isn't — in values.yaml's
    own top-level component order relative to the rows already there (see
    lib.upgradedoc.component_order_key/insertion_index), not always at
    the end. Returns (new_text, action) where action is "updated" or
    "added" (or None if the doc has no table at all to insert into)."""
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
        key_order = values_key_order(values)
        new_key = component_order_key(friendly, deps, key_order)
        existing_keys = [component_order_key(r["name"], deps, key_order) for r in rows]
        idx = insertion_index(new_key, existing_keys)
        insert_at = rows[idx]["line_index"] if idx < len(rows) else rows[-1]["line_index"] + 1
    else:
        insert_at = None
        for i, line in enumerate(lines):
            if re.match(r"^\|\s*:?-+:?\s*\|", line.strip()):
                insert_at = i + 1
        if insert_at is None:
            return text, None
    lines.insert(insert_at, new_row_line)
    return "".join(lines), "added"


def remove_component_row(text, friendly):
    """Delete this component's row from the "Component versions" table
    entirely — the counterpart to update_component_table's "added"/
    "updated" for a bump that nets out to no change from baseline at all
    (see lib.upgradedoc.compute_changed_components): there's no longer a
    source → target transition to show a row for. Returns
    (new_text, removed)."""
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)
    if row is None:
        return text, False
    lines = text.splitlines(keepends=True)
    del lines[row["line_index"]]
    return "".join(lines), True


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


def insert_changes_section(text, section_text, friendly, deps, values):
    """Insert section_text as a new "### ..." block into the "## Changes"
    section, in values.yaml's own top-level component order relative to
    the blocks already there (see lib.upgradedoc.component_order_key/
    insertion_index) — not always at the end. Appends right before the
    next "## " heading (or EOF) if the section doesn't exist yet, or has
    no blocks of its own yet to compare against."""
    blocks = parse_upgrade_doc_changes_blocks(text)
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

    section_end = len(lines)
    for i in range(changes_idx + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            section_end = i
            break

    if not blocks:
        insert_at = section_end
    else:
        key_order = values_key_order(values)
        new_key = component_order_key(friendly, deps, key_order)
        existing_keys = [component_order_key(b["heading"], deps, key_order) for b in blocks]
        idx = insertion_index(new_key, existing_keys)
        insert_at = blocks[idx]["start"] if idx < len(blocks) else section_end

    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def remove_changes_section(text, friendly):
    """Delete this component's "### ..." block from the "## Changes"
    section entirely — the counterpart to insert_changes_section for a
    bump that nets out to no change from baseline at all. Also swallows
    the block's own trailing blank line(s) so removal doesn't leave a
    double gap before whatever follows. Returns (new_text, removed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    norm_friendly = normalize_name(friendly)
    block = next((b for b in blocks if norm_friendly in normalize_name(b["heading"])), None)
    if block is None:
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


def values_delta_bullet(friendly, old_app, new_app, old_chart, new_chart):
    app_changed = normalize_version(old_app) != normalize_version(new_app)
    chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
    app_bit = f"`{old_app} → {new_app}`" if app_changed else f"`{new_app}` (unchanged)"
    chart_bit = f"`{old_chart} → {new_chart}`" if chart_changed else f"`{new_chart}`, unchanged"
    note = "image tag only" if not chart_changed else "chart + image tag"
    return f"- **{friendly}** app {app_bit} (chart {chart_bit}) — {note}.\n"


def remove_component_values_delta(text, friendly):
    """Delete this component's version-bullet block from values-deltas.md
    entirely: the "- **<friendly>** app ..." (values_delta_bullet) or
    "- **<basename>** image ..." (lib.image_docs.image_delta_bullet)
    bullet line, plus any immediately-following describe_key_changes
    lines appended alongside it (a bullet's own caller always appends
    them together as one contiguous block — see append_to_doc). Used both
    to collapse more than one bump within a release into a single
    up-to-date bullet (remove the stale one before appending the fresh
    one) and to remove it outright when a bump nets out to no change from
    baseline at all. Returns (new_text, removed)."""
    lines = text.splitlines(keepends=True)
    norm_friendly = normalize_name(friendly)
    bullet_re = re.compile(r"^-\s+\*\*([^*]+)\*\*\s+\w+\b")
    start = None
    for i, line in enumerate(lines):
        m = bullet_re.match(line)
        if m and norm_friendly in normalize_name(m.group(1)):
            start = i
            break
    if start is None:
        return text, False
    end = start + 1
    while end < len(lines) and lines[end].startswith("- ") and not bullet_re.match(lines[end]):
        end += 1
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


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


def remove_component_from_images_manifest(images_path, friendly, values_key, paths_to_update, repos,
                                           new_tags_by_path):
    """Counterpart to update_images_manifest for a bump that nets out to no
    change from baseline at all (see lib.upgradedoc.compute_changed_
    components): still writes each touched entry's final version/digest —
    the manifest's job is to list the correct final state for every image
    regardless of change-tracking — but removes the "changes:" list item
    and each entry's own preceding source comment instead of updating
    them, since there is no longer anything to document. Returns
    (changes_action, entry_names_updated) — changes_action is "removed" or
    None (no matching list item found)."""
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

        norm_friendly = normalize_name(friendly)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_friendly in normalize_name(m.group("rest")):
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

    entries = yaml.safe_load("".join(lines)) or []
    if not isinstance(entries, list):
        entries = []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]

    def component_of(entry):
        return values_key if normalize_name(values_key) in normalize_name(entry["name"]) else None

    def same_group(entry_a, entry_b):
        return (component_of(entry_a) is not None
                and component_of(entry_a) == component_of(entry_b)
                and entry_a.get("version") == entry_b.get("version"))

    entry_updates, comment_lines_to_remove = [], []
    for path in paths_to_update:
        target_path = values_tree_path_for(values_key, path)
        entry, entry_idx, index = find_matching_images_entry(entries, entry_line_indices, target_path)
        if entry is None:
            continue
        new_app_version, digest = new_tags_by_path[path].split("@", 1)
        block_end2 = len(lines)
        for i in range(entry_idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[i]) or not lines[i].strip():
                block_end2 = i
                break
        for i in range(entry_idx, block_end2):
            m = re.match(r"^\s*(version|digest):", lines[i])
            if not m:
                continue
            new_value = new_app_version if m.group(1) == "version" else digest
            lines[i] = replace_scalar_value(lines[i], new_value)

        comment_idx = find_grouped_preceding_comment_line(
            lines, entries, entry_line_indices, index, same_group)
        if comment_idx is not None and extract_source_version(lines[comment_idx]):
            comment_lines_to_remove.append(comment_idx)
        entry_updates.append(entry["name"])

    for idx in sorted(set(comment_lines_to_remove), reverse=True):
        del lines[idx]

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates
