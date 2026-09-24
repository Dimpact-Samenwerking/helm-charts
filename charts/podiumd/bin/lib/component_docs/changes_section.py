"""The upgrade doc's "Component versions" table row + "## Changes"
section for a single component's version bump: finding/updating/
removing a component's own table row (find_component_row, update_
component_table, remove_component_row), building and inserting a
"## <component>" changes section (make_changes_section, insert_changes_
section, remove_changes_section), stripping stale bare TODO
placeholders left over from a doc-scaffolding stub once real content
replaces them (_strip_bare_changes_todo, _find_standalone_placeholder_
line, _strip_standalone_placeholder_line, _is_bare_placeholder_span,
strip_stale_upgrade_placeholders), and backfilling table rows/changes
sections for components a run didn't otherwise touch but that changed
since upgrade_docs_baseline anyway (dep_for_values_key, resolve_
component_own_version_change, add_missing_component_rows). Shared by
update-component-version, update-image-version, and fix-doc-
consistency. Split out of the former flat lib/component_docs.py, now
the lib.component_docs package.

VersionChange/OrderingContext/ComponentIdentity/ComponentState/
DocContext below bundle this module's own repeated parameter groups
(each documents on itself which functions share it and why) purely to
keep those functions' own argument/local-variable counts under
pylint's too-many-arguments/too-many-locals thresholds -- not a
general-purpose abstraction, just this module's own plumbing."""

import re

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.registered_paths import component_chart_versions
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import native_components
from lib.chart.registered_paths import version_paths_for
from lib.chart.values_tree_primitives import values_key_of
from lib.component_docs.baseline_doc_stubs import UPGRADE_CHANGES_STUB_TODO_LINE
from lib.component_docs.baseline_doc_stubs import UPGRADE_INTRO_STUB_TODO_LINE
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.consistency_checks import resolve_component_identity
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import changes_section_bounds
from lib.upgradedoc.sorting_and_ordering import component_order_key
from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import COMPONENT_VERSIONS_HEADING_RE
from lib.upgradedoc.string_and_parsing_basics import TableRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names
from lib.upgradedoc.string_and_parsing_basics import match_native_component
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.string_and_parsing_basics import text_names
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell
from lib.upgradedoc.version_cells_and_key_changes import version_change_suffix
from lib.yaml_types import YamlMapping


@dataclass
class VersionChange:
    """A component's own before/after app + Helm chart version pair,
    bundled together since update_component_table/make_changes_section
    both need all four the same way. `new_chart == "-"` means a native_
    components component with no Chart.yaml dependency at all (see
    make_changes_section's own docstring); `old_chart is None` means a
    component with no baseline Chart.yaml dependency (genuinely new this
    hop); `old_app is None` means no baseline app version could be
    resolved at all (also rendered as "new") -- same conventions
    throughout this module."""

    old_app: str | None = None
    new_app: str | None = None
    old_chart: str | None = None
    new_chart: str | None = None


@dataclass
class OrderingContext:
    """deps/values/canonical_names, bundled since update_component_table/
    insert_changes_section both use them for nothing but component_
    order_key/insertion_index's own ordering lookup -- see component_
    order_key's own docstring for what canonical_names is for (lets a
    bare "global" shared-image row/section insert at its own real
    values.yaml position instead of always last)."""

    deps: list[ChartDependency]
    values: YamlMapping | None
    canonical_names: dict[str, tuple[str, ...]] | None = None


@dataclass
class ComponentIdentity:
    """A component's own friendly display name / Chart.yaml dependency
    name / values.yaml top-level key triple, bundled since make_changes_
    section renders all three into different parts of the same section
    (heading + prose use `friendly`, the "Helm chart `...`" bullet uses
    `chart_name`, the "Image/Version pin `...`" bullets use
    `values_key`) -- see its own docstring for exactly where each
    lands."""

    friendly: str
    chart_name: str
    values_key: str


@dataclass
class ComponentState:
    """A target-or-baseline deps/values pair -- resolve_component_own_
    version_change/add_missing_component_rows both need one of each
    side, compared against each other, and never mix a target dep with
    a baseline value or vice versa by construction."""

    deps: list[ChartDependency]
    values: YamlMapping


