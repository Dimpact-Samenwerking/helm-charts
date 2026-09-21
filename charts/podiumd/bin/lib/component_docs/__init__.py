"""Update the docs for a single component's version bump: the upgrade
doc's "Component versions" table row + "## Changes" section, the
values-deltas doc, and docs/images/images-<target>.yaml. Shared by
update-component-version (a component's own app+chart bump — old_chart
may differ from new_chart) and update-image-version (a shared image
basename's bump, applied per component it happens to affect — old_chart
always equals new_chart there, since an image-only bump never touches
Chart.yaml).

See lib.component_docs.baseline_doc_stubs for the standard-doc-set
scaffolding (create_missing_docs, STANDARD_SUFFIXES, STUB_TEMPLATES),
lib.component_docs.images_manifest_changes_header for the images-
manifest "# Changes:" header/item bookkeeping, and lib.component_docs.
changes_section for the table row/"## Changes" section itself — all
three split out of this module, kept as package siblings.

Every path here (doc_dir/images_dir/values_path) is passed in explicitly
rather than read from a module-level constant, since the callers each
resolve their own CHART_DIR-relative paths independently."""

import re

import yaml

from lib.chart_registered_paths import native_components
from lib.chart_values_tree_primitives import replace_scalar_value
from lib.component_docs.baseline_doc_stubs import GEMEENTE_SPECIFIC_STUB_LINE, VALUES_DELTAS_STUB_TODO_LINE
from lib.component_docs.changes_section import dep_for_values_key
from lib.component_docs.images_manifest_changes_header import (
    CHANGES_HEADER_RE,
    CHANGES_ITEM_RE,
    NUMBER_WORDS,
    ensure_images_manifest_changes_header,
    find_images_manifest_changes_header,
    images_manifest_order_key,
    insert_images_manifest_header_item,
)
from lib.upgradedoc_app_version_and_image_paths import (
    actual_app_version,
    resolve_entry_path,
)
from lib.upgradedoc_grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc_sorting_and_ordering import (
    component_order_key,
    insertion_index,
    parse_values_delta_sections,
    values_key_order,
)
from lib.upgradedoc_string_and_parsing_basics import (
    changes_heading_identities,
    extract_source_version,
    normalize_name,
    normalize_version,
)
from lib.upgradedoc_version_cells_and_key_changes import (
    append_to_doc,
    component_version_cell,
    image_manifest_version_text,
    missing_key_change_lines_by_key,
    replace_version_pair,
    strip_html_comments,
)

NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)


def values_delta_section_heading(friendly, old_app, new_app, old_chart, new_chart):
    """The "## <friendly> ..." heading for this component's own values-
    deltas.md section — carries the app/chart-transition info a flat
    "- **<friendly>** app ..." bullet used to restate on its own first
    line: once the heading itself already says it, repeating it as the
    section's first bullet is pure noise (that's the whole point of
    giving each component its own section instead of a shared flat
    list). `new_chart == "-"` means a native_components component (see
    lib.chart.native_components) with no Chart.yaml dependency/chart
    version at all — the "(chart ...)" clause is dropped entirely rather
    than rendered as the misleading "chart None → -". `old_app`/
    `old_chart` may be None (nothing resolved at upgrade_docs_baseline —
    a genuinely brand-new component this hop, e.g. mi, real case: the
    Chart.yaml dependency line predates this release but its own
    "image:" block was only pinned this hop) — rendered "(new)" via
    lib.upgradedoc.component_version_cell, the exact same wording family
    make_changes_section's own app_heading/chart_suffix already use for
    the identical case (real bug, fixed: this used to silently collapse
    "old is None" into "old == new" via "old_app or new_app", rendering
    the equally-wrong "(unchanged)" instead — component_version_cell
    handles None correctly on its own, so there's no reason for this
    function to re-derive that logic separately and risk drifting from
    make_changes_section's own).

    Only ever called (see sync_values_delta_sections) when there's a
    real "- Key `...`" line to put under this heading — a section with
    nothing else to say needs no section at all, so there's no "— <note>
    explaining why nothing else changed" suffix here the way an earlier
    design had. `new_app is None` (actual_app_version couldn't resolve
    anything — see that function's own docstring) falls back to a
    chart-only heading with its own unconditional TODO note instead,
    since that one isn't about "nothing else changed" but about a real
    tooling gap (the app version itself is unknown)."""
    if new_app is None:
        if new_chart == "-":
            return (
                f"## {friendly} — TODO: describe this component's changes; its app version "
                f"could not be resolved automatically.\n"
            )
        chart_bit = (
            f"chart {old_chart} → {new_chart}"
            if old_chart and normalize_version(old_chart) != normalize_version(new_chart)
            else f"chart {new_chart}, unchanged"
        )
        return (
            f"## {friendly} {chart_bit} — TODO: describe this component's changes; its app "
            f"version could not be resolved automatically.\n"
        )

    app_bit = component_version_cell(old_app, new_app)
    if new_chart == "-":
        chart_bit = ""
    elif old_chart is None:
        chart_bit = f" (chart {new_chart}, new)"
    else:
        chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
        chart_bit = f" (chart {old_chart} → {new_chart})" if chart_changed else f" (chart {new_chart}, unchanged)"
    return f"## {friendly} {app_bit}{chart_bit}\n"


