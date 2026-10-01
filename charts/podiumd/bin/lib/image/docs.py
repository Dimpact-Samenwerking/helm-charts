"""Update upgrade docs for a shared image basename bump spanning several components.

Writes the "Component versions" row (chart column "-"), the "## Changes"
block listing every bumped pin, and the images-<target>.yaml entry, keyed
by basename/repository; values-deltas.md is left alone. A bump that
resolves to one component goes through lib.component_docs instead.
"""

import re

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import baseline_lookup
from lib.chart.historical_baselines import baseline_tag_for_sidecar_path
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import version_paths_for
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.values_tree_primitives import dep_for_values_key
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import version_of
from lib.checks.digest_pinning import find_unresolved_subchart_images
from lib.component_docs.changes_section import IMAGE_INTRO_KEPT
from lib.component_docs.changes_section import IMAGE_INTRO_NEW
from lib.component_docs.changes_section import IMAGE_INTRO_UPGRADE
from lib.component_docs.changes_section import IMAGE_PATH_BULLET
from lib.component_docs.changes_section import PINNED_AT
from lib.component_docs.changes_section import TODO_STUB
from lib.component_docs.changes_section import ComponentIdentity
from lib.component_docs.changes_section import ComponentState
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import VersionChange
from lib.component_docs.changes_section import changes_body_kinds
from lib.component_docs.changes_section import insert_changes_section
from lib.component_docs.changes_section import make_changes_section
from lib.component_docs.changes_section import render_changes_section
from lib.component_docs.changes_section import replace_changes_block
from lib.component_docs.changes_section import replace_changes_section
from lib.component_docs.changes_section import update_component_table
from lib.component_docs.images_manifest_changes_header import CHANGES_ITEM_RE
from lib.component_docs.images_manifest_changes_header import find_changes_item
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_block
from lib.component_docs.images_manifest_changes_header import insert_images_manifest_header_item
from lib.component_docs.images_manifest_changes_header import remove_changes_item
from lib.image.digests import cached_tag_exists
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.app_version_and_image_paths import chart_image_paths
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.consistency_checks import resolve_component_identity
from lib.upgradedoc.grouped_comments_and_changes_block import find_preceding_comment_line
from lib.upgradedoc.images_manifest_ordering import delete_images_manifest_entry
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import changes_blocks_with_lines
from lib.upgradedoc.sorting_and_ordering import component_order_key
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import path_order_key
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import ComponentRef
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.upgradedoc.version_cells_and_key_changes import pin_version_text
from lib.upgradedoc.version_cells_and_key_changes import replace_version_pair
from lib.upgradedoc.version_cells_and_key_changes import version_change_suffix
from lib.upgradedoc.version_cells_and_key_changes import version_transition
from lib.yaml_types import YamlMapping


def make_image_changes_section(
    basename: str, target: str, old_version: str | None, new_version: str | None, pinned: list[tuple[str, str | None]]
) -> str:
    """The "### <image-basename> <old> → <new>" Changes block for an image basename bump.

    "Shared" only when every bumped pin is under global.images. `pinned` is
    [(dotted_path, old_version), ...], listed per pin since their old
    versions may differ. A None old version renders "(new)"; one equal to
    `new_version` renders "(unchanged)".
    """
    image = (
        f"shared **{basename}**" if pinned and all(p.startswith("global.") for p, _ in pinned) else f"**{basename}**"
    )
    if old_version is None:
        intro_template = IMAGE_INTRO_NEW
    elif version_change_suffix(old_version, new_version):
        intro_template = IMAGE_INTRO_KEPT
    else:
        intro_template = IMAGE_INTRO_UPGRADE
    intro = [intro_template.format(target=target, image=image, new=new_version) + "\n", PINNED_AT + "\n"]
    bullets = [
        IMAGE_PATH_BULLET.format(path=path, pin=pin_version_text(path_old, new_version)) + "\n"
        for path, path_old in pinned
    ]
    return render_changes_section(f"{basename} {version_transition(old_version, new_version)}", intro, bullets, target)