@dataclass
class BaselineState:
    """deps/values as they stood at upgrade_docs_baseline. deps is None
    when no baseline was resolved: baseline comparisons are then skipped
    (see lib.upgradedoc.resolve_component_row)."""

    deps: list[ChartDependency] | None
    values: YamlMapping | None


@dataclass
class DocContext:
    """add_missing_component_rows' own chart_dir/target-release-label/
    upgrade_docs_baseline triple -- bundled purely to keep its own (and
    its own helpers') argument count down; the three have nothing in
    common except being threaded through unchanged to resolve_
    component_own_version_change and make_changes_section."""

    chart_dir: Path
    target: str
    upgrade_docs_baseline: str | None = None


def find_component_row(rows: list[TableRow], friendly: str):
    """The row whose Name names `friendly` (see text_names): at word
    boundaries, so "mi" never takes the "ensurePodiumdAdminUser" row,
    and a plain "openbao" never takes an "openbao - openbao-csi-provider"
    sidecar row. None when no row does."""
    return next((row for row in rows if text_names(row["name"], friendly)), None)


def _new_row_insert_index(lines: list[str], rows: list[TableRow], friendly: str, ordering: OrderingContext):
    """Line index to insert a brand-new component row at, matching
    update_component_table's own ordering rules: in values.yaml's own
    top-level component order relative to the rows already there when
    the table has any rows at all (see component_order_key/
    insertion_index), or right after the "Component versions" section's
    own separator line when the table is still empty (header +
    separator, no data rows yet) — scoped to THAT section specifically,
    since an unscoped scan for the last "| --- |" in the whole doc would
    splice the row into an unrelated pipe table further down (e.g. a
    settings-migration table under "## Changes"), same section-scoping
    parse_upgrade_doc_rows uses. None if the doc has no "Component
    versions" table at all to insert into."""
    if rows:
        key_order = values_key_order(ordering.values)
        new_key = component_order_key(friendly, ordering.deps, key_order, ordering.canonical_names, ordering.values)
        existing_keys = [
            component_order_key(r["name"], ordering.deps, key_order, ordering.canonical_names, ordering.values)
            for r in rows
        ]
        idx = insertion_index(new_key, existing_keys)
        return rows[idx]["line_index"] if idx < len(rows) else rows[-1]["line_index"] + 1
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if COMPONENT_VERSIONS_HEADING_RE.match(stripped):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+\S", line):
            break
        if in_section and re.match(r"^\|\s*:?-+:?\s*\|", stripped):
            return i + 1
    return None