def find_values_delta_section(text, friendly, deps, canonical_names=None):
    """The existing "## ..." section (see lib.upgradedoc.parse_values_
    delta_sections/changes_heading_identities) that already names the
    SAME component identity `friendly` does — reused for a real
    Chart.yaml dependency/native_components friendly name, a canonical
    "<parent> - <basename>" sidecar name, or a bare shared-image
    basename (see changes_heading_identities for all three shapes), so
    a hand-written section already covering this identity (KISS's own
    "## KISS ... — required edits", or a shared-image mention already
    covered elsewhere) is found and reused instead of creating a
    redundant new one right next to it. None if `friendly` itself
    resolves to no real identity at all, or no existing section shares
    one."""
    target_idents = changes_heading_identities(friendly, deps, canonical_names)
    if not target_idents:
        return None
    for section in parse_values_delta_sections(text):
        if changes_heading_identities(section["heading"], deps, canonical_names) & target_idents:
            return section
    return None


def _is_bare_values_deltas_todo_stub(lines):
    """True if `lines` (a whole values-deltas.md doc with no "## ..."
    section yet) is JUST STUB_TEMPLATES["values-deltas"]'s own shape: its
    "# Values deltas — ..." H1 title, then nothing but blank lines and
    the bare TODO sentence that stub writes (VALUES_DELTAS_STUB_TODO_LINE)
    — same exact-shape precision as _is_bare_placeholder_span above,
    never a substring/heuristic match."""
    non_blank = [line.strip() for line in lines if line.strip()]
    return (
        len(non_blank) == 2 and non_blank[0].startswith("# ") and non_blank[1] == VALUES_DELTAS_STUB_TODO_LINE.strip()
    )