@dataclass
class _SidecarScanState:
    """add_missing_sidecar_rows' values.yaml-derived tables, computed once rather than per path."""

    canonical_names: dict[str, ImagePath]
    current_paths: dict[ImagePath, str]
    baseline_paths: dict[ImagePath, str]
    baseline_repo_groups: dict[str, list[ImagePath]]
    matched_paths: set[ImagePath]


@dataclass
class _SidecarRowContext:
    """_SidecarScanState plus per-doc inputs, bundled to limit _add_sidecar_row's arguments."""

    state: _SidecarScanState
    target_state: ComponentState
    baseline_values: YamlMapping | None
    doc_context: DocContext


def _sidecar_scan_state(
    text: str, doc_context: DocContext, target_state: ComponentState, baseline_values: YamlMapping | None
) -> _SidecarScanState:
    """Build _SidecarScanState (split out to limit local variables)."""
    target = ChartImageIndex(doc_context.chart_dir, target_state.deps, target_state.values)
    # Against baseline_values: where the repository lived in the baseline tree.
    baseline = ChartImageIndex(doc_context.chart_dir, target_state.deps, baseline_values)
    matched_paths = {
        path
        for row in parse_upgrade_doc_rows(text)
        for path in [target.canonical_names.get(row["name"])]
        if path is not None
    }
    return _SidecarScanState(target.canonical_names, target.paths, baseline.paths, baseline.repo_groups, matched_paths)


def _resolve_sidecar_old_app(path: tuple[str, ...], ctx: _SidecarRowContext):
    """A sidecar path's prior app version when the exact path isn't in the baseline.

    Tries baseline_tag_for_sidecar_path (same repository elsewhere in the
    baseline, e.g. postgres pins merged into global.images.postgres), then
    past images-<version>.yaml manifests. Never images-baseline.yaml.
    """
    old_app = baseline_tag_for_sidecar_path(
        baseline_lookup(
            ctx.doc_context.chart_dir, ctx.target_state.deps, ctx.target_state.values, ctx.baseline_values, ctx.state
        ),
        path,
    )
    if old_app is None and ctx.baseline_values:
        old_app = historical_app_version_for_path(
            ctx.doc_context.chart_dir,
            ctx.target_state.deps,
            ctx.target_state.values,
            path,
            ctx.doc_context.upgrade_docs_baseline,
        )
    return old_app


def _add_sidecar_row(text: str, name: str, path: tuple[str, ...], ctx: _SidecarRowContext):
    """Insert `name`'s missing row and Changes section for `path`; (text, False) if not needed.

    Not needed when already present, unchanged in version (digest-only
    re-pins aren't documented), or the doc has no table.
    """
    if path in ctx.state.matched_paths:
        return text, False
    current_tag = ctx.state.current_paths.get(path)
    baseline_tag = ctx.state.baseline_paths.get(path)
    if current_tag is None or (baseline_tag is not None and version_of(current_tag) == version_of(baseline_tag)):
        return text, False
    new_app = current_tag.split("@", 1)[0]
    old_app = _resolve_sidecar_old_app(path, ctx)

    ordering = OrderingContext(ctx.target_state.deps, ctx.target_state.values, ctx.state.canonical_names)
    text, table_action = update_component_table(text, name, VersionChange(old_app, new_app, None, "-"), ordering)
    if table_action is None:
        return text, False  # no "Component versions" table

    dotted_path = ".".join(path) + ".tag"
    section = make_image_changes_section(name, ctx.doc_context.target, old_app, new_app, [(dotted_path, old_app)])
    text = replace_changes_section(text, section, name, ordering)
    return text, True


