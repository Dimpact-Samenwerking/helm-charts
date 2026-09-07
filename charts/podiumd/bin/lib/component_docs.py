"""Update the docs for a single component's version bump: the upgrade
doc's "Component versions" table row + "## Changes" section, the
values-deltas doc, and docs/images/images-<target>.yaml. Shared by
update-component-version (a component's own app+chart bump — old_chart
may differ from new_chart) and update-image-version (a shared image
basename's bump, applied per component it happens to affect — old_chart
always equals new_chart there, since an image-only bump never touches
Chart.yaml).

Also holds the standard-doc-set scaffolding shared by create-doc-version
and fix-doc-consistency (STANDARD_SUFFIXES/STUB_TEMPLATES/
IMAGES_STUB_TEMPLATE, existing_doc_baselines, create_missing_docs) — the
"create fresh vs. rebase existing" split lives entirely in those two
scripts' own control flow; only the shared data/scan/create pieces live
here.

Every path here (doc_dir/images_dir/values_path) is passed in explicitly
rather than read from a module-level constant, since the callers each
resolve their own CHART_DIR-relative paths independently."""
import re

import yaml

from lib.chart import NATIVE_COMPONENTS, image_paths_for, load_images_baseline, replace_scalar_value, \
    version_paths_for
from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.upgradedoc import (
    _word_aligned_spans, actual_app_version, app_version_pin_via_images_baseline, append_to_doc,
    changes_heading_identities, component_order_key, component_version_cell, COMPONENT_VERSIONS_HEADING_RE,
    extract_source_version, find_grouped_preceding_comment_line, insertion_index,
    match_dependency_excluding_sidecar_names, match_native_component, missing_key_change_lines_by_key,
    normalize_name, normalize_version, parse_upgrade_doc_changes_blocks, parse_upgrade_doc_rows,
    parse_values_delta_sections, replace_version_pair, resolve_entry_path, values_key_order,
)

NUMBER_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen"]
CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)(?P<count_word>\w+)\s+changes?:\s*$", re.IGNORECASE)
# A plain "# Changes:" images-manifest header with no leading count word at
# all — CHANGES_HEADER_RE requires one ("# Twenty Two changes:"), but a
# hand-curated header (this chart's own real images-4.9.0.yaml, extensively
# rewritten with rich per-item prose) may never have picked that convention
# up, and IMAGES_STUB_TEMPLATE's own fresh "# Changes:" line never has one
# either. See find_images_manifest_changes_header, the shared "recognize
# either shape" lookup.
BARE_CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)[Cc]hanges:\s*$")
CHANGES_ITEM_RE = re.compile(r"^#\s*(?P<num>\d+)\.\s+(?P<rest>.+)$")
NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)
# The intro line IMAGES_STUB_TEMPLATE's own "# Changes:\n#\n" header
# always follows immediately — see ensure_images_manifest_changes_header,
# which uses this as its own insertion anchor when a file has lost (or
# never had) that header.
IMAGES_MANIFEST_INTRO_RE = re.compile(r"^#\s*Images new or changed in podiumd\b.*$", re.IGNORECASE)


def find_images_manifest_changes_header(lines):
    """(header_idx, header_has_count) for the images-manifest's own "#
    Changes:" header — matching EITHER CHANGES_HEADER_RE's counted form
    ("# Twenty One changes:") or BARE_CHANGES_HEADER_RE's plain "#
    Changes:" (no count word at all — the real, hand-curated images-
    4.9.0.yaml header's own actual shape, and IMAGES_STUB_TEMPLATE's own
    fresh one). (None, False) if neither is found anywhere in the file.
    Shared by fix-doc-consistency's own header-item insertion/reordering
    and update_images_manifest below — before this was factored out,
    update_images_manifest checked CHANGES_HEADER_RE alone, so it never
    recognized (and so never updated) a bare "# Changes:" header — the
    exact shape both the real hand-curated file and a freshly-stubbed
    one actually have."""
    for i, line in enumerate(lines):
        if CHANGES_HEADER_RE.match(line):
            return i, True
        if BARE_CHANGES_HEADER_RE.match(line):
            return i, False
    return None, False


def ensure_images_manifest_changes_header(lines):
    """Create the images-manifest's own bare "# Changes:\n#\n" header
    (see find_images_manifest_changes_header/IMAGES_STUB_TEMPLATE),
    right after the "# Images new or changed in podiumd ... vs ..."
    intro line, for a file that has NO header at all yet — a no-op if
    one already exists (either shape).

    insert_images_manifest_header_item's own docstring documents it as
    a no-op when the file has no header at all — by design, it only
    ever inserts an item INTO an existing header, never creates one from
    scratch. That meant a file that somehow lost its header (or never
    got one in the first place) could never have it added back by any
    later fix-doc-consistency run, silently, with no error or warning —
    real, observed case: images-4.9.1.yaml gained 5 real entries (redis,
    3 openbao sidecars, zac's own otel sidecar) across several runs, each
    with a correct per-entry "#" comment (proving path_display_name's own
    component lookup worked fine), but the file's "# Changes:" header
    itself was simply never there for any of those insertions to land
    in — so none of them ever got a summary-list item either, and
    nothing surfaced that gap until lib.docs_consistency's own "has an
    entry but no mention in the '# Changes:' list" check was pointed at
    it directly.

    Callers should call this before every insert_images_manifest_header_
    item call site (both the per-entry pass and the backfill pass in
    fix-doc-consistency's own add_missing_images_manifest_entries) —
    it's cheap and idempotent, so unconditionally ensuring first is
    simpler than threading "did we already ensure this run" state
    through both call sites.

    Falls through as a no-op (never crashes) if the intro line itself
    isn't found either — a defensive fallback for a manifest shaped
    differently than IMAGES_STUB_TEMPLATE's own convention; nothing
    currently produces that shape, but this must never be where a
    caller's whole run aborts."""
    header_idx, _has_count = find_images_manifest_changes_header(lines)
    if header_idx is not None:
        return
    for i, line in enumerate(lines):
        if IMAGES_MANIFEST_INTRO_RE.match(line.strip()):
            insert_at = i + 1
            if insert_at < len(lines) and lines[insert_at].strip() == "#":
                insert_at += 1
            lines[insert_at:insert_at] = ["# Changes:\n", "#\n"]
            return