def insert_values_delta_section(text, friendly, heading_line, body_lines, deps, values, canonical_names=None):
    """Insert a brand-new "## <heading_line>" section (heading_line
    already includes its own trailing newline) + body_lines as its
    content, in values.yaml's own top-level component order relative to
    the "## " sections already there (see lib.upgradedoc.component_
    order_key/insertion_index) — not always at the end. Mirrors
    insert_changes_section's own positioning logic, one heading level
    up (top-level "## " instead of "## Changes"'s own nested "### ..."),
    including stripping the doc's own bare TODO placeholder (see
    _is_bare_values_deltas_todo_stub) before the very first real section
    lands, rather than leaving it stranded above it — the same class of
    bug insert_changes_section had (see that function's own docstring)."""
    body = "".join(body_lines)
    section_text = heading_line + "\n" + body + ("\n" if body else "")
    sections = parse_values_delta_sections(text)
    lines = text.splitlines(keepends=True)
    if not sections:
        if _is_bare_values_deltas_todo_stub(lines):
            lines = [line for line in lines if line.strip() != VALUES_DELTAS_STUB_TODO_LINE.strip()]
            text = "".join(lines)
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text + section_text

    key_order = values_key_order(values)
    new_key = component_order_key(friendly, deps, key_order, canonical_names, values)
    existing_keys = [component_order_key(s["heading"], deps, key_order, canonical_names, values) for s in sections]
    idx = insertion_index(new_key, existing_keys)
    insert_at = sections[idx]["start"] if idx < len(sections) else len(lines)
    if insert_at > 0 and lines[insert_at - 1].strip():
        lines.insert(insert_at, "\n")
        insert_at += 1
    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def strip_stale_values_deltas_todo_stub(text):
    """Retroactive cleanup companion to insert_values_delta_section's own
    insertion-time fix (see _is_bare_values_deltas_todo_stub there): a
    values-deltas.md doc whose FIRST real "## ..." section was inserted
    BEFORE that fix existed still has the stray TODO sentence stranded
    between the doc's own H1 title and that first section — real case,
    confirmed live: 4.9.1-to-4.9.2-values-deltas.md. Mirrors strip_
    stale_upgrade_placeholders' own shape one heading level up, same as
    insert_values_delta_section mirrors insert_changes_section.

    Also doubles as the CHECKER side, same trick as strip_stale_upgrade_
    placeholders: a caller that only wants to know WHETHER the
    placeholder is still stranded inspects the returned `changed` flag
    and discards new_text, rather than a separate find-only function.

    Only fires when a real "## ..." section ALREADY exists — a doc that
    still only has the bare stub (nothing recorded yet) is correct and
    must never be touched. Returns (new_text, changed)."""
    sections = parse_values_delta_sections(text)
    if not sections:
        return text, False

    lines = text.splitlines(keepends=True)
    first_section_start = sections[0]["start"]
    prefix = lines[:first_section_start]
    if not _is_bare_values_deltas_todo_stub(prefix):
        return text, False

    title_line = next(line for line in prefix if line.strip())
    return title_line + "\n" + "".join(lines[first_section_start:]), True


GEMEENTE_SECTION_HEADING_RE = re.compile(r"^##\s+\S.*$", re.MULTILINE)


def has_real_gemeente_specific_content(text):
    """True if gemeente-specific.md has at least one real "## <gemeente>
    (<env>)" section outside its own commented-out example template (see
    STUB_TEMPLATES["gemeente-specific"], whose own EXAMPLE heading of
    that exact shape lives inside a "<!-- ... -->" block) — the "has
    real content" signal for has_stale_gemeente_specific_placeholder,
    mirroring parse_upgrade_doc_changes_blocks/parse_values_delta_
    sections' own role for the other two doc types. Scans strip_html_
    comments' own output, never the original text, same precedent as
    strip_fenced_code_blocks (see that function's own docstring)."""
    return bool(GEMEENTE_SECTION_HEADING_RE.search(strip_html_comments(text)))


def has_stale_gemeente_specific_placeholder(text):
    """True if gemeente-specific.md still carries its own bare "_None
    recorded yet._" placeholder (GEMEENTE_SPECIFIC_STUB_LINE) ALONGSIDE
    at least one real "## <gemeente> (<env>)" section already added by
    hand — a human added a real finding but left the placeholder behind.

    Unlike the other three placeholders (upgrade.md's own two, values-
    deltas.md's own one), there is NO strip/fixer counterpart for this
    one: nothing ever writes a new section into gemeente-specific.md
    automatically — its content is entirely human-authored findings
    (data quirks, local overrides, incident follow-ups) — so this is a
    check-only finding for verify-podiumd's own check_docs_consistency
    to report, left for a human to clear by hand, never something fix-
    doc-consistency could safely auto-fix."""
    if not has_real_gemeente_specific_content(text):
        return False
    return any(line.strip() == GEMEENTE_SPECIFIC_STUB_LINE.strip() for line in text.splitlines())