def add_missing_sidecar_rows(
    text: str, doc_context: DocContext, target_state: ComponentState, baseline_values: YamlMapping | None
) -> tuple[str, list[str]]:
    """Insert a row and "### ..." section for every canonical sidecar/shared-image name missing one.

    Only when the version (not just the digest) changed vs baseline. Uses
    the shared-image shape (chart column "-") for sidecars too, matching
    the docs and the checker. global.images anchors are included so an
    aliased image gets one bare "<image-basename>" row, not one per component.
    Paths new to the baseline resolve their old version via
    _resolve_sidecar_old_app.

    Returns (new_text, added_names).
    """
    state = _sidecar_scan_state(text, doc_context, target_state, baseline_values)
    ctx = _SidecarRowContext(state, target_state, baseline_values, doc_context)
    added_names: list[str] = []
    for name, path in sorted(state.canonical_names.items()):
        text, added = _add_sidecar_row(text, name, path, ctx)
        if added:
            added_names.append(name)
    return text, added_names


def build_changes_section_for_row(
    row: VersionRow, ident: ComponentRef, deps: list[ChartDependency], target: str
) -> str | None:
    """The "### ..." Changes section for a table row and its resolved identity.

    Built from the row's own cells so the two can't disagree; a row
    without a target app version gets a TODO stub. None if a "dep" identity
    has no dependency in `deps`.
    """
    if row["app"] in (None, "-"):
        chart_bit = row["chart"] or row["chart_source"] or "-"
        return f"### {row['name']} {chart_bit}\n\n{TODO_STUB}\n\n"
    if ident[0] == "dep":
        values_key = ident[1]
        dep = dep_for_values_key(deps, values_key)
        if dep is None:
            return None
        # Registered bare-version fields (eck-stack) have no image block, so the
        # generic "<key>.image.tag" default would name a nonexistent path.
        version_paths = version_paths_for(dep["name"])
        image_paths = [] if version_paths else image_paths_for(dep["name"])
        identity = ComponentIdentity(row["name"], dep["name"], values_key)
        # A "(new)" cell has no source version: the section then says "new" too.
        change = VersionChange(
            row["app_source"],
            row["app"],
            row["chart_source"] if row["chart"] else str(dep["version"]),
            row["chart"] or str(dep["version"]),
        )
        return make_changes_section(identity, target, change, image_paths, version_paths)
    dotted_path = ".".join(ident[1]) + ".tag"
    return make_image_changes_section(
        row["name"], target, row["app_source"], row["app"], [(dotted_path, row["app_source"])]
    )


def add_missing_changes_sections(
    text: str,
    deps: list[ChartDependency],
    target_values: YamlMapping,
    target: str,
    canonical_names: dict[str, ImagePath],
) -> tuple[str, list[str]]:
    """Insert a "### ..." section for every table row lacking one.

    Rows resolving to neither a dependency nor a canonical sidecar are
    skipped (reported elsewhere). Returns (new_text, added_names).
    """
    rows = parse_upgrade_doc_rows(text)
    headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(text)]
    rows_without_heading, _ = find_changes_row_correspondence_gaps(rows, headings, deps, canonical_names)
    if not rows_without_heading:
        return text, []
    missing = set(rows_without_heading)

    added_names: list[str] = []
    for row in rows:
        if row["name"] not in missing:
            continue
        ident = resolve_component_identity(row["name"], deps, canonical_names)
        if ident is None:
            continue
        section = build_changes_section_for_row(row, ident, deps, target)
        if section is None:
            continue
        text = insert_changes_section(text, section, row["name"], OrderingContext(deps, target_values, canonical_names))
        added_names.append(row["name"])

    return text, added_names


def _block_by_exact_heading(text: str, heading: str) -> HeadingBlock | None:
    """The Changes block with exactly this heading, avoiding fuzzy matches."""
    return next((b for b in parse_upgrade_doc_changes_blocks(text) if b["heading"] == heading), None)


@dataclass
class _StaleHeadingContext:
    """doc_context and ordering, shared by update_stale_app_version_headings' helpers."""

    doc_context: DocContext
    ordering: OrderingContext