def find_images_manifest_changes_items(lines):
    """(header_idx, header_has_count, item_indices) — item_indices is
    every "#   N. ..." line's own index (see CHANGES_ITEM_RE), in
    current top-to-bottom document order, scoped to the "# Changes:"
    header's own block (see find_images_manifest_changes_header). (None,
    False, []) if the header doesn't exist. Shared by every function
    that needs to enumerate this list's own items without re-deriving
    the same block-scanning loop each time."""
    header_idx, header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None, False, []
    item_indices = []
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        if CHANGES_ITEM_RE.match(lines[i]):
            item_indices.append(i)
    return header_idx, header_has_count, item_indices


def images_manifest_changes_count_word(total):
    """The header's own leading count word for `total` items — a single
    NUMBER_WORDS entry (Zero..Fifteen) when it has one, else the bare
    numeral string; CHANGES_HEADER_RE's own count_word group is a single
    \\w+ token, so a two-word compound like "Twenty Six" is never
    produced — paired with "change"/"changes" for the trailing noun.
    Shared by every function that rewrites this header line so the
    "what word for what count" rule is never reimplemented twice."""
    count_word = NUMBER_WORDS[total] if total < len(NUMBER_WORDS) else str(total)
    noun = "change" if total == 1 else "changes"
    return count_word, noun


def renumber_images_manifest_changes_items(lines):
    """Renumber the images-manifest's own "# Changes:" numbered item
    list to a gapless 1..N sequence matching CURRENT top-to-bottom
    document order, and update the header's own leading count word (see
    images_manifest_changes_count_word) to match — regardless of
    whether anything else about the list changed. insert_images_
    manifest_header_item/dedupe_images_manifest_changes_items/sort_
    images_manifest_changes_items each already renumber correctly as a
    side effect of their OWN specific operation (inserting one item,
    removing a duplicate, reordering) — but none of them fires at all
    when the list is already duplicate-free and already in the right
    RELATIVE order, yet still has the wrong ABSOLUTE numbers (real case:
    a human hand-removes a stale item's own block without renumbering
    everything after it, leaving a gap like "...6. ... 8. ..." with no
    "7." at all). This is the one pass that always fixes that, on its
    own, independent of anything else. Mutates `lines` in place. Returns
    True if anything was renumbered (either an item's own number, or
    the header's count word), False if the list was already exactly
    1..N (or the header/list doesn't exist at all)."""
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None or not item_indices:
        return False

    changed = False
    for slot, idx in enumerate(item_indices):
        expected = slot + 1
        m = CHANGES_ITEM_RE.match(lines[idx])
        if int(m.group("num")) != expected:
            lines[idx] = CHANGES_ITEM_RE.sub(lambda mm, n=expected: f"#   {n}. {mm.group('rest')}", lines[idx])
            changed = True

    if header_has_count:
        count_word, noun = images_manifest_changes_count_word(len(item_indices))
        header_m = CHANGES_HEADER_RE.match(lines[header_idx])
        new_header = f"{header_m.group('indent')}{count_word} {noun}:\n"
        if lines[header_idx] != new_header:
            lines[header_idx] = new_header
            changed = True

    return changed


def images_manifest_order_key(key_order, values_key, is_sidecar):
    """(index-in-key_order, 0-or-1-for-sidecar) sort key for an images-
    manifest "# Changes:" item belonging to `values_key` — an unknown
    values_key (not in key_order at all) sorts LAST, never crashes.
    Shared by every caller that inserts/positions a header item relative
    to values.yaml's own top-level component order (update_images_
    manifest below, lib.image_docs.update_image_manifest, fix-doc-
    consistency's own add_missing_images_manifest_entries) so they can
    never independently drift on what "in order" means."""
    try:
        return (key_order.index(values_key), 1 if is_sidecar else 0)
    except ValueError:
        return (len(key_order), 1 if is_sidecar else 0)