def append_values_delta_section_body(text, section, new_lines):
    """Append new_lines at the end of an EXISTING values-deltas.md
    section (see find_values_delta_section) — right before its own next
    "## " heading (or EOF) — blank-line-separated from whatever already
    ends the section (append_to_doc's own convention, just section-
    scoped instead of always true EOF), never disturbing whatever
    hand-written prose or previously-added lines already sit there."""
    lines = text.splitlines(keepends=True)
    head = "".join(lines[: section["end"]])
    tail = "".join(lines[section["end"] :])
    new_head = append_to_doc(head, new_lines)
    if tail:
        new_head = new_head.rstrip("\n") + "\n\n"
    return new_head + tail


def remove_values_delta_section(text, friendly, deps, canonical_names=None):
    """Delete this component's OWN values-deltas.md section entirely —
    the counterpart to insert_values_delta_section, for a bump that nets
    out to no change from upgrade_docs_baseline at all. Only ever
    deletes a section whose own identity set is EXACTLY `friendly`'s
    (see find_values_delta_section) — a hand-written section covering
    several components at once (e.g. "## ZAC and ZGW Office Add-in — no
    changes") is never a candidate for deletion just because one of ITS
    components reset to baseline; that always needs a human's own edit.
    Also swallows the section's own trailing blank line(s). Returns
    (new_text, removed)."""
    target_idents = changes_heading_identities(friendly, deps, canonical_names)
    if not target_idents:
        return text, False
    for section in parse_values_delta_sections(text):
        if changes_heading_identities(section["heading"], deps, canonical_names) == target_idents:
            lines = text.splitlines(keepends=True)
            start, end = section["start"], section["end"]
            while end < len(lines) and not lines[end].strip():
                end += 1
            del lines[start:end]
            return "".join(lines), True
    return text, False


def sync_values_delta_sections(
    text,
    chart_dir,
    target_deps,
    target_values,
    baseline_deps,
    baseline_values,
    actual_changed_keys,
    canonical_names=None,
):
    """Ensure every key in `actual_changed_keys` has its own values-
    deltas.md section (see find_values_delta_section/insert_values_
    delta_section) carrying every describe_key_changes line not already
    mentioned anywhere in the doc (see missing_key_change_lines_by_key)
    — creating a brand new "## <key> <old> → <new>..." section (see
    values_delta_section_heading) at its own values.yaml-order position
    when no existing section (hand-written, or a previous run's own)
    already covers this key's identity, or appending just the missing
    lines into whichever section already does, after whatever's already
    there. Existing content is only ever ADDED to, never reordered or
    rewritten — see sort_values_delta_sections for reordering.

    A key with no matching Chart.yaml dependency AND no lib.chart.
    native_components entry either is skipped when it needs a brand-new
    section — nothing here can be generated confidently without a real
    Chart.yaml version to read, or the chart-less convention to fall
    back to (same skip add_missing_component_rows already applies). A
    key with NO key_lines of its own (a pure app/chart version bump,
    already fully covered by -upgrade.md's own table + Changes section)
    never gets a brand-new section either — values-deltas.md exists to
    tell gemeentes what THEIR OWN podiumd.yml needs to react to, and a
    version-only bump needs no gemeente action at all; a heading with
    nothing under it is worse than no heading. An EXISTING section
    (hand-written, or a previous run's own) is still left exactly as it
    already was in that case — this only ever decides whether a NEW one
    gets created, never touches one that's already there.
    Returns (new_text, created_names, updated_names)."""
    by_key = missing_key_change_lines_by_key(text, actual_changed_keys, baseline_values, target_values)
    created_names, updated_names = [], []
    for key in sorted(actual_changed_keys):
        key_lines = by_key.get(key, [])
        section = find_values_delta_section(text, key, target_deps, canonical_names)
        if section is not None:
            if key_lines:
                text = append_values_delta_section_body(text, section, key_lines)
                updated_names.append(key)
            continue
        if not key_lines:
            continue

        dep = dep_for_values_key(target_deps, key)
        if dep is not None:
            chart_name = dep["name"]
            baseline_dep = dep_for_values_key(baseline_deps, key) if baseline_deps else None
            old_chart = str(baseline_dep["version"]) if baseline_dep else None
            new_chart = str(dep["version"])
        elif key in native_components(chart_dir):
            chart_name = key
            old_chart = None
            new_chart = "-"
        else:
            continue

        old_app = actual_app_version(baseline_values, key, chart_name) if baseline_values else None
        new_app = actual_app_version(target_values, key, chart_name, chart_dir=chart_dir, dep=dep)
        heading_line = values_delta_section_heading(key, old_app, new_app, old_chart, new_chart)
        text = insert_values_delta_section(
            text, key, heading_line, key_lines, target_deps, target_values, canonical_names
        )
        created_names.append(key)

    return text, created_names, updated_names