def _rows_by_identity(text: str, ctx: _StaleHeadingContext) -> dict[ComponentRef, VersionRow]:
    """{identity: row} for every table row in `text` that resolves to an identity."""
    rows_by_identity: dict[ComponentRef, VersionRow] = {}
    for row in parse_upgrade_doc_rows(text):
        ident = resolve_component_identity(row["name"], ctx.ordering.deps, ctx.ordering.canonical_names)
        if ident is not None:
            rows_by_identity[ident] = row
    return rows_by_identity


def _stale_app_version_headings(text: str, ctx: _StaleHeadingContext) -> list[tuple[str, tuple[Literal["dep"], str]]]:
    """[(heading, ident), ...] for headings missing the app version that resolve to one "dep" identity."""
    stale: list[tuple[str, tuple[Literal["dep"], str]]] = []
    for heading in [b["heading"] for b in parse_upgrade_doc_changes_blocks(text)]:
        if changes_heading_has_app_version(heading):
            continue
        idents = changes_heading_identities(heading, ctx.ordering.deps, ctx.ordering.canonical_names)
        if len(idents) != 1:
            continue
        ident = next(iter(idents))
        if ident[0] != "dep":
            continue
        stale.append((heading, ident))
    return stale


def _rewrite_stale_heading(
    text: str,
    heading: str,
    ident: tuple[Literal["dep"], str],
    rows_by_identity: dict[ComponentRef, VersionRow],
    ctx: _StaleHeadingContext,
) -> tuple[str, bool]:
    """Rewrite `heading`'s block from its table row; (text, False) if anything is unresolvable."""
    _, values_key = ident
    dep = dep_for_values_key(ctx.ordering.deps, values_key)
    if dep is None:
        return text, False
    actual_app = actual_app_version(
        ctx.ordering.values, values_key, dep["name"], chart_dir=ctx.doc_context.chart_dir, dep=dep
    )
    if not actual_app:
        return text, False
    row = rows_by_identity.get(ident)
    if row is None:
        return text, False
    section = build_changes_section_for_row(row, ident, ctx.ordering.deps, ctx.doc_context.target)
    if section is None:
        return text, False

    block = _block_by_exact_heading(text, heading)
    if block is None:
        return text, False
    return replace_changes_block(text, block, section), True


def update_stale_app_version_headings(
    text: str, doc_context: DocContext, ordering: OrderingContext
) -> tuple[str, list[str]]:
    """Regenerate Changes sections whose heading lacks an app version that now resolves.

    E.g. an old chart-only stub "### openbao 0.28.4". Its generated parts are
    rewritten from the component's table row; text a user added stays. Only
    headings naming exactly one "dep" component are touched (sidecar
    headings are written with a known tag). Returns (new_text,
    updated_headings), the latter with the original heading texts.
    """
    ctx = _StaleHeadingContext(doc_context, ordering)
    rows_by_identity = _rows_by_identity(text, ctx)
    updated_headings: list[str] = []
    for heading, ident in _stale_app_version_headings(text, ctx):
        text, updated = _rewrite_stale_heading(text, heading, ident, rows_by_identity, ctx)
        if updated:
            updated_headings.append(heading)
    return text, updated_headings


_CHART_PART_RE = re.compile(r"\(chart [^)]*\)$")


def _owned_lines(body: str, kind: str) -> list[str]:
    """The lines of `body` that changes_body_kinds labels `kind`."""
    lines = body.splitlines(keepends=True)
    return [line for line, line_kind in zip(lines, changes_body_kinds(lines), strict=True) if line_kind == kind]