def insert_images_manifest_header_item(lines, deps, key_order, new_key, item_text):
    """Insert "#   N. <item_text>" into the images-manifest's own "#
    Changes:" header list (see find_images_manifest_changes_header) at
    the position matching new_key relative to what's already there (see
    lib.upgradedoc.component_order_key/insertion_index — the SAME
    ordering convention upgrade.md's own table rows/Changes sections
    use, via images_manifest_order_key above), renumbering every
    subsequent item. An existing item that can't be resolved to a real
    dependency (free-form prose, matched via match_dependency_excluding_
    sidecar_names the same way check_images_manifest_format's own
    Changes-item check does) sorts last for THIS purpose only — never
    causes it to move. Mutates `lines` in place; a no-op if the file has
    no header at all. Only rewrites the header line's own leading count
    word if it already had one (see header_has_count) — never invents
    one for a bare "# Changes:" label.

    Renumbering after the raw insert goes through renumber_images_
    manifest_changes_items rather than a relative "+1 to every existing
    item's OWN current number" shift — the latter silently preserves
    (just shifted) any gap or wrong number the list already had before
    this call, since it never computes each item's correct ABSOLUTE
    position from scratch; the former always does, fixing a pre-existing
    drift as a side effect of this insert instead of just adding to it.

    Shared by update_images_manifest below (a real component's own app+
    chart bump — the common case update-component-version/update-image-
    version write) and fix-doc-consistency's own add_missing_images_
    manifest_entries (a changed image with no entry/header item at all
    yet) — before this was factored out here, update_images_manifest had
    its OWN separate, append-only version (new items always landed at
    the very end, out of values.yaml's own order, only ever fixed by a
    LATER fix-doc-consistency run), which could silently drift from this
    one on what "correct" position even means."""
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None:
        return

    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1

    item_keys = []
    for idx in item_indices:
        m = CHANGES_ITEM_RE.match(lines[idx])
        item_dep = match_dependency_excluding_sidecar_names(m.group("rest"), deps) if m else None
        if item_dep is None:
            item_keys.append((len(key_order), 0))
            continue
        item_keys.append(images_manifest_order_key(key_order, item_dep.get("alias", item_dep["name"]), False))

    insert_slot = insertion_index(new_key, item_keys)
    insert_line = item_indices[insert_slot] if insert_slot < len(item_indices) else block_end
    # The number here is only ever a placeholder — renumber_images_
    # manifest_changes_items (below) overwrites it, and every OTHER
    # item's own number, with each one's correct final position.
    lines.insert(insert_line, f"#   0. {item_text}\n")

    renumber_images_manifest_changes_items(lines)


def images_manifest_path(images_dir, target):
    return images_dir / f"images-{target}.yaml"


def baseline_doc_paths(doc_dir, upgrade_docs_baseline, target):
    """(upgrade_path, values_deltas_path) for the <upgrade_docs_baseline>-to-<target>-
    *.md doc set, or (None, None) if upgrade_docs_baseline is None
    (release-baseline.yaml's own upgrade_docs key doesn't exist yet) or
    the upgrade doc itself doesn't exist yet — run create-doc-version
    first to scaffold it either way."""
    if upgrade_docs_baseline is None:
        return None, None
    upgrade_path = doc_dir / f"{upgrade_docs_baseline}-to-{target}-upgrade.md"
    if not upgrade_path.is_file():
        return None, None
    values_deltas_path = doc_dir / f"{upgrade_docs_baseline}-to-{target}-values-deltas.md"
    return upgrade_path, (values_deltas_path if values_deltas_path.is_file() else None)


# The three docs verify-podiumd's check_baseline_doc_set expects for every
# target — missing ones are created as stubs, not just renamed. Shared by
# create-doc-version (creates whichever are missing for a fresh target)
# and fix-doc-consistency (renames existing ones, and falls back to the
# same fresh-create for whichever were never scaffolded at all).
STANDARD_SUFFIXES = ("upgrade", "gemeente-specific", "values-deltas")

STUB_TEMPLATES = {
    "upgrade": (
        "# Upgrade guide: PodiumD {upgrade_docs_baseline} → {target}\n\n"
        "> See the Confluence Releases page for the agreed application\n"
        "> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.\n\n"
        "TODO: describe this hop's changes.\n\n"
        "## Component versions ({target} vs {upgrade_docs_baseline})\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
        "TODO\n"
    ),
    "gemeente-specific": (
        "# Gemeente-specific notes — PodiumD {upgrade_docs_baseline} → {target}\n\n"
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
        "# Values deltas — PodiumD {upgrade_docs_baseline} → {target}\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
    ),
}

IMAGES_STUB_TEMPLATE = (
    "# Baseline: podiumd {upgrade_docs_baseline}. Re-verify before release.\n"
    "#\n"
    "# Images new or changed in podiumd {target} vs {upgrade_docs_baseline}.\n"
    "#\n"
    "# Changes:\n"
    "#\n"
    "# See docs/_UPGRADE_PATHS/{upgrade_docs_baseline}-to-{target}-upgrade.md for the operator upgrade notes.\n"
    "#\n"
    "# Digests are the OCI image index (multi-arch manifest) digest as returned in\n"
    "# the Docker-Content-Digest response header from the source registry.\n\n"
    "[]\n"
)

# The shape a doc filename's upgrade_docs_baseline segment must have — bare
# MAJOR.MINOR.PATCH, matching create-podiumd-version/change-podiumd-
# baseline's own release-baseline.yaml upgrade_docs convention.
DOC_FILENAME_RE_TMPL = r"^(?P<upgrade_docs_baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>[\w\-]+)\.md$"


def existing_doc_baselines(doc_dir, target):
    """{suffix: [(upgrade_docs_baseline, path), ...]} for every *-to-<target>-<suffix>.md
    doc currently in doc_dir, whatever upgrade_docs_baseline each one currently names —
    the raw "what's actually there" scan. Shared by create-doc-version (to
    detect an upgrade_docs_baseline mismatch worth refusing fresh-creation over) and
    fix-doc-consistency (to know what to rename)."""
    pattern = re.compile(DOC_FILENAME_RE_TMPL.format(target=re.escape(target)))
    by_suffix = {}
    for path in doc_dir.glob(f"*-to-{target}-*.md"):
        m = pattern.match(path.name)
        if not m:
            continue
        by_suffix.setdefault(m.group("suffix"), []).append((m.group("upgrade_docs_baseline"), path))
    return by_suffix