def prune_empty_values_delta_sections(text):
    """Delete every "## ..." section (see lib.upgradedoc.parse_values_
    delta_sections) whose own body is entirely blank — no content at all
    between its heading and the next "## " heading (or EOF). Only ever
    hits a section sync_values_delta_sections/update-component-version/
    update-image-version themselves left behind BEFORE this rule
    existed (a heading-only section describing a pure version bump with
    nothing else to say) — a hand-written section always has SOME prose
    of its own, so this can never accidentally delete one. Also swallows
    the pruned section's own trailing blank line(s), same as
    remove_values_delta_section. Returns (new_text, removed_headings)."""
    lines = text.splitlines(keepends=True)
    sections = parse_values_delta_sections(text)
    removed_headings = []
    for section in reversed(sections):
        body = "".join(lines[section["start"] + 1 : section["end"]]).strip()
        if body:
            continue
        start, end = section["start"], section["end"]
        while end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        removed_headings.append(section["heading"])
    return "".join(lines), list(reversed(removed_headings))


def values_tree_path_for(values_key, image_path):
    """The find_image_tag_paths key for a component_image_paths()-style
    dotted path (e.g. "frontend.image") under this component's values_key."""
    segments = image_path.split(".")
    return (values_key,) + tuple(segments[:-1])


def find_matching_images_entry(entries, entry_line_indices, target_path):
    for index, (entry, line_idx) in enumerate(zip(entries, entry_line_indices, strict=True)):
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
        return (
            component_of(entry_a) is not None
            and component_of(entry_a) == component_of(entry_b)
            and entry_a.get("version") == entry_b.get("version")
        )

    comment_idx = find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index, same_group)
    if comment_idx is not None:
        current_source = extract_source_version(lines[comment_idx])
        if current_source:
            lines[comment_idx] = replace_version_pair(lines[comment_idx], current_source, new_app_version)
            changed = True
    return changed