def _section_contradicts(heading: str, body: str, expected_heading: str, expected: str) -> bool:
    """Whether a generated part of the section differs from the section its row gives.

    Compared: the heading's "(chart ...)" part, the generated intro, and each
    expected pin bullet. Extra generated bullets (an aliased path's pin) are
    allowed; hand-written headings, intros and lines are never compared.
    """
    chart = _CHART_PART_RE.search(heading)
    expected_chart = _CHART_PART_RE.search(expected_heading)
    if chart and expected_chart and chart.group(0) != expected_chart.group(0):
        return True
    expected_body = expected.split("\n", 1)[1]
    intro = _owned_lines(body, "intro")
    if intro and intro != _owned_lines(expected_body, "intro"):
        return True
    bullets = _owned_lines(body, "bullet")
    return bool(bullets) and not set(_owned_lines(expected_body, "bullet")) <= set(bullets)


@dataclass(frozen=True)
class ContradictingSection:
    """A Changes section whose heading or intro disagrees with its table row."""

    heading: str
    expected_heading: str
    row_name: str
    expected_section: str
    repairable: bool


def changes_sections_contradicting_rows(
    text: str, doc_context: DocContext, ordering: OrderingContext
) -> list[ContradictingSection]:
    """Dependency Changes sections whose heading or "introduces"/"upgrades" intro contradicts the table row.

    E.g. row "0.28.4 → 0.29.6" with heading "(chart 0.29.6, new)" and
    "introduces". Compared with the section build_changes_section_for_row
    writes for that row; rows without an app version are skipped.
    """
    ctx = _StaleHeadingContext(doc_context, ordering)
    rows_by_identity = _rows_by_identity(text, ctx)
    lines, blocks = changes_blocks_with_lines(text)
    found: list[ContradictingSection] = []
    for block in blocks:
        idents = changes_heading_identities(block["heading"], ordering.deps, ordering.canonical_names)
        ident = next(iter(idents)) if len(idents) == 1 else None
        row = rows_by_identity.get(ident) if ident is not None and ident[0] == "dep" else None
        if row is None or ident is None or row["app"] in (None, "-"):
            continue
        expected = build_changes_section_for_row(row, ident, ordering.deps, doc_context.target)
        if expected is None:
            continue
        expected_heading = expected.splitlines()[0].removeprefix("### ")
        body = "".join(lines[block["start"] + 1 : block["end"]])
        if not _section_contradicts(block["heading"], body, expected_heading, expected):
            continue
        found.append(
            ContradictingSection(
                block["heading"], expected_heading, row["name"], expected, _repair_resolves(text, block, expected)
            )
        )
    return found


def _repair_resolves(text: str, block: HeadingBlock, expected: str) -> bool:
    """Whether rewriting the block's owned parts removes the contradiction (it may sit in user text)."""
    rewritten = replace_changes_block(text, block, expected)
    new_block = next(b for b in parse_upgrade_doc_changes_blocks(rewritten) if b["start"] == block["start"])
    lines = rewritten.splitlines(keepends=True)
    body = "".join(lines[new_block["start"] + 1 : new_block["end"]])
    return not _section_contradicts(new_block["heading"], body, expected.splitlines()[0].removeprefix("### "), expected)


def rebuild_changes_sections_contradicting_rows(
    text: str, doc_context: DocContext, ordering: OrderingContext
) -> tuple[str, list[ContradictingSection]]:
    """Rewrite the owned parts of each contradicting section from its row; user text stays.

    Returns (text, rebuilt); a contradiction inside user text is left for
    doc-consistency to report.
    """
    rebuilt: list[ContradictingSection] = []
    for section in changes_sections_contradicting_rows(text, doc_context, ordering):
        block = _block_by_exact_heading(text, section.heading)
        if section.repairable and block is not None:
            text = replace_changes_block(text, block, section.expected_section)
            rebuilt.append(section)
    return text, rebuilt