def create_missing_docs(doc_dir, images_dir, upgrade_docs_baseline, target):
    """Create whichever of the three standard <upgrade_docs_baseline>-to-<target>-*.md
    docs, and docs/images/images-<target>.yaml, don't already exist yet,
    as TODO stubs — never overwrites an existing file. Returns the
    filenames actually created (upgrade/gemeente-specific/values-deltas
    order, images manifest last)."""
    created = []
    for suffix in STANDARD_SUFFIXES:
        path = doc_dir / f"{upgrade_docs_baseline}-to-{target}-{suffix}.md"
        if not path.is_file():
            path.write_text(STUB_TEMPLATES[suffix].format(upgrade_docs_baseline=upgrade_docs_baseline, target=target), encoding="utf-8")
            created.append(path.name)
    images_path = images_manifest_path(images_dir, target)
    if not images_path.is_file():
        images_path.write_text(IMAGES_STUB_TEMPLATE.format(upgrade_docs_baseline=upgrade_docs_baseline, target=target), encoding="utf-8")
        created.append(images_path.name)
    return created


def load_baseline_values(values_path, upgrade_docs_baseline):
    """values.yaml as it actually was at the release these docs are written
    against (resolved via git) — NOT "before this script's own edit". A
    tag-only bump never touches values.yaml's schema, so a before/after-
    this-run comparison would always be empty regardless of what actually
    changed for this component since the real upgrade_docs_baseline; comparing against
    the true upgrade_docs_baseline is the only way to catch a values.yaml schema change
    (new/removed/renamed key) made by hand as part of this hop, whenever
    during the hop that edit happened. Returns None if the upgrade_docs_baseline can't
    be resolved (e.g. that release hasn't been tagged yet) — callers then
    skip key-change detection rather than comparing against nothing
    meaningful."""
    repo_root = find_repo_root(values_path.parent)
    if repo_root is None:
        return None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(upgrade_docs_baseline))
    if ref is None:
        return None
    rel_values_path = values_path.relative_to(repo_root)
    return git_show_yaml(repo_root, ref, str(rel_values_path))


def load_baseline_state(chart_yaml_path, values_path, upgrade_docs_baseline):
    """(baseline_deps, baseline_values) as they actually were at upgrade_docs_baseline's
    resolved git ref — same ref resolution as load_baseline_values, but
    also pulls Chart.yaml so a caller can tell whether a component's own
    CHART version (not just an image tag under it) has moved from
    upgrade_docs_baseline. Feeds lib.upgradedoc.compute_changed_components, which is
    the ground truth for "has this component actually changed since
    upgrade_docs_baseline at all" — used to decide whether a bump's own "old" version
    for docs should be the true upgrade_docs_baseline (so a component bumped more than
    once in one release cycle still shows upgrade_docs_baseline → final, not
    each-intermediate-hop → final) or whether there's no longer any change
    left to document. Returns (None, None) if the upgrade_docs_baseline can't be
    resolved (e.g. that release hasn't been tagged yet) — callers then
    fall back to their own before-this-run comparison instead."""
    repo_root = find_repo_root(values_path.parent)
    if repo_root is None:
        return None, None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(upgrade_docs_baseline))
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
    """The row whose own Name mentions `friendly` — matched only at word
    boundaries (see lib.upgradedoc.match_dependency/_word_aligned_spans,
    which need the exact same protection for the exact same reason): a
    short friendly/values_key like "mi" is a literal substring of
    "ensurePodiumdAdminUser" (inside "ad-mi-n"), which a raw
    normalize_name() containment check can't tell apart from a real
    word-level match — update_component_table would otherwise silently
    overwrite that unrelated row's own cells instead of inserting "mi"'s
    own new row.

    A canonical "<key> - <basename>" sidecar/shared-image row (see lib.
    chart.canonical_sidecar_row_names) legitimately STARTS with its owning
    dependency's own name as a leading word-aligned span (e.g. "openbao -
    openbao-csi-provider" starts with "openbao") — that leading-span match
    must never satisfy a lookup for the dependency's OWN plain-name
    friendly ("openbao"), same class of collision as the substring case
    above, or update_component_table silently overwrites the SIDECAR's row
    with the DEPENDENCY's own values instead of inserting the dependency's
    own new row (real bug: exactly this, for openbao, when its own row
    didn't exist yet but its sidecar rows already did — see lib.upgradedoc.
    match_dependency_excluding_sidecar_names for the same class of
    collision on the read side). Such a row only matches when `friendly`
    is an exact whole-name match for it (i.e. friendly IS that same
    compound name, not just its leading segment)."""
    norm_friendly = normalize_name(friendly)
    for row in rows:
        if " - " in row["name"] and normalize_name(row["name"]) != norm_friendly:
            continue
        if norm_friendly in _word_aligned_spans(row["name"]):
            return row
    return None


def update_component_table(text, friendly, old_app, new_app, old_chart, new_chart, deps, values,
                            canonical_names=None):
    """Update this component's "Component versions" table row if it's
    already mentioned, or insert a new row if it isn't — in values.yaml's
    own top-level component order relative to the rows already there (see
    lib.upgradedoc.component_order_key/insertion_index), not always at
    the end. canonical_names, when given, lets a bare "global" shared-
    image row (e.g. "nginx-unprivileged") insert at its own real
    values.yaml position instead of always last — see component_order_
    key's own docstring. Returns (new_text, action) where action is
    "updated" or "added" (or None if the doc has no table at all to
    insert into)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)

    app_cell = component_version_cell(old_app, new_app)
    chart_cell = component_version_cell(old_chart, new_chart)

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
        new_key = component_order_key(friendly, deps, key_order, canonical_names)
        existing_keys = [component_order_key(r["name"], deps, key_order, canonical_names) for r in rows]
        idx = insertion_index(new_key, existing_keys)
        insert_at = rows[idx]["line_index"] if idx < len(rows) else rows[-1]["line_index"] + 1
    else:
        # Empty "Component versions" table (header + separator, no data
        # rows yet): insert right after THAT section's separator. Scope the
        # scan to the section — an unscoped scan keeping the last "| --- |"
        # in the whole doc would splice the row into an unrelated pipe
        # table further down (e.g. a settings-migration table under
        # "## Changes"), same section-scoping parse_upgrade_doc_rows uses.
        insert_at = None
        in_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if COMPONENT_VERSIONS_HEADING_RE.match(stripped):
                in_section = True
                continue
            if in_section and re.match(r"^##\s+\S", line):
                break
            if in_section and re.match(r"^\|\s*:?-+:?\s*\|", stripped):
                insert_at = i + 1
                break
        if insert_at is None:
            return text, None
    lines.insert(insert_at, new_row_line)
    return "".join(lines), "added"


def remove_component_row(text, friendly):
    """Delete this component's row from the "Component versions" table
    entirely — the counterpart to update_component_table's "added"/
    "updated" for a bump that nets out to no change from upgrade_docs_baseline at all
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
                          old_chart, new_chart, image_paths, version_paths=()):
    """`image_paths` (see lib.chart.image_paths_for) are rendered as
    "Image tag pin `<values_key>.<path>.tag`" bullets — the ordinary
    "{repository, tag}" block shape. `version_paths` (see lib.chart.
    version_paths_for) are for a component whose real app version isn't
    expressed that way at all (e.g. eck-stack's bare "...version:"
    fields, the ECK operator's own CRD convention) — rendered as
    "Version pin `<path>`" bullets instead, no ".tag" suffix (there's no
    sibling "repository:" key to go with it). Passing image_paths for a
    component actually shaped like version_paths (or vice versa) would
    silently generate a bullet pointing at a values.yaml path that
    doesn't exist — callers must use lib.chart.image_paths_for/version_
    paths_for's own registration to know which applies.

    `new_chart == "-"` means a NATIVE_COMPONENTS component (see lib.chart
    .NATIVE_COMPONENTS) with no Chart.yaml dependency/chart version at
    all — the heading omits the "(chart ...)" parenthetical entirely and
    chart_changed is forced False, so the "Helm chart `...` bump" bullet
    (which needs a real chart_name/old_chart/new_chart triple) is never
    emitted either.

    old_chart is None (a component with no baseline Chart.yaml dependency
    at all — genuinely brand new this hop) renders "(chart <new_chart>,
    new)", the chart-side sibling of old_app is None below; the "Helm
    chart `...` bump" bullet is suppressed for it too, same as the
    new_chart == "-" case, since there's no real "old → new" chart
    transition to describe.

    old_app is None (real case: openbao — actual_app_version(baseline_
    values, ...) never even attempts its own subchart_app_version
    fallback for the BASELINE side, so a component whose real app
    version only ever resolves via that fallback has no baseline value
    to compare against at all, same as a genuinely brand-new component)
    renders "<app> (new)", matching component_version_cell's own
    "(new)" convention for exactly this case — never a nonsensical
    "None → <app>". old_app == new_app (real case: a component whose
    own PRIMARY image is untouched but still qualifies for a row/
    section because SOME OTHER path in its subtree changed — e.g. a
    brand-new sidecar of its own; see compute_changed_components)
    renders "<app> (unchanged)", matching chart_suffix's own existing
    "(chart ..., unchanged)" convention, instead of a meaningless
    "<app> → <app>" self-transition — same reasoning throughout: this
    doc is about VERSION changes, and there isn't one to report in
    either case."""
    if new_chart == "-":
        chart_changed = False
        chart_suffix = ""
    elif old_chart is None:
        chart_changed = False
        chart_suffix = f" (chart {new_chart}, new)"
    else:
        chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
        chart_suffix = f" (chart {old_chart} → {new_chart})" if chart_changed else f" (chart {new_chart}, unchanged)"
    if old_app is None:
        app_heading = f"{new_app} (new)"
    elif normalize_version(old_app) == normalize_version(new_app):
        app_heading = f"{new_app} (unchanged)"
    else:
        app_heading = f"{old_app} → {new_app}"
    lines = [f"### {friendly} {app_heading}{chart_suffix}\n\n"]
    if old_app is None:
        lines.append(f"PodiumD {target} introduces **{friendly}** at app version {new_app}.\n\n")
    elif normalize_version(old_app) == normalize_version(new_app):
        lines.append(f"**{friendly}**'s own app version ({new_app}) is unchanged this hop.\n\n")
    else:
        lines.append(f"PodiumD {target} upgrades **{friendly}** from app version {old_app}\n")
        lines.append(f"to {new_app}.\n\n")
    if old_app is None:
        pin_suffix = f"`{new_app}` (new)"
    elif normalize_version(old_app) == normalize_version(new_app):
        pin_suffix = f"`{new_app}` (unchanged)"
    else:
        pin_suffix = f"`{old_app}` → `{new_app}`"
    if chart_changed:
        lines.append(f"- Helm chart `{chart_name}` `{old_chart}` → `{new_chart}` in\n")
        lines.append("  `charts/podiumd/Chart.yaml`.\n")
    for path in image_paths:
        lines.append(f"- Image tag pin `{values_key}.{path}.tag` {pin_suffix} in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    for path in version_paths:
        lines.append(f"- Version pin `{values_key}.{path}` {pin_suffix} in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    lines.append(f"- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def insert_changes_section(text, section_text, friendly, deps, values, canonical_names=None):
    """Insert section_text as a new "### ..." block into the "## Changes"
    section, in values.yaml's own top-level component order relative to
    the blocks already there (see lib.upgradedoc.component_order_key/
    insertion_index) — not always at the end. canonical_names, when
    given, lets a bare "global" shared-image section (e.g. "nginx-
    unprivileged") insert at its own real values.yaml position instead
    of always last — see component_order_key's own docstring. Appends
    right before the next "## " heading (or EOF) if the section doesn't
    exist yet, or has no blocks of its own yet to compare against."""
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
        new_key = component_order_key(friendly, deps, key_order, canonical_names)
        existing_keys = [component_order_key(b["heading"], deps, key_order, canonical_names) for b in blocks]
        idx = insertion_index(new_key, existing_keys)
        insert_at = blocks[idx]["start"] if idx < len(blocks) else section_end

    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def remove_changes_section(text, friendly):
    """Delete this component's "### ..." block from the "## Changes"
    section entirely — the counterpart to insert_changes_section for a
    bump that nets out to no change from upgrade_docs_baseline at all. Also swallows
    the block's own trailing blank line(s) so removal doesn't leave a
    double gap before whatever follows. Matched only at word boundaries
    (see find_component_row's own identical protection) — a short
    friendly/values_key must never delete an unrelated block just
    because it's a coincidental mid-word substring of that block's own
    heading. Returns (new_text, removed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    norm_friendly = normalize_name(friendly)
    block = next((b for b in blocks if norm_friendly in _word_aligned_spans(b["heading"])), None)
    if block is None:
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


def dep_for_values_key(deps, values_key):
    """The Chart.yaml dependency whose own alias-or-name equals
    values_key — the reverse of "dep.get('alias', dep['name'])" — or
    None if no dependency owns that key (e.g. an orphan top-level
    values.yaml block with no separate chart, like frankgateway)."""
    for dep in deps:
        if dep.get("alias", dep["name"]) == values_key:
            return dep
    return None


def resolve_component_own_version_change(key, target_deps, baseline_deps, target_values, baseline_values, chart_dir,
                                          images_baseline):
    """(dep, chart_name, old_chart, new_chart, old_app, new_app, unchanged)
    for `key` (a member of lib.upgradedoc.compute_changed_components'
    own result) — `unchanged` is True when BOTH this component's own
    chart version and its own primary app version resolve as identical
    between baseline and target (the images-baseline.yaml fallback
    included — see app_version_pin_via_images_baseline), meaning
    whatever else made `key` register as changed (almost always a
    brand-new/changed sidecar nested under it — that gets its own
    separate row via lib.image_docs.add_missing_sidecar_rows) has
    NOTHING to do with this component's own version; -upgrade.md's own
    "Component versions" table is about version changes specifically,
    so a redundant "(unchanged)"-only row for the OWNING component
    itself would just be noise on top of the sidecar's own row (real
    case: zac gaining a brand-new opentelemetry-collector-contrib
    sidecar, or openbao gaining three brand-new sidecars of its own,
    neither changing that component's OWN app/chart version at all).

    Returns None (nothing resolved) for a key matching neither a real
    Chart.yaml dependency nor a lib.chart.NATIVE_COMPONENTS entry —
    shouldn't happen for a key compute_changed_components itself ever
    returns, but never assumed. Shared by add_missing_component_rows
    (skip adding such a row) and lib.docs_consistency.check_docs_
    consistency's own "changed but has no row" finding (skip demanding
    one), so the two can never drift on which keys actually need a
    row of their own."""
    dep = dep_for_values_key(target_deps, key)
    if dep is not None:
        chart_name = dep["name"]
        baseline_dep = dep_for_values_key(baseline_deps, key) if baseline_deps else None
        old_chart = str(baseline_dep["version"]) if baseline_dep else None
        new_chart = str(dep["version"])
    elif key in NATIVE_COMPONENTS:
        chart_name = key
        old_chart = None
        new_chart = "-"
    else:
        return None
    chart_unchanged = new_chart == "-" or (old_chart is not None
                                           and normalize_version(old_chart) == normalize_version(new_chart))
    old_app = actual_app_version(baseline_values, key, chart_name) if baseline_values else None
    new_app = actual_app_version(target_values, key, chart_name, chart_dir=chart_dir, dep=dep)
    if old_app is None and baseline_values:
        old_app = app_version_pin_via_images_baseline(target_values, key, chart_name, chart_dir, target_deps,
                                                       images_baseline)
    if old_app is None and baseline_values and dep is not None and chart_unchanged:
        # subchart_app_version's own vendored-.tgz lookup is keyed on
        # dep["version"] (see lib.chart.subchart_app_version) — never
        # attempted for the baseline side above (actual_app_version's own
        # chart_dir/dep params are deliberately omitted there), since
        # there's normally no vendored artifact for a historical baseline
        # ref to read at all. But chart_unchanged means dep's own version
        # here IS the baseline's chart version too — the exact same
        # vendored .tgz backs both sides — so it's safe to attempt this
        # fallback using the CURRENT chart_dir/dep after all. Real case:
        # openbao's own baseline app version was unresolvable through
        # every other tier (its own "server.image.tag" is deliberately
        # left blank for the chart's appVersion to supply — see actual_
        # app_version's own docstring — and it long predates images-
        # baseline.yaml), wrongly rendering "(new)" for a component whose
        # own chart version (0.28.4) didn't change at all this hop —
        # inconsistent with any other component in the exact same
        # situation (e.g. zac, whose own app version resolves normally at
        # both ends and so correctly gets skipped instead of a redundant
        # row) — see resolve_component_own_version_change's own docstring
        # for why an unchanged own component doesn't get a row/section.
        old_app = actual_app_version(baseline_values, key, chart_name, chart_dir=chart_dir, dep=dep)
    app_unchanged = (old_app is not None and new_app is not None
                     and normalize_version(old_app) == normalize_version(new_app))
    return dep, chart_name, old_chart, new_chart, old_app, new_app, (chart_unchanged and app_unchanged)


def add_missing_component_rows(text, chart_dir, target_deps, target_values, baseline_deps, baseline_values,
                                actual_changed_keys, target):
    """Insert a new "Component versions" table row + matching "### ..."
    Changes section for every key in `actual_changed_keys` (see
    lib.upgradedoc.compute_changed_components) that doesn't already have
    a row — read straight from `text` itself via the same match_dependency
    lookup lib.docs_consistency.check_docs_consistency's own "component
    ... changed vs ... but has no row" finding uses, so this always
    targets exactly what that finding reports.

    Reuses update_component_table/make_changes_section exactly as
    update-component-version's own single-component bump does, just
    driven by Chart.yaml/values.yaml's CURRENT state instead of a
    human-typed <app-version>/<chart-version> pair — an auto-added row is
    indistinguishable from one a real bump would have produced, right
    down to using the dependency's own literal name/alias as the row's
    Name (immune to a "Keycloak" vs "keycloak-operator" style naming
    drift a hand-picked display name can fall into, since match_dependency
    always matches its own exact source unambiguously).

    A key with no matching Chart.yaml dependency AND no lib.chart.
    NATIVE_COMPONENTS entry either is skipped — there's no dep["version"]
    to read a Helm chart version from, and nothing here can tell it apart
    from a genuinely unrelated top-level key; add that row by hand. A
    NATIVE_COMPONENTS key (e.g. frankgateway) instead gets old_chart=None,
    new_chart="-" — the same chart-less convention update-component-
    version's own "native" chart-version already writes — so its row's
    Helm-chart cell reads the bare "-" placeholder, never a guessed
    version. A key whose app version can't be resolved via actual_app_
    version's own known shapes (<key>.image.tag, frontend/backend,
    COMPONENT_VERSION_PATHS' bare version fields, or a registered
    COMPONENT_IMAGE_PATHS component's vendored-chart appVersion fallback
    — see that function's own docstring) gets a "-" app-version
    placeholder and a short TODO-stub Changes section instead of
    guessing at prose. Returns (new_text, added_names)."""
    images_baseline = load_images_baseline(chart_dir)
    matched_keys = set()
    for row in parse_upgrade_doc_rows(text):
        # match_dependency_excluding_sidecar_names, not match_dependency
        # directly — a canonical sidecar row like "redis-operator -
        # redis" must never register as if it were redis-operator's OWN
        # row, which would wrongly suppress adding redis-operator's real
        # row if IT independently changed with no row of its own yet.
        dep = match_dependency_excluding_sidecar_names(row["name"], target_deps)
        if dep:
            matched_keys.add(dep.get("alias", dep["name"]))
            continue
        native_key = match_native_component(row["name"], NATIVE_COMPONENTS)
        if native_key:
            matched_keys.add(native_key)

    added_names = []
    for key in sorted(actual_changed_keys - matched_keys):
        resolved = resolve_component_own_version_change(
            key, target_deps, baseline_deps, target_values, baseline_values, chart_dir, images_baseline)
        if resolved is None:
            continue
        dep, chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
        if unchanged:
            # This component's OWN chart+app are both unchanged — whatever
            # else made `key` register as changed (almost always a brand-
            # new/changed sidecar nested under it) already gets its own
            # separate row via add_missing_sidecar_rows; a redundant
            # "(unchanged)"-only row here would just be noise.
            continue

        text, table_action = update_component_table(
            text, key, old_app, new_app if new_app is not None else "-", old_chart, new_chart,
            target_deps, target_values)
        if table_action is None:
            continue  # doc has no "Component versions" table at all to insert into

        text, _ = remove_changes_section(text, key)
        if new_app is not None:
            # version_paths_for wins outright when registered — see
            # make_changes_section's own docstring for why image_paths_for's
            # generic "<key>.image.tag" guess would be wrong for a
            # component actually shaped like version_paths (e.g. eck-stack).
            version_paths = version_paths_for(chart_name)
            image_paths = [] if version_paths else image_paths_for(chart_name)
            section = make_changes_section(key, target, chart_name, key, old_app, new_app,
                                            old_chart, new_chart, image_paths, version_paths)
        else:
            chart_suffix = (f"{old_chart} → {new_chart}"
                             if old_chart and normalize_version(old_chart) != normalize_version(new_chart)
                             else new_chart)
            section = (f"### {key} {chart_suffix}\n\n"
                        f"TODO: describe this component's changes — its app version could not be "
                        f"resolved automatically.\n\n")
        text = insert_changes_section(text, section, key, target_deps, target_values)
        added_names.append(key)

    return text, added_names


def values_delta_section_heading(friendly, old_app, new_app, old_chart, new_chart):
    """The "## <friendly> ..." heading for this component's own values-
    deltas.md section — carries the app/chart-transition info a flat
    "- **<friendly>** app ..." bullet used to restate on its own first
    line: once the heading itself already says it, repeating it as the
    section's first bullet is pure noise (that's the whole point of
    giving each component its own section instead of a shared flat
    list). `new_chart == "-"` means a NATIVE_COMPONENTS component (see
    lib.chart.NATIVE_COMPONENTS) with no Chart.yaml dependency/chart
    version at all — the "(chart ...)" clause is dropped entirely rather
    than rendered as the misleading "chart None → -". `old_app`/
    `old_chart` may be None (nothing resolved at upgrade_docs_baseline,
    e.g. a component added since then) — treated as "unchanged against
    the new value" rather than a literal "None → ...".

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
            return (f"## {friendly} — TODO: describe this component's changes; its app version "
                     f"could not be resolved automatically.\n")
        chart_bit = (f"chart {old_chart} → {new_chart}"
                     if old_chart and normalize_version(old_chart) != normalize_version(new_chart)
                     else f"chart {new_chart}, unchanged")
        return (f"## {friendly} {chart_bit} — TODO: describe this component's changes; its app "
                f"version could not be resolved automatically.\n")

    app_changed = normalize_version(old_app or new_app) != normalize_version(new_app)
    app_bit = f"{old_app or new_app} → {new_app}" if app_changed else f"{new_app} (unchanged)"
    if new_chart == "-":
        chart_bit = ""
    else:
        chart_changed = normalize_version(old_chart or new_chart) != normalize_version(new_chart)
        chart_bit = f" (chart {old_chart or new_chart} → {new_chart})" if chart_changed \
            else f" (chart {new_chart}, unchanged)"
    return f"## {friendly} {app_bit}{chart_bit}\n"