def update_component_table(text: str, friendly: str, change: VersionChange, ordering: OrderingContext):
    """Update this component's "Component versions" table row if it's
    already mentioned, or insert a new row if it isn't — in values.yaml's
    own top-level component order relative to the rows already there (see
    lib.upgradedoc.component_order_key/insertion_index), not always at
    the end. `ordering.canonical_names`, when set, lets a bare "global"
    shared-image row (e.g. "nginx-unprivileged") insert at its own real
    values.yaml position instead of always last — see component_order_
    key's own docstring. Returns (new_text, action) where action is
    "updated" or "added" (or None if the doc has no table at all to
    insert into)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)

    app_cell = component_version_cell(change.old_app, change.new_app)
    chart_cell = component_version_cell(change.old_chart, change.new_chart)

    if row is not None:
        old_line = lines[row["line_index"]]
        cells = [c.strip() for c in old_line.strip().strip("|").split("|")]
        # No new version for a cell: leave what the row already says.
        if app_cell is not None:
            cells[1] = app_cell
        if chart_cell is not None:
            cells[2] = chart_cell
        suffix = "\n" if old_line.endswith("\n") else ""
        lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + suffix
        return "".join(lines), "updated"

    new_row_line = f"| {friendly} | {app_cell or '-'} | {chart_cell or '-'} | - |\n"
    insert_at = _new_row_insert_index(lines, rows, friendly, ordering)
    if insert_at is None:
        return text, None
    lines.insert(insert_at, new_row_line)
    return "".join(lines), "added"


def remove_component_row(text: str, friendly: str):
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


def make_changes_section(
    identity: ComponentIdentity,
    target: str,
    change: VersionChange,
    image_paths: Sequence[str],
    version_paths: Sequence[str] = (),
) -> str:
    """`image_paths` (see lib.chart.image_paths_for) are rendered as
    "Image tag pin `<identity.values_key>.<path>.tag`" bullets — the
    ordinary "{repository, tag}" block shape. `version_paths` (see lib.
    chart.version_paths_for) are for a component whose real app version
    isn't expressed that way at all (e.g. eck-stack's bare "...version:"
    fields, the ECK operator's own CRD convention) — rendered as
    "Version pin `<path>`" bullets instead, no ".tag" suffix (there's no
    sibling "repository:" key to go with it). Passing image_paths for a
    component actually shaped like version_paths (or vice versa) would
    silently generate a bullet pointing at a values.yaml path that
    doesn't exist — callers must use lib.chart.image_paths_for/version_
    paths_for's own registration to know which applies.

    `change.new_chart == "-"` means a native_components component (see
    lib.chart.native_components) with no Chart.yaml dependency/chart
    version at all — the heading omits the "(chart ...)" parenthetical
    entirely and chart_changed is forced False, so the "Helm chart
    `...` bump" bullet (which needs a real chart_name/old_chart/
    new_chart triple) is never emitted either.

    `change.old_chart is None` (a component with no baseline Chart.yaml
    dependency at all — genuinely brand new this hop) renders "(chart
    <new_chart>, new)", the chart-side sibling of old_app is None
    below; the "Helm chart `...` bump" bullet is suppressed for it too,
    same as the new_chart == "-" case, since there's no real "old →
    new" chart transition to describe.

    `change.old_app is None` (real case: openbao — actual_app_version
    (baseline_values, ...) never even attempts its own subchart_app_
    version fallback for the BASELINE side, so a component whose real
    app version only ever resolves via that fallback has no baseline
    value to compare against at all, same as a genuinely brand-new
    component) renders "<app> (new)", matching component_version_
    cell's own "(new)" convention for exactly this case — never a
    nonsensical "None → <app>". `change.old_app == change.new_app`
    (real case: a component whose own PRIMARY image is untouched but
    still qualifies for a row/section because SOME OTHER path in its
    subtree changed — e.g. a brand-new sidecar of its own; see compute_
    changed_components) renders "<app> (unchanged)", matching chart_
    suffix's own existing "(chart ..., unchanged)" convention, instead
    of a meaningless "<app> → <app>" self-transition — same reasoning
    throughout: this doc is about VERSION changes, and there isn't one
    to report in either case."""
    if change.new_chart == "-":
        chart_changed = False
        chart_suffix = ""
    elif change.old_chart is None:
        chart_changed = False
        chart_suffix = f" (chart {change.new_chart}, new)"
    else:
        chart_changed = normalize_version(change.old_chart) != normalize_version(change.new_chart)
        chart_suffix = (
            f" (chart {change.old_chart} → {change.new_chart})"
            if chart_changed
            else f" (chart {change.new_chart}, unchanged)"
        )
    app_suffix = version_change_suffix(change.old_app, change.new_app)
    app_heading = f"{change.new_app} {app_suffix}" if app_suffix else f"{change.old_app} → {change.new_app}"
    lines = [f"### {identity.friendly} {app_heading}{chart_suffix}\n\n"]
    if change.old_app is None:
        lines.append(f"PodiumD {target} introduces **{identity.friendly}** at app version {change.new_app}.\n\n")
    elif normalize_version(change.old_app) == normalize_version(change.new_app):
        lines.append(f"**{identity.friendly}**'s own app version ({change.new_app}) is unchanged this hop.\n\n")
    else:
        lines.append(f"PodiumD {target} upgrades **{identity.friendly}** from app version {change.old_app}\n")
        lines.append(f"to {change.new_app}.\n\n")
    pin_suffix = f"`{change.new_app}` {app_suffix}" if app_suffix else f"`{change.old_app}` → `{change.new_app}`"
    if chart_changed:
        lines.append(f"- Helm chart `{identity.chart_name}` `{change.old_chart}` → `{change.new_chart}` in\n")
        lines.append("  `charts/podiumd/Chart.yaml`.\n")
    for path in image_paths:
        lines.append(f"- Image tag pin `{identity.values_key}.{path}.tag` {pin_suffix} in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    for path in version_paths:
        lines.append(f"- Version pin `{identity.values_key}.{path}` {pin_suffix} in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    lines.append(f"- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def _is_bare_placeholder_span(lines: list[str], start: int, end: int, placeholder_text: str):
    """True if lines[start:end] contains nothing but blank lines and
    exactly one line matching placeholder_text (stripped comparison) —
    the shared exact-shape "is this span JUST the placeholder, nothing
    else" check every stub-placeholder detector that owns a CLOSED span
    (a heading's own nested content, with nothing legitimate expected to
    sit alongside the placeholder) reuses in this module — currently
    "## Changes"' own bare TODO. Deliberately an exact-shape match, never
    a substring/heuristic check for the placeholder's own wording — real,
    human-written prose that happens to mention it (a real note to self,
    say) must never be silently deleted just because it shares wording
    with the stub. See _find_standalone_placeholder_line for the OTHER
    shape (a placeholder sitting alongside OTHER legitimate content, e.g.
    upgrade.md's own intro blockquote next to its own intro TODO)."""
    non_blank = [line.strip() for line in lines[start:end] if line.strip()]
    return non_blank == [placeholder_text.strip()]


def _find_standalone_placeholder_line(lines: list[str], end: int, placeholder_text: str):
    """Index of a line within lines[:end] whose stripped content exactly
    equals placeholder_text AND stands alone as its own paragraph — a
    blank line, or the start of the document, immediately before it; a
    blank line, or `end` itself, immediately after — or None if no such
    line exists. Unlike _is_bare_placeholder_span, this tolerates OTHER
    legitimate content anywhere else in lines[:end] (upgrade.md's own
    intro blockquote sits right next to its own intro TODO placeholder,
    see UPGRADE_INTRO_STUB_TODO_LINE) — it only demands that the
    placeholder ITSELF is isolated, not that nothing else is present.
    Never a substring match: a line must stripped-equal placeholder_text
    exactly."""
    target = placeholder_text.strip()
    for i in range(end):
        if lines[i].strip() != target:
            continue
        before_ok = i == 0 or not lines[i - 1].strip()
        after_ok = i + 1 == end or not lines[i + 1].strip()
        if before_ok and after_ok:
            return i
    return None


def _strip_standalone_placeholder_line(lines: list[str], end: int, placeholder_text: str):
    """Removes the standalone placeholder line found by _find_standalone_
    placeholder_line (if any) from `lines` in place, collapsing the
    double blank-line gap left behind so exactly one blank line survives
    between its former neighbors. Returns True if something was actually
    removed, False (a no-op) otherwise."""
    idx = _find_standalone_placeholder_line(lines, end, placeholder_text)
    if idx is None:
        return False
    del lines[idx]
    if 0 < idx < len(lines) and not lines[idx].strip() and not lines[idx - 1].strip():
        del lines[idx]
    return True


def _strip_bare_changes_todo(lines: list[str], changes_idx: int, end_bound: int):
    """If lines[changes_idx+1:end_bound] is JUST "## Changes"' own bare
    TODO stub (see _is_bare_placeholder_span), deletes it in place and
    returns the new end_bound (changes_idx + 1) — shared by insert_
    changes_section (which handles blank-line normalization itself,
    generically, for every insertion point, so doesn't need this to add
    one back) and strip_stale_upgrade_placeholders (which has no such
    downstream step of its own and inserts the blank line itself).
    Returns end_bound UNCHANGED if there's nothing to strip."""
    if not _is_bare_placeholder_span(lines, changes_idx + 1, end_bound, UPGRADE_CHANGES_STUB_TODO_LINE):
        return end_bound
    del lines[changes_idx + 1 : end_bound]
    return changes_idx + 1


def _insert_index_for_empty_changes_section(lines: list[str], changes_idx: int, section_end: int):
    """insert_at for insert_changes_section's own "no ### blocks yet"
    branch: strips BOTH of upgrade.md's own stub placeholders first (see
    insert_changes_section's own docstring for why), recomputing
    changes_idx/section_end if that shifted line indices, then returns
    "## Changes"' own end bound with its bare TODO (if any) also
    stripped — see _strip_bare_changes_todo. Split out of insert_
    changes_section purely to keep its own local-variable count down."""
    first_heading_idx = next((i for i, line in enumerate(lines) if re.match(r"^##\s+\S", line)), len(lines))
    if _strip_standalone_placeholder_line(lines, first_heading_idx, UPGRADE_INTRO_STUB_TODO_LINE):
        # Line indices shifted -- recompute rather than patch by a
        # guessed amount (the standalone-placeholder removal may take
        # one line or two, depending on its own neighbors).
        new_changes_idx, section_end = changes_section_bounds(lines)
        if new_changes_idx is not None:
            changes_idx = new_changes_idx
    return _strip_bare_changes_todo(lines, changes_idx, section_end)


def _normalize_blank_line_before_insert(lines: list[str], insert_at: int):
    """Adjusts `lines` in place so exactly one blank line sits
    immediately before `insert_at`, returning the (possibly shifted)
    insert_at — rather than assuming one is already there: section_
    text's own leading edge never supplies it (make_changes_section/
    make_image_changes_section both start straight with "### "), and
    the PRECEDING content's own trailing blank can legitimately be gone
    by the time this runs (e.g. fix-doc-consistency's own EOF-blank-
    line collapsing already stripped it — see lib.checks.markdown).
    Real bug this fixes: re-inserting whatever block currently sorts
    LAST in the file used to silently depend on that trailing blank
    still being there, producing a "### ..." heading with zero blank
    lines above it (MD022/MD032) whenever it wasn't. Split out of
    insert_changes_section purely to keep its own local-variable count
    down."""
    blank_count = 0
    i = insert_at - 1
    while i >= 0 and not lines[i].strip():
        blank_count += 1
        i -= 1
    if blank_count == 0:
        lines[insert_at:insert_at] = ["\n"]
        insert_at += 1
    elif blank_count > 1:
        del lines[insert_at - (blank_count - 1) : insert_at]
        insert_at -= blank_count - 1
    return insert_at


def insert_changes_section(text: str, section_text: str, friendly: str, ordering: OrderingContext):
    """Insert section_text as a new "### ..." block into the "## Changes"
    section, in values.yaml's own top-level component order relative to
    the blocks already there (see lib.upgradedoc.component_order_key/
    insertion_index) — not always at the end. `ordering.canonical_names`,
    when set, lets a bare "global" shared-image section (e.g. "nginx-
    unprivileged") insert at its own real values.yaml position instead
    of always last — see component_order_key's own docstring. Appends
    right before the next "## " heading (or EOF) if the section doesn't
    exist yet, or has no blocks of its own yet to compare against — in
    that latter case, first stripping BOTH of upgrade.md's own stub
    placeholders (the top-level intro TODO and "## Changes"' own bare
    TODO — treated as ONE event, see UPGRADE_INTRO_STUB_TODO_LINE's own
    module-level comment) if either is literally all that's there, rather
    than leaving it stranded above the section actually being inserted
    (real bug, confirmed live on 4.9.1-to-4.9.2-upgrade.md: neither stub
    was ever cleared the moment the first real "### ..." block landed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    lines = text.splitlines(keepends=True)
    changes_idx, section_end = changes_section_bounds(lines)
    if changes_idx is None:
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text + section_text

    if not blocks:
        insert_at = _insert_index_for_empty_changes_section(lines, changes_idx, section_end)
    else:
        key_order = values_key_order(ordering.values)
        new_key = component_order_key(friendly, ordering.deps, key_order, ordering.canonical_names, ordering.values)
        existing_keys = [
            component_order_key(b["heading"], ordering.deps, key_order, ordering.canonical_names, ordering.values)
            for b in blocks
        ]
        idx = insertion_index(new_key, existing_keys)
        insert_at = blocks[idx]["start"] if idx < len(blocks) else section_end

    insert_at = _normalize_blank_line_before_insert(lines, insert_at)
    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def strip_stale_upgrade_placeholders(text: str):
    """Retroactive cleanup companion to insert_changes_section's own
    insertion-time fix: a doc whose FIRST real "### ..." block was
    inserted BEFORE that fix existed still has BOTH of upgrade.md's own
    stub placeholders stranded beside it — the top-level intro TODO
    (UPGRADE_INTRO_STUB_TODO_LINE) and "## Changes"' own bare TODO
    (UPGRADE_CHANGES_STUB_TODO_LINE), treated as ONE event (see that
    constant's own module-level comment) — real case, confirmed live:
    4.9.1-to-4.9.2-upgrade.md. Fixes both after the fact, run as part of
    fix-doc-consistency's own normal pass over every *-upgrade.md doc,
    not just newly-inserted ones.

    Also doubles as the CHECKER side (verify-podiumd's own check_docs_
    consistency): a caller that only wants to know WHETHER either
    placeholder is still stranded, without writing anything, just
    inspects the returned `changed` flag and discards new_text — the
    exact same "would stripping actually change anything" question,
    asked without applying the answer, so there's no separate find_
    stale_placeholder-style function to keep in sync with this one.

    Only fires when a real "### ..." block ALREADY exists — a "##
    Changes" section that still only has the bare TODO (a genuinely new
    doc with nothing recorded yet) is the correct, expected state and
    must never be touched, and neither is the intro TODO on its own with
    no accompanying real content. Returns (new_text, changed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    if not blocks:
        return text, False

    lines = text.splitlines(keepends=True)
    changed = False

    first_heading_idx = next((i for i, line in enumerate(lines) if re.match(r"^##\s+\S", line)), len(lines))
    if _strip_standalone_placeholder_line(lines, first_heading_idx, UPGRADE_INTRO_STUB_TODO_LINE):
        changed = True
        blocks = parse_upgrade_doc_changes_blocks("".join(lines))  # indices shifted -- recompute

    changes_idx, _ = changes_section_bounds(lines)
    if changes_idx is not None and blocks:
        first_block_start = blocks[0]["start"]
        new_end = _strip_bare_changes_todo(lines, changes_idx, first_block_start)
        if new_end != first_block_start:
            lines[changes_idx + 1 : changes_idx + 1] = ["\n"]
            changed = True

    if not changed:
        return text, False
    return "".join(lines), True


def remove_changes_block(text: str, block: HeadingBlock | None) -> tuple[str, bool]:
    """Delete `block` (one parse_upgrade_doc_changes_blocks entry) from
    text, with its trailing blank line(s) so removal doesn't leave a
    double gap. Returns (new_text, removed); (text, False) if block is
    None."""
    if block is None:
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


def remove_changes_section(text: str, friendly: str, ordering: OrderingContext) -> tuple[str, bool]:
    """Delete this component's "### ..." block from the "## Changes"
    section entirely — the counterpart to insert_changes_section for a
    bump that nets out to no change from upgrade_docs_baseline at all. Also swallows
    the block's own trailing blank line(s) so removal doesn't leave a
    double gap before whatever follows. The block is the one whose
    heading names exactly `friendly`'s identity, resolved the same way
    check_docs_consistency pairs headings with rows (resolve_component_
    identity / changes_heading_identities), so a sidecar's own
    "<key> - <basename>" block is never taken for its parent's.
    Returns (new_text, removed)."""
    deps, canonical_names = ordering.deps, ordering.canonical_names
    ident = resolve_component_identity(friendly, deps, canonical_names)
    blocks = parse_upgrade_doc_changes_blocks(text)
    block = next(
        (b for b in blocks if ident and changes_heading_identities(b["heading"], deps, canonical_names) == {ident}),
        None,
    )
    return remove_changes_block(text, block)


def resolve_component_own_version_change(
    key: str,
    target_state: ComponentState,
    baseline_state: BaselineState,
    chart_dir: Path | None,
    upgrade_docs_baseline: str | None = None,
):
    """(dep, chart_name, old_chart, new_chart, old_app, new_app, unchanged)
    for `key` (a member of lib.upgradedoc.compute_changed_components'
    own result) — `unchanged` is True when BOTH this component's own
    chart version and its own primary app version resolve as identical
    between `baseline_state` and `target_state`, meaning whatever else
    made `key` register as changed (almost always a
    brand-new/changed sidecar nested under it — that gets its own
    separate row via lib.image.docs.add_missing_sidecar_rows) has
    NOTHING to do with this component's own version; -upgrade.md's own
    "Component versions" table is about version changes specifically,
    so a redundant "(unchanged)"-only row for the OWNING component
    itself would just be noise on top of the sidecar's own row (real
    case: zac gaining a brand-new opentelemetry-collector-contrib
    sidecar, or openbao gaining three brand-new sidecars of its own,
    neither changing that component's OWN app/chart version at all).

    Returns None (nothing resolved) for a key matching neither a real
    Chart.yaml dependency nor a lib.chart.native_components entry —
    shouldn't happen for a key compute_changed_components itself ever
    returns, but never assumed. Shared by add_missing_component_rows
    (skip adding such a row) and lib.docs_consistency.check_docs_
    consistency's own "changed but has no row" finding (skip demanding
    one), so the two can never drift on which keys actually need a
    row of their own."""
    chart_versions = component_chart_versions(chart_dir, key, target_state.deps, baseline_state.deps)
    if chart_versions is None:
        return None
    dep, chart_name, old_chart, new_chart = chart_versions
    chart_unchanged = new_chart == "-" or (
        old_chart is not None and normalize_version(old_chart) == normalize_version(new_chart)
    )
    old_app = actual_app_version(baseline_state.values, key, chart_name) if baseline_state.values else None
    new_app = actual_app_version(target_state.values, key, chart_name, chart_dir=chart_dir, dep=dep)
    if old_app is None and baseline_state.values:
        # The git baseline genuinely has nothing for this path (real
        # case: brppersonenmock's Chart.yaml entry predates 4.9.0, but
        # its "image:" block was only added to podiumd's own values.yaml
        # this release) — before concluding "genuinely new", check
        # whether this repository already appears in any of this
        # chart's own PAST images-<version>.yaml manifests (real,
        # already-committed per-release documents, not the removed
        # images-baseline.yaml side-file) — if so, that release's own
        # recorded version is the true prior app version, even though
        # THIS component's own Chart.yaml/values.yaml presence is new.
        for path in image_paths_for(chart_name, chart_dir):
            old_app = historical_app_version_for_path(
                chart_dir, target_state.deps, target_state.values, (key, *tuple(path.split("."))), upgrade_docs_baseline
            )
            if old_app is not None:
                break
    if old_app is None and baseline_state.values and dep is not None and chart_unchanged:
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
        old_app = actual_app_version(baseline_state.values, key, chart_name, chart_dir=chart_dir, dep=dep)
    app_unchanged = (
        old_app is not None and new_app is not None and normalize_version(old_app) == normalize_version(new_app)
    )
    return dep, chart_name, old_chart, new_chart, old_app, new_app, (chart_unchanged and app_unchanged)


def _matched_component_keys(text: str, target_deps: list[ChartDependency], chart_dir: Path) -> set[str]:
    """Set of already-matched keys (a Chart.yaml dependency's own alias-
    or-name, or a lib.chart.native_components entry) found among
    `text`'s own current "Component versions" table rows —
    add_missing_component_rows' own "already has a row" check, split
    out purely to keep its own local-variable count down."""
    matched_keys: set[str] = set()
    for row in parse_upgrade_doc_rows(text):
        # match_dependency_excluding_sidecar_names, not match_dependency
        # directly — a canonical sidecar row like "redis-operator -
        # redis" must never register as if it were redis-operator's OWN
        # row, which would wrongly suppress adding redis-operator's real
        # row if IT independently changed with no row of its own yet.
        dep = match_dependency_excluding_sidecar_names(row["name"], target_deps)
        if dep:
            matched_keys.add(values_key_of(dep))
            continue
        native_key = match_native_component(row["name"], native_components(chart_dir))
        if native_key:
            matched_keys.add(native_key)
    return matched_keys


def _new_component_section(key: str, chart_name: str, change: VersionChange, doc_context: DocContext):
    """The "### ..." Changes section body for a newly-auto-added
    component row (see _add_missing_row_for_key): the normal make_
    changes_section render when its own app version resolved at all —
    `version_paths_for` wins outright when registered (see make_
    changes_section's own docstring for why image_paths_for's generic
    "<key>.image.tag" guess would be wrong for a component actually
    shaped like version_paths, e.g. eck-stack) — or a short TODO stub
    when it didn't (see add_missing_component_rows' own docstring for
    why: no dep["version"]-free way to know which values.yaml shape a
    truly unresolvable component actually uses, so this never guesses
    at prose)."""
    if change.new_app is not None:
        version_paths = version_paths_for(chart_name, doc_context.chart_dir)
        image_paths = [] if version_paths else image_paths_for(chart_name, doc_context.chart_dir)
        identity = ComponentIdentity(key, chart_name, key)
        return make_changes_section(identity, doc_context.target, change, image_paths, version_paths)
    chart_suffix = (
        f"{change.old_chart} → {change.new_chart}"
        if change.old_chart and normalize_version(change.old_chart) != normalize_version(change.new_chart)
        else change.new_chart
    )
    return (
        f"### {key} {chart_suffix}\n\n"
        f"TODO: describe this component's changes — its app version could not be "
        f"resolved automatically.\n\n"
    )


def _add_missing_row_for_key(
    text: str, key: str, target_state: ComponentState, baseline_state: BaselineState, doc_context: DocContext
):
    """Insert `key`'s own missing table row + Changes section into
    `text`, if resolve_component_own_version_change resolves it to a
    real, genuinely-changed component — (new_text, True) if a row was
    actually added, (text, False) otherwise (unresolvable, resolves as
    unchanged — see resolve_component_own_version_change's own
    docstring for why that's skipped, not just "(unchanged)" — or the
    doc has no table to insert into at all). Split out of add_missing_
    component_rows' own per-key loop purely to keep ITS own local-
    variable count down."""
    resolved = resolve_component_own_version_change(
        key, target_state, baseline_state, doc_context.chart_dir, doc_context.upgrade_docs_baseline
    )
    if resolved is None:
        return text, False
    _, chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    if unchanged:
        return text, False

    # new_app coerced to "-" only for the table cell (component_version_
    # cell's own convention for "no baseline, no real new value either");
    # _new_component_section below needs the RAW new_app (still None when
    # unresolved) to pick between a real section and the TODO stub -- see
    # its own docstring.
    text, table_action = update_component_table(
        text,
        key,
        VersionChange(old_app, new_app if new_app is not None else "-", old_chart, new_chart),
        OrderingContext(target_state.deps, target_state.values),
    )
    if table_action is None:
        return text, False  # doc has no "Component versions" table at all to insert into

    text, _ = remove_changes_section(text, key, OrderingContext(target_state.deps, target_state.values))
    change = VersionChange(old_app, new_app, old_chart, new_chart)
    text = insert_changes_section(
        text,
        _new_component_section(key, chart_name, change, doc_context),
        key,
        OrderingContext(target_state.deps, target_state.values),
    )
    return text, True


def add_missing_component_rows(
    text: str,
    doc_context: DocContext,
    target_state: ComponentState,
    baseline_state: BaselineState,
    actual_changed_keys: set[str],
) -> tuple[str, list[str]]:
    """Insert a new "Component versions" table row + matching "### ..."
    Changes section for every key in `actual_changed_keys` (see
    lib.upgradedoc.compute_changed_components) that doesn't already have
    a row — read straight from `text` itself via the same match_dependency
    lookup lib.docs_consistency.check_docs_consistency's own "component
    ... changed vs ... but has no row" finding uses, so this always
    targets exactly what that finding reports.

    Reuses update_component_table/make_changes_section (via _add_
    missing_row_for_key/_new_component_section) exactly as update-
    component-version's own single-component bump does, just driven by
    `target_state`'s CURRENT Chart.yaml/values.yaml state instead of a
    human-typed <app-version>/<chart-version> pair — an auto-added row is
    indistinguishable from one a real bump would have produced, right
    down to using the dependency's own literal name/alias as the row's
    Name (immune to a "Keycloak" vs "keycloak-operator" style naming
    drift a hand-picked display name can fall into, since match_dependency
    always matches its own exact source unambiguously).

    A key with no matching Chart.yaml dependency AND no lib.chart.
    native_components entry either is skipped — there's no dep["version"]
    to read a Helm chart version from, and nothing here can tell it apart
    from a genuinely unrelated top-level key; add that row by hand. A
    native_components key (e.g. frankgateway) instead gets old_chart=None,
    new_chart="-" — the same chart-less convention update-component-
    version's own "native" chart-version already writes — so its row's
    Helm-chart cell reads the bare "-" placeholder, never a guessed
    version. A key whose app version can't be resolved via actual_app_
    version's own known shapes (<key>.image.tag, frontend/backend,
    component_version_paths()' bare version fields, or a registered
    component_image_paths() component's vendored-chart appVersion fallback
    — see that function's own docstring) gets a "-" app-version
    placeholder and a short TODO-stub Changes section instead of
    guessing at prose. Returns (new_text, added_names)."""
    matched_keys = _matched_component_keys(text, target_state.deps, doc_context.chart_dir)
    added_names: list[str] = []
    for key in sorted(actual_changed_keys - matched_keys):
        text, added = _add_missing_row_for_key(text, key, target_state, baseline_state, doc_context)
        if added:
            added_names.append(key)
    return text, added_names