def resolve_basename_baseline_version(
    baseline_values: YamlMapping | None, full_paths: list[tuple[str, str | None]]
) -> str | None:
    """The baseline version shared by all of a basename's touched pins, or None if they differ or are absent.

    A uniform baseline lets a bump repeated within a release document
    baseline -> latest instead of each intermediate hop. `full_paths` is
    [(dotted "...tag" path, old_version), ...].
    """
    versions: set[str] = set()
    for dotted_path, _old_version in full_paths:
        tag = text_at(baseline_values, dotted_path)
        if not isinstance(tag, str) or not tag:
            return None
        versions.add(tag.split("@", 1)[0])
    return next(iter(versions)) if len(versions) == 1 else None


@dataclass
class ImageBump:
    """A shared image basename's version-bump facts, for locating its images-manifest entry."""

    basename: str
    repository: str
    old_version: str | None
    new_version: str
    digest: str


def _find_manifest_entry(lines: list[str], repository: str):
    """(entry_line, block_end) of the first entry whose host-stripped "url:" is `repository`, or (None, None)."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    url_re = re.compile(r"^\s*url:\s*(\S+)\s*$")
    for idx in entry_line_indices:
        block_end = len(lines)
        for j in range(idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
                block_end = j
                break
        for j in range(idx, block_end):
            m = url_re.match(lines[j])
            if m and m.group(1).rstrip("/").endswith(repository):
                return idx, block_end
    return None, None


def _update_manifest_entry_scalars(
    lines: list[str], entry_line: int | None, block_end: int | None, new_version: str, digest: str
):
    """Set the entry's "version:"/"digest:" in place; False (no-op) when entry_line is None."""
    if entry_line is None or block_end is None:
        return False
    entry_updated = False
    for i in range(entry_line, block_end):
        m = re.match(r"^\s*(version|digest):", lines[i])
        if not m:
            continue
        new_value = new_version if m.group(1) == "version" else digest
        lines[i] = replace_scalar_value(lines[i], new_value)
        entry_updated = True
    return entry_updated


def _update_manifest_changes_header(lines: list[str], bump: ImageBump, ordering: OrderingContext):
    """Insert or update the basename's "#   N. ..." changes-header item.

    Returns None without a header, else "updated" or "added"; new items go
    in values.yaml order when `ordering.values` is given, else at the end.
    """
    # Not CHANGES_HEADER_RE alone: it doesn't match the plain "# Changes:" header.
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None

    item_indices, block_end = images_manifest_changes_block(lines, header_idx)
    match_idx = find_changes_item(lines, item_indices, bump.basename)
    item_text = f"{bump.basename} {image_manifest_version_text(bump.old_version, bump.new_version)}."

    if match_idx is not None:
        m = match_located_line(CHANGES_ITEM_RE, lines[match_idx])
        lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
        return "updated"
    if ordering.values is not None:
        # Keeps a bare "# Changes:" header uncounted.
        key_order = values_key_order(ordering.values)
        new_key = component_order_key(
            bump.basename, ordering.deps, key_order, ordering.canonical_names, ordering.values
        )
        insert_images_manifest_header_item(lines, ordering.deps, key_order, new_key, item_text)
        return "added"
    # No ordering context: append.
    new_num = len(item_indices) + 1
    insert_at = block_end if item_indices else header_idx + 1
    lines.insert(insert_at, f"#   {new_num}. {item_text}\n")
    return "added"


def update_image_manifest(images_path: Path, bump: ImageBump, ordering: OrderingContext | None = None):
    """Update the changes-header item and images-manifest entry for a shared image basename bump.

    The entry is matched by host-stripped "url:" against `bump.repository`.
    Returns (changes_action, entry_updated); a missing entry is not created
    here but by the closing fix-doc-consistency run. `ordering` places a
    new header item in values.yaml order, like lib.component_docs does, so
    items from both writers stay ordered; without it, the item is appended.
    """
    ordering = ordering or OrderingContext([], None)
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    changes_action = _update_manifest_changes_header(lines, bump, ordering)

    entry_line, block_end2 = _find_manifest_entry(lines, bump.repository)
    entry_updated = _update_manifest_entry_scalars(lines, entry_line, block_end2, bump.new_version, bump.digest)
    if entry_line is not None:
        comment_idx = find_preceding_comment_line(lines, entry_line)
        if comment_idx is not None:
            current_source = extract_source_version(lines[comment_idx])
            if current_source:
                lines[comment_idx] = replace_version_pair(lines[comment_idx], current_source, bump.new_version)

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updated


def _remove_manifest_changes_header_item(lines: list[str], basename: str):
    """Delete the basename's changes-header item and renumber; "removed", or None if nothing matched."""
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None
    item_indices, _block_end = images_manifest_changes_block(lines, header_idx)
    match_idx = find_changes_item(lines, item_indices, basename)
    if match_idx is None:
        return None

    remove_changes_item(lines, item_indices, match_idx)
    return "removed"


def remove_image_manifest_entry(images_path: Path, basename: str, repository: str):
    """Counterpart to update_image_manifest for a shared-image bump that
    nets out to no change from baseline at all: removes the "changes:"
    list item and the matching entry with its own comment, since the
    manifest only lists images that changed. A same-version re-pin with
    a new digest is added back as "(digest changed)" by the
    fix-doc-consistency run that follows. Returns (changes_action,
    entry_removed)."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    changes_action = _remove_manifest_changes_header_item(lines, basename)

    entry_line, _block_end = _find_manifest_entry(lines, repository)
    if entry_line is not None:
        delete_images_manifest_entry(lines, entry_line)

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_line is not None


IMAGES_BASELINE_HEADER = (
    "# Baseline images — the single, complete strip-registry mirror manifest.\n"
    "#\n"
    "# This is a full, CURRENT snapshot of every image PodiumD pulls right now —\n"
    "# every component's own primary image, every sidecar, every MULTIPLE/global-\n"
    "# anchored shared image — under the strip-registry mirror convention:\n"
    "#   name = strip_registry(url): upstream url with the registry host removed,\n"
    "#   full <namespace>/<repo> path kept.\n"
    "# Versions are the tags currently pinned in charts/podiumd/values.yaml (or the\n"
    '# owning subchart). Digests are the tag\'s own embedded "@sha256:..." suffix\n'
    "# when it has one, else resolved live against the source registry\n"
    "# (Docker-Content-Digest / manifest_digest).\n"
    "#\n"
    "# Fully regenerated by fix-doc-consistency, update-component-version and\n"
    "# update-image-version on every run (lib.image.docs.\n"
    "# regenerate_images_baseline_manifest) — always a complete, wholesale\n"
    "# snapshot, never incremental patching: no hand-maintained gap-fillers, no\n"
    '# "NOT INCLUDED" exclusion notes, no stale dual-version entries. Editing this\n'
    "# file by hand is pointless — the next run overwrites it entirely.\n"
)


@dataclass
class _BaselineManifestContext:
    """regenerate_images_baseline_manifest's per-run inputs, computed once."""

    chart_dir: Path
    deps: list[ChartDependency]
    values: YamlMapping
    key_order: list[str]
    sibling_fields: dict[ImagePath, DigestPinningException]


def _current_image_paths(
    chart_dir: Path, deps: list[ChartDependency], values: YamlMapping, rendered_paths: set[str]
) -> dict[ImagePath, str]:
    """Every pinned image path, plus live unpinned subchart-default images (find_unresolved_subchart_images)."""
    current_paths = chart_image_paths(values, deps)
    for scope_key, subpath, tag, _already_pinned in find_unresolved_subchart_images(
        chart_dir, deps, values, rendered_paths
    ):
        current_paths.setdefault((scope_key, *subpath.split(".")), tag)
    return current_paths


# (sort_key, repo, full_repo, new_version, digest) -- see _resolve_baseline_entry.
BaselineEntry = tuple[tuple[int, ...], str, str, str, str | None]


def _resolve_baseline_entry(
    ctx: _BaselineManifestContext, current_paths: dict[ImagePath, str], repo: str, group_paths: list[ImagePath]
) -> BaselineEntry | None:
    """One repository group's baseline entry, or None if its full repository or digest is unresolvable."""
    representative = repo_group_representative(group_paths, ctx.deps)
    tag = current_paths[representative]
    full_repo = full_repository_for_path(ctx.chart_dir, ctx.deps, ctx.values, representative)
    if full_repo is None:
        return None

    pinned = resolved_digest_pin(ctx.values, representative, tag, ctx.sibling_fields)
    if pinned is not None:
        new_version, digest = pinned.split("@", 1)
    else:
        new_version = tag.split("@", 1)[0]
        exists, digest = cached_tag_exists(ctx.chart_dir, full_repo, new_version)
        if not exists or not digest:
            return None

    sort_key = path_order_key(representative, ctx.deps, ctx.key_order, ctx.values)
    return sort_key, repo, full_repo, new_version, digest


def _resolve_baseline_entries(
    ctx: _BaselineManifestContext, current_paths: dict[ImagePath, str], repo_groups: dict[str, list[ImagePath]]
) -> tuple[list[BaselineEntry], list[str]]:
    """(resolved entries sorted by sort_key, skipped repos) for every group in repo_groups."""
    resolved: list[BaselineEntry] = []
    skipped: list[str] = []
    for repo, group_paths in repo_groups.items():
        entry = _resolve_baseline_entry(ctx, current_paths, repo, group_paths)
        if entry is None:
            skipped.append(repo)
        else:
            resolved.append(entry)
    resolved.sort(key=lambda e: e[0])
    return resolved, skipped


def _render_baseline_manifest_lines(resolved: list[BaselineEntry]):
    """The images-baseline.yaml text: header, then one block per entry, ending in a single newline."""
    lines = [IMAGES_BASELINE_HEADER, "\n"]
    for _sort_key, repo, full_repo, new_version, digest in resolved:
        lines.append(f"- name: {repo}\n")
        lines.append(f"  url: {full_repo}\n")
        lines.append(f'  version: "{new_version}"\n')
        lines.append(f'  digest: "{digest}"\n')
        lines.append("\n")
    text = "".join(lines)
    # Every entry ends with a blank line; collapse the final one.
    if text.endswith("\n\n"):
        text = text[:-1]
    return text


def regenerate_images_baseline_manifest(
    chart_dir: Path,
    deps: list[ChartDependency],
    values: YamlMapping,
    images_baseline_path: Path,
    rendered_paths: set[str],
):
    """Rewrite docs/images/images-baseline.yaml as a full snapshot of every image the chart deploys.

    Includes every chart_image_paths path plus live images defined only in a
    vendored subchart's defaults (a null tag resolving to its appVersion),
    gated by `rendered_paths` so condition/tag-disabled charts are left out.
    One entry per repository, in path_order_key order like
    images-<target>.yaml; never incremental.

    `name` is the stripped repository, `url` the host-qualified one;
    the digest comes from the pin or, failing that, a registry lookup.
    Repository resolution stays offline (allow_pull=False).

    Returns (written, skipped, changed): entry count, repos whose url or
    digest couldn't be resolved, and whether the content differs (the file
    is written only then).
    """
    current_paths = _current_image_paths(chart_dir, deps, values, rendered_paths)
    repo_groups = paths_by_repository(chart_dir, deps, values, current_paths.keys())
    ctx = _BaselineManifestContext(
        chart_dir, deps, values, values_key_order(values), digest_pinning_exceptions(chart_dir)
    )

    resolved, skipped = _resolve_baseline_entries(ctx, current_paths, repo_groups)
    text = _render_baseline_manifest_lines(resolved)
    current_text = images_baseline_path.read_text(encoding="utf-8") if images_baseline_path.is_file() else None
    changed = text != current_text
    if changed:
        images_baseline_path.write_text(text, encoding="utf-8")
    return len(resolved), skipped, changed