def find_values_delta_section(text, friendly, deps, canonical_names=None):
    """The existing "## ..." section (see lib.upgradedoc.parse_values_
    delta_sections/changes_heading_identities) that already names the
    SAME component identity `friendly` does — reused for a real
    Chart.yaml dependency/NATIVE_COMPONENTS friendly name, a canonical
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


def insert_values_delta_section(text, friendly, heading_line, body_lines, deps, values, canonical_names=None):
    """Insert a brand-new "## <heading_line>" section (heading_line
    already includes its own trailing newline) + body_lines as its
    content, in values.yaml's own top-level component order relative to
    the "## " sections already there (see lib.upgradedoc.component_
    order_key/insertion_index) — not always at the end. Mirrors
    insert_changes_section's own positioning logic, one heading level
    up (top-level "## " instead of "## Changes"'s own nested "### ...")."""
    body = "".join(body_lines)
    section_text = heading_line + "\n" + body + ("\n" if body else "")
    sections = parse_values_delta_sections(text)
    lines = text.splitlines(keepends=True)
    if not sections:
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text + section_text

    key_order = values_key_order(values)
    new_key = component_order_key(friendly, deps, key_order, canonical_names)
    existing_keys = [component_order_key(s["heading"], deps, key_order, canonical_names) for s in sections]
    idx = insertion_index(new_key, existing_keys)
    insert_at = sections[idx]["start"] if idx < len(sections) else len(lines)
    if insert_at > 0 and lines[insert_at - 1].strip():
        lines.insert(insert_at, "\n")
        insert_at += 1
    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def append_values_delta_section_body(text, section, new_lines):
    """Append new_lines at the end of an EXISTING values-deltas.md
    section (see find_values_delta_section) — right before its own next
    "## " heading (or EOF) — blank-line-separated from whatever already
    ends the section (append_to_doc's own convention, just section-
    scoped instead of always true EOF), never disturbing whatever
    hand-written prose or previously-added lines already sit there."""
    lines = text.splitlines(keepends=True)
    head = "".join(lines[:section["end"]])
    tail = "".join(lines[section["end"]:])
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


def sync_values_delta_sections(text, chart_dir, target_deps, target_values, baseline_deps, baseline_values,
                                actual_changed_keys, canonical_names=None):
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
    NATIVE_COMPONENTS entry either is skipped when it needs a brand-new
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
        elif key in NATIVE_COMPONENTS:
            chart_name = key
            old_chart = None
            new_chart = "-"
        else:
            continue

        old_app = actual_app_version(baseline_values, key, chart_name) if baseline_values else None
        new_app = actual_app_version(target_values, key, chart_name, chart_dir=chart_dir, dep=dep)
        heading_line = values_delta_section_heading(key, old_app, new_app, old_chart, new_chart)
        text = insert_values_delta_section(text, key, heading_line, key_lines, target_deps, target_values,
                                            canonical_names)
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
        body = "".join(lines[section["start"] + 1:section["end"]]).strip()
        if body:
            continue
        start, end = section["start"], section["end"]
        while end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        removed_headings.append(section["heading"])
    return "".join(lines), list(reversed(removed_headings))


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
                            paths_to_update, repos, new_tags_by_path, deps, values):
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
            # NATIVE_COMPONENTS component (see lib.chart.NATIVE_COMPONENTS)
            # — no chart at all, so no "(chart ...)" clause to render.
            item_text = f"{friendly} {old_app} -> {new_app}."
        else:
            chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
            chart_bit = f"{old_chart} -> {new_chart}" if chart_changed else f"{new_chart}, unchanged"
            item_text = f"{friendly} {old_app} -> {new_app} (chart {chart_bit})."

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