def update_images_manifest(
    images_path,
    friendly,
    values_key,
    old_app,
    new_app,
    old_chart,
    new_chart,
    paths_to_update,
    repos,
    new_tags_by_path,
    deps,
    values,
):
    """Update the "# <N> changes:" header list and any existing entries'
    version/digest/comment for this component. Returns (changes_action,
    entry_names_updated, missing_entries) where missing_entries is
    [(image_path, repo, new_tag), ...] for components with no existing
    entry — never invented here. "name:" is mechanically derivable now
    (strip_registry(repo), see docs/images/acr-mirror-naming.md) but this
    function doesn't compute it — a full manifest entry still needs a
    human-authored comment/heading, so callers print a placeholder and
    leave the whole entry for manual review rather than a script writing
    part of it and a human the rest.

    deps/values position a brand-new header item at its own values.yaml-
    order slot (via insert_images_manifest_header_item/images_manifest_
    order_key — the SAME convention fix-doc-consistency's own add_
    missing_images_manifest_entries already uses) instead of always
    appending at the very end — real bug this fixes: update-image-
    version/update-component-version writing a new item that then sat
    out of order until a LATER fix-doc-consistency run reshuffled it,
    even though nothing else about the manifest was actually wrong.
    Updating an EXISTING item never needs them for anything — the far
    more common path here — so they're only ever read on a genuinely new
    item."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    # A file that has lost its "# Changes:" header (or never had one) —
    # see ensure_images_manifest_changes_header's own docstring for the
    # real bug this fixes: insert_images_manifest_header_item is a
    # documented no-op with no header to insert into, so without this,
    # a component bumped via update-component-version/update-image-
    # version into a header-less manifest would silently never get a
    # "# Changes:" list item, exactly the fix-doc-consistency-side gap
    # this same fix already closed for add_missing_images_manifest_
    # entries — this is the same gap in THESE scripts' own write path.
    ensure_images_manifest_changes_header(lines)
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)

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

        if new_chart == "-":
            # native_components component (see lib.chart.native_components)
            # — no chart at all, so no "(chart ...)" clause to render.
            item_text = f"{friendly} {image_manifest_version_text(old_app, new_app)}."
        else:
            chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
            chart_bit = f"{old_chart} -> {new_chart}" if chart_changed else f"{new_chart}, unchanged"
            item_text = f"{friendly} {image_manifest_version_text(old_app, new_app)} (chart {chart_bit})."

        if match_idx is not None:
            m = CHANGES_ITEM_RE.match(lines[match_idx])
            lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
            changes_action = "updated"
        else:
            key_order = values_key_order(values)
            new_key = images_manifest_order_key(key_order, values_key, " - " in friendly)
            insert_images_manifest_header_item(lines, deps, key_order, new_key, item_text)
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
        if update_images_manifest_entry(lines, entries, entry_line_indices, index, new_tags_by_path[path], values_key):
            entry_updates.append(entry["name"])

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates, missing_entries


def remove_component_from_images_manifest(images_path, friendly, values_key, paths_to_update, repos, new_tags_by_path):
    """Counterpart to update_images_manifest for a bump that nets out to no
    change from upgrade_docs_baseline at all (see lib.upgradedoc.compute_changed_
    components): still writes each touched entry's final version/digest —
    the manifest's job is to list the correct final state for every image
    regardless of change-tracking — but removes the "changes:" list item
    and each entry's own preceding source comment instead of updating
    them, since there is no longer anything to document. Returns
    (changes_action, entry_names_updated) — changes_action is "removed" or
    None (no matching list item found)."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    header_idx, header_has_count = find_images_manifest_changes_header(lines)

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
            if header_has_count:
                count_word = NUMBER_WORDS[remaining] if remaining < len(NUMBER_WORDS) else str(remaining)
                noun = "change" if remaining == 1 else "changes"
                header_m = CHANGES_HEADER_RE.match(lines[header_idx])
                lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
            # else: bare "# Changes:" header — left as-is, same convention
            # update_images_manifest's own insertion path follows.
            changes_action = "removed"

    entries = yaml.safe_load("".join(lines)) or []
    if not isinstance(entries, list):
        entries = []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]

    def component_of(entry):
        return values_key if normalize_name(values_key) in normalize_name(entry["name"]) else None

    def same_group(entry_a, entry_b):
        return (
            component_of(entry_a) is not None
            and component_of(entry_a) == component_of(entry_b)
            and entry_a.get("version") == entry_b.get("version")
        )

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

        comment_idx = find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index, same_group)
        if comment_idx is not None and extract_source_version(lines[comment_idx]):
            comment_lines_to_remove.append(comment_idx)
        entry_updates.append(entry["name"])

    for idx in sorted(set(comment_lines_to_remove), reverse=True):
        del lines[idx]

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates
