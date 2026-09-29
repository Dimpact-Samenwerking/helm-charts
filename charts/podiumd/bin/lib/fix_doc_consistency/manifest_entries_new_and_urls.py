"""fix-doc-consistency's images-manifest fixes: url/name repair, adding
missing entries and removing stale ones."""

import re

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import baseline_lookup
from lib.chart.historical_baselines import baseline_tag_for_sidecar_path
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.nested_subchart_identity import documented_repository_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.repo_and_path_resolution import canonical_sidecar_row_names
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.chart.values_tree_primitives import version_of
from lib.component_docs.images_manifest_changes_header import ensure_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import find_changes_item
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_items
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_block
from lib.component_docs.images_manifest_changes_header import images_manifest_order_key
from lib.component_docs.images_manifest_changes_header import insert_images_manifest_header_item
from lib.component_docs.images_manifest_changes_header import remove_changes_item
from lib.image.repository_check import find_images_without_repository
from lib.images_manifest import ManifestEntry
from lib.images_manifest import try_parse_images_manifest
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffContext
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffInputs
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import delete_images_manifest_entry
from lib.upgradedoc.images_manifest_ordering import images_manifest_block_start
from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.yaml_types import YamlMapping


@dataclass
class UrlFixContext:
    """Resolution inputs for fix_images_manifest_entry_urls."""

    chart_dir: Path
    deps: list[ChartDependency]
    target_values: YamlMapping
    repo_map: dict[str, ImagePath] | None = None


@dataclass
class MissingEntriesContext:
    """Inputs for adding missing / removing stale manifest entries."""

    chart_dir: Path
    deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_values: YamlMapping | None
    allow_pull: bool = False
    upgrade_docs_baseline: str | None = None


@dataclass
class BaselineResolution:
    """Baseline image paths and their repository groups."""

    baseline_paths: dict[ImagePath, str]
    baseline_repo_groups: dict[str, list[ImagePath]]


@dataclass
class RepoResolution:
    """Target repository groups, representative map and reverse map."""

    repo_groups: dict[str, list[ImagePath]]
    repo_map: dict[str, ImagePath]
    path_to_repo: dict[ImagePath, str]


@dataclass
class MissingEntriesResolution:
    """Values computed once per run and shared by all passes; nested
    dataclasses keep it under pylint's max-instance-attributes."""

    current_paths: dict[ImagePath, str]
    baseline: BaselineResolution
    repo: RepoResolution
    unresolvable_paths: set[ImagePath]
    canonical_names: dict[str, ImagePath]
    key_order: list[str]
    sibling_fields: dict[ImagePath, DigestPinningException]


@dataclass
class AddedEntryFields:
    """Fields of a new entry, used for both its block and header item."""

    name: str
    repo: str
    full_repo_url: str | None
    pinned_tag: str


def _entry_url_line_index(lines: list[str], line_idx: int) -> int | None:
    """Index of the entry's "url:" line within its block (up to the next
    entry or blank line), or None."""
    block_end = len(lines)
    for j in range(line_idx + 1, len(lines)):
        if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
            block_end = j
            break
    for j in range(line_idx, block_end):
        if re.match(r"^\s*url:\s*\S", lines[j]):
            return j
    return None


def _entry_url_status(
    entry: ManifestEntry, line_idx: int, lines: list[str], current_paths: dict[ImagePath, str], context: UrlFixContext
) -> (
    tuple[Literal["unresolved"], str]
    | tuple[Literal["changed"], tuple[str, str, str]]
    | tuple[Literal["unchanged"], None]
):
    """("unresolved", name), ("changed", (name, old_url, new_url)) or
    ("unchanged", None) for one entry's "url:". Mutates `lines` when the
    url changes."""
    name = entry["name"]
    path = resolve_entry_image_path(entry["name"], current_paths.keys(), context.repo_map)
    full_repo = (
        full_repository_for_path(context.chart_dir, context.deps, context.target_values, path)
        if path is not None
        else None
    )
    if full_repo is None:
        return "unresolved", name

    url_idx = _entry_url_line_index(lines, line_idx)
    if url_idx is None:
        return "unresolved", name

    url_m = re.match(r"^\s*url:\s*(\S+)\s*$", lines[url_idx])
    if url_m is None:
        return "unresolved", name  # text after the url: no single value to compare
    current_url = url_m.group(1)
    if current_url == full_repo:
        return "unchanged", None
    lines[url_idx] = replace_scalar_value(lines[url_idx], full_repo)
    return "changed", (name, current_url, full_repo)


def fix_images_manifest_entry_urls(
    text: str,
    chart_dir: Path,
    deps: list[ChartDependency],
    target_values: YamlMapping,
    repo_map: dict[str, ImagePath] | None = None,
) -> tuple[str, list[tuple[str, str, str]], list[str]]:
    """Rewrite each entry's "url:" to the fully host-qualified repository of
    its values path (full_repository_for_path), as new entries get. Always
    offline: dependencies are vendored.

    Returns (new_text, changed_names, unresolved_names): changed_names is
    [(name, old_url, new_url), ...]; unresolved_names are entries whose
    path/repository can't be resolved or that lack a "url:" (reported, not
    touched)."""
    lines = text.splitlines(keepends=True)
    entries = try_parse_images_manifest(text)
    if entries is None:
        return text, [], []

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    current_paths = dict(find_all_image_and_version_paths(target_values, deps))
    current_paths.update(global_image_paths(target_values))

    changed_names: list[tuple[str, str, str]] = []
    unresolved_names: list[str] = []
    for entry, line_idx in zip(entries, entry_line_indices, strict=False):
        status = _entry_url_status(
            entry, line_idx, lines, current_paths, UrlFixContext(chart_dir, deps, target_values, repo_map)
        )
        if status[0] == "unresolved":
            unresolved_names.append(status[1])
        elif status[0] == "changed":
            changed_names.append(status[1])

    return "".join(lines), changed_names, unresolved_names


def fix_images_manifest_entry_names(text: str, repo_map: dict[str, ImagePath]) -> tuple[str, list[tuple[str, str]]]:
    """Rewrite each entry's "name:" to its url's group key (url minus
    registry host, e.g. "library/python"): the ACR mirror name the check
    expects. Skips entries without a url, whose new name is no known
    repository, or whose new name another entry has. Run after
    fix_images_manifest_entry_urls. Returns (new_text,
    [(old_name, new_name), ...])."""
    lines = text.splitlines(keepends=True)
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    names = {_unquoted(m.group(1)) for i in entry_line_indices if (m := _ENTRY_NAME_RE.match(lines[i]))}
    renamed: list[tuple[str, str]] = []
    for line_idx in entry_line_indices:
        name_m = _ENTRY_NAME_RE.match(lines[line_idx])
        url_idx = _entry_url_line_index(lines, line_idx)
        url_m = re.match(r"^\s*url:\s*(\S+)\s*$", lines[url_idx]) if url_idx is not None else None
        if name_m is None or url_m is None:
            continue
        old_name, new_name = _unquoted(name_m.group(1)), repository_group_key(_unquoted(url_m.group(1)))
        if old_name == new_name or new_name not in repo_map or new_name in names:
            continue
        lines[line_idx] = replace_scalar_value(lines[line_idx], new_name)
        names.add(new_name)
        renamed.append((old_name, new_name))
    return "".join(lines), renamed


_ENTRY_NAME_RE = re.compile(r"^-\s*name:\s*(\S+)\s*$")


def _unquoted(scalar: str) -> str:
    """`scalar` without the YAML quotes around it."""
    return scalar.strip("\"'")


def _images_manifest_changes_header_text(lines: list[str]):
    """Text of the "# Changes:" header block (with wrapped items), or ""
    if there is none."""
    header_idx, _has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return ""
    block_end = images_manifest_changes_block(lines, header_idx)[1]
    return "".join(lines[header_idx:block_end])


def _baseline_setup(context: MissingEntriesContext) -> tuple[dict[ImagePath, str], dict[str, list[ImagePath]]]:
    """(baseline_paths, baseline_repo_groups), grouped against
    baseline_values (where each repository lived in the baseline)."""
    baseline_paths = (
        dict(find_all_image_and_version_paths(context.baseline_values, context.deps)) if context.baseline_values else {}
    )
    baseline_paths.update(global_image_paths(context.baseline_values) if context.baseline_values else [])
    baseline_repo_groups = (
        paths_by_repository(context.chart_dir, context.deps, context.baseline_values, baseline_paths.keys())
        if context.baseline_values
        else {}
    )
    return baseline_paths, baseline_repo_groups


def _repo_setup(
    context: MissingEntriesContext, current_paths: dict[ImagePath, str]
) -> tuple[dict[str, list[ImagePath]], dict[str, ImagePath], dict[ImagePath, str]]:
    """(repo_groups, repo_map, path_to_repo) for target_values."""
    repo_groups = paths_by_repository(context.chart_dir, context.deps, context.target_values, current_paths.keys())
    repo_map = {repo: repo_group_representative(group_paths, context.deps) for repo, group_paths in repo_groups.items()}
    path_to_repo = {path: repo for repo, group_paths in repo_groups.items() for path in group_paths}
    return repo_groups, repo_map, path_to_repo


def _manifest_list_diff(
    text: str, context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[list[ImagePath], list[str], list[str]]:
    """find_images_manifest_list_diff's result for `text`: the same diff
    verify-podiumd reports."""
    entries = try_parse_images_manifest(text) or []
    return find_images_manifest_list_diff(
        ManifestDiffInputs(
            entries,
            resolution.current_paths,
            resolution.baseline.baseline_paths,
            resolution.repo.repo_map,
            resolution.repo.repo_groups,
            resolution.unresolvable_paths,
            context=ManifestDiffContext(
                chart_dir=context.chart_dir,
                deps=context.deps,
                upgrade_docs_baseline=context.upgrade_docs_baseline,
                values=context.target_values,
                baseline_values=context.baseline_values,
            ),
        )
    )


def _entries_resolution(context: MissingEntriesContext) -> MissingEntriesResolution:
    """Shared per-run resolution for adding and removing entries."""
    current_paths = dict(find_all_image_and_version_paths(context.target_values, context.deps))
    current_paths.update(global_image_paths(context.target_values))
    baseline_paths, baseline_repo_groups = _baseline_setup(context)
    repo_groups, repo_map, path_to_repo = _repo_setup(context, current_paths)
    unresolvable_paths = set(find_images_without_repository(context.chart_dir))
    canonical_names = canonical_sidecar_row_names(
        context.chart_dir, context.deps, context.target_values, current_paths.keys()
    )
    key_order = values_key_order(context.target_values)
    sibling_fields = digest_pinning_exceptions(context.chart_dir)

    return MissingEntriesResolution(
        current_paths,
        BaselineResolution(baseline_paths, baseline_repo_groups),
        RepoResolution(repo_groups, repo_map, path_to_repo),
        unresolvable_paths,
        canonical_names,
        key_order,
        sibling_fields,
    )


def _pinned_tag_for_path(
    path: tuple[str, ...],
    context: MissingEntriesContext,
    resolution: MissingEntriesResolution,
    current_tag: str,
    name: str,
) -> str | None:
    """Digest-pinned tag for `path`. With allow_pull and no local digest
    (e.g. eck-stack's bare "version:" fields), asks the registry; else
    None."""
    pinned_tag = resolved_digest_pin(context.target_values, path, current_tag, resolution.sibling_fields)
    if pinned_tag is not None or not context.allow_pull:
        return pinned_tag
    full_repo = documented_repository_for_path(context.chart_dir, context.deps, path)
    if not full_repo:
        return None
    host, repo_path = parse_repo(full_repo)
    print(f"  fetching digest for {full_repo}:{current_tag} from the registry...")
    try:
        # OSError covers urllib errors and non-JSON responses; a registry
        # hiccup must skip the entry, not abort a partial rewrite.
        exists, digest_hex = registry_tag_exists(host, repo_path, current_tag)
    except OSError as e:
        print(f"  registry lookup failed ({e}) — skipping {name}")
        exists, digest_hex = False, None
    if exists and digest_hex:
        return f"{current_tag}@{digest_hex}"
    return None


def _entry_fields_for_missing_path(
    path: tuple[str, ...], context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[str, AddedEntryFields | None]:
    """(name, fields) for `path`; fields is None when no repository or
    digest-pinned tag resolves (name is still returned for reporting)."""
    repo = resolution.repo.path_to_repo.get(path)
    # repo is host-stripped (right for "name:"); "url:" needs the real host.
    full_repo_url = (
        full_repository_for_path(
            context.chart_dir, context.deps, context.target_values, path, allow_pull=context.allow_pull
        )
        or repo
    )
    current_tag = resolution.current_paths[path]
    name = path_display_name(path, context.deps, resolution.canonical_names)
    pinned_tag = _pinned_tag_for_path(path, context, resolution, current_tag, name)
    if repo is None or pinned_tag is None:
        return name, None
    return name, AddedEntryFields(name, repo, full_repo_url, pinned_tag)


def _entry_old_version_and_digest_change(
    path: tuple[str, ...],
    new_version: str,
    pinned_tag: str,
    context: MissingEntriesContext,
    resolution: MissingEntriesResolution,
) -> tuple[str | None, bool]:
    """(old_version, digest_only_change) for a new entry's comment: from the
    baseline path (flagging a same-version re-pin so it doesn't render
    "<v> -> <v>"), else baseline_tag_for_sidecar_path, else past
    manifests."""
    baseline_tag = resolution.baseline.baseline_paths.get(path)
    if baseline_tag:
        old_version = version_of(baseline_tag)
        digest_only_change = False
        if normalize_version(old_version) == normalize_version(new_version):
            baseline_pinned_tag = resolved_digest_pin(
                context.baseline_values, path, baseline_tag, resolution.sibling_fields
            )
            if baseline_pinned_tag:
                digest_only_change = pinned_tag.split("@", 1)[1] != baseline_pinned_tag.split("@", 1)[1]
        return old_version, digest_only_change

    old_version = baseline_tag_for_sidecar_path(
        baseline_lookup(
            context.chart_dir, context.deps, context.target_values, context.baseline_values, resolution.baseline
        ),
        path,
    )
    if old_version is None:
        old_version = historical_app_version_for_path(
            context.chart_dir, context.deps, context.target_values, path, context.upgrade_docs_baseline
        )
    return old_version, False


def _manifest_lines_for_insert(text: str):
    """Lines with a trailing newline ensured and the stub's bare "[]" (see
    IMAGES_STUB_TEMPLATE) plus trailing blanks removed. Leaving "[]" before
    the first entry yields YAML later runs parse as empty, re-adding every
    entry. A manifest with "[]" has no real entries yet, so trimming is
    safe."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if any(line.strip() == "[]" for line in lines):
        lines = [line for line in lines if line.strip() != "[]"]
        while lines and not lines[-1].strip():
            lines.pop()
    return lines


def _entry_insertion_keys(
    lines: list[str], context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[list[int], list[tuple[int, ...]]]:
    """(entry_line_indices, entry_keys) of existing entries, for finding a
    new entry's insertion point."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    entry_keys: list[tuple[int, ...]] = []
    for idx in entry_line_indices:
        m = re.match(r"^-\s*name:\s*(\S+)\s*$", lines[idx])
        entry_path = (
            resolve_entry_image_path(m.group(1), resolution.current_paths.keys(), resolution.repo.repo_map)
            if m
            else None
        )
        if entry_path is None:
            entry_keys.append((len(resolution.key_order), 0))
            continue
        entry_display = path_display_name(entry_path, context.deps, resolution.canonical_names)
        entry_keys.append(
            images_manifest_order_key(
                resolution.key_order, entry_path, is_sidecar=" - " in entry_display, values=context.target_values
            )
        )
    return entry_line_indices, entry_keys


def _splice_added_entry_block(
    lines: list[str],
    context: MissingEntriesContext,
    resolution: MissingEntriesResolution,
    new_key: tuple[int, ...],
    block_lines: list[str],
):
    """Insert a new entry block in values.yaml component order, or append
    it when nothing sorts after it."""
    entry_line_indices, entry_keys = _entry_insertion_keys(lines, context, resolution)
    body_slot = insertion_index(new_key, entry_keys)
    if body_slot < len(entry_line_indices):
        insert_at = images_manifest_block_start(lines, entry_line_indices[body_slot])
        lines[insert_at:insert_at] = [*block_lines, "\n"]
    else:
        lines.append("\n")
        lines.extend(block_lines)


def _insert_added_entry(
    text: str,
    path: tuple[str, ...],
    context: MissingEntriesContext,
    resolution: MissingEntriesResolution,
    fields: AddedEntryFields,
):
    """Insert the new entry block, plus a header item unless the header
    already names it (e.g. a lockstep sibling). Returns the text."""
    new_version, digest = fields.pinned_tag.split("@", 1)
    old_version, digest_only_change = _entry_old_version_and_digest_change(
        path, new_version, fields.pinned_tag, context, resolution
    )
    new_key = images_manifest_order_key(
        resolution.key_order, path, is_sidecar=" - " in fields.name, values=context.target_values
    )
    version_text = image_manifest_version_text(old_version, new_version, digest_only_change=digest_only_change)
    version_text = f"{fields.name} {version_text}"

    lines = _manifest_lines_for_insert(text)
    ensure_images_manifest_changes_header(lines)
    header_text = _images_manifest_changes_header_text(lines)
    if not re.search(rf"\b{re.escape(fields.name)}\b", header_text, re.IGNORECASE):
        insert_images_manifest_header_item(lines, context.deps, resolution.key_order, new_key, f"{version_text}.")

    header_prefix = "# " if is_primary_image_path(path, context.deps, context.chart_dir) else "#   sidecar: "
    block_lines = [
        f"{header_prefix}{version_text}\n",
        f"- name: {fields.repo}\n",
        f"  url: {fields.full_repo_url}\n",
        f'  version: "{new_version}"\n',
        f'  digest: "{digest}"\n',
    ]
    _splice_added_entry_block(lines, context, resolution, new_key, block_lines)
    return "".join(lines)


def _backfilled_header_target(
    lines: list[str], header_text: str, context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[ImagePath, str, str, str] | None:
    """(entry_path, entry_name, entry_old, entry_new) of the first entry not
    named in `header_text`, or None. Entries whose display name is only the
    raw dotted path are skipped: not prose worth adding."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    for idx in entry_line_indices:
        m = re.match(r"^-\s*name:\s*(\S+)\s*$", lines[idx])
        entry_path = (
            resolve_entry_image_path(m.group(1), resolution.current_paths.keys(), resolution.repo.repo_map)
            if m
            else None
        )
        if entry_path is None:
            continue
        entry_name = path_display_name(entry_path, context.deps, resolution.canonical_names)
        if entry_name == ".".join(entry_path):
            continue
        if re.search(rf"\b{re.escape(entry_name)}\b", header_text, re.IGNORECASE):
            continue
        comment_text = "".join(lines[images_manifest_block_start(lines, idx) : idx])
        entry_new = extract_target_version(comment_text)
        if entry_new is None:
            continue
        entry_old = extract_source_version(comment_text) or entry_new
        return entry_path, entry_name, entry_old, entry_new
    return None


def _backfill_header_items(
    text: str, context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[str, list[str]]:
    """Add a header item for each entry that has a block but no item,
    reading old/new versions from its existing comment. Returns
    (text, backfilled_names)."""
    backfilled_names: list[str] = []
    while True:
        lines = text.splitlines(keepends=True)
        ensure_images_manifest_changes_header(lines)
        header_text = _images_manifest_changes_header_text(lines)
        if not header_text:
            break
        text = "".join(lines)

        target = _backfilled_header_target(lines, header_text, context, resolution)
        if target is None:
            break

        entry_path, entry_name, entry_old, entry_new = target
        new_key = images_manifest_order_key(
            resolution.key_order, entry_path, is_sidecar=" - " in entry_name, values=context.target_values
        )
        insert_images_manifest_header_item(
            lines, context.deps, resolution.key_order, new_key, f"{entry_name} {entry_old} -> {entry_new}."
        )
        text = "".join(lines)
        backfilled_names.append(entry_name)
    return text, backfilled_names


def add_missing_images_manifest_entries(
    text: str, context: MissingEntriesContext
) -> tuple[str, list[str], list[str], list[str]]:
    """Add an entry, its "# <name> <old> -> <new>" comment and a "# Changes:"
    header item for every missing path find_images_manifest_list_diff
    reports, then backfill header items (_backfill_header_items).

    Inserted in values.yaml component order; unresolvable existing items
    sort last without moving. "name:" is the stripped repository, not the
    curated ACR mirror slug (no mechanical formula; a human corrects it).
    version/digest come from the pinned tag in target_values;
    context.allow_pull lets an undigested tag be looked up in the registry.
    Paths without a digest or repository are reported as skipped, never
    written incomplete.

    One path at a time, re-parsing after each insert, so shifted line
    indices need no bookkeeping. Global image paths take part directly and
    represent their repository group, so a shared image gets one entry.

    Returns (new_text, added_names, skipped_names, backfilled_names)."""
    resolution = _entries_resolution(context)
    missing_paths, _stale_entry_names, _unmatched_entry_names = _manifest_list_diff(text, context, resolution)

    added_names: list[str] = []
    skipped_names: list[str] = []
    for path in missing_paths:
        name, fields = _entry_fields_for_missing_path(path, context, resolution)
        if fields is None:
            skipped_names.append(name)
            continue
        text = _insert_added_entry(text, path, context, resolution, fields)
        added_names.append(name)

    text, backfilled_names = _backfill_header_items(text, context, resolution)
    return text, added_names, skipped_names, backfilled_names


def _remove_stale_entry(
    lines: list[str], entry_name: str, context: MissingEntriesContext, resolution: MissingEntriesResolution
):
    """Delete the entry and its comment, and its "# Changes:" item unless
    another entry has the same display name (lockstep component)."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    entry_line = next(
        (i for i in entry_line_indices if re.match(rf"^-\s*name:\s*{re.escape(entry_name)}\s*$", lines[i])), None
    )
    if entry_line is None:
        return
    delete_images_manifest_entry(lines, entry_line)

    entry_path = resolve_entry_image_path(entry_name, resolution.current_paths.keys(), resolution.repo.repo_map)
    if entry_path is None:
        return
    display_name = path_display_name(entry_path, context.deps, resolution.canonical_names)
    remaining_display_names = {
        path_display_name(path, context.deps, resolution.canonical_names)
        for entry in try_parse_images_manifest("".join(lines)) or []
        if (path := resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo.repo_map))
    }
    if display_name in remaining_display_names:
        return
    _header_idx, _header_has_count, item_indices = find_images_manifest_changes_items(lines)
    match_idx = find_changes_item(lines, item_indices, display_name)
    if match_idx is not None:
        remove_changes_item(lines, item_indices, match_idx)


def remove_stale_images_manifest_entries(text: str, context: MissingEntriesContext) -> tuple[str, list[str]]:
    """Delete every entry find_images_manifest_list_diff reports as stale
    (version and digest equal upgrade_docs_baseline), with its comment and
    "# Changes:" item; a later pass renumbers the count word. Entries with
    an unresolvable repository are kept for a human. Returns
    (new_text, removed_names)."""
    resolution = _entries_resolution(context)
    _missing_paths, stale_entry_names, _unmatched_entry_names = _manifest_list_diff(text, context, resolution)
    removable_names = [
        name
        for name in stale_entry_names
        if resolve_entry_image_path(name, resolution.current_paths.keys(), resolution.repo.repo_map)
        not in resolution.unresolvable_paths
    ]
    lines = text.splitlines(keepends=True)
    for entry_name in removable_names:
        _remove_stale_entry(lines, entry_name, context, resolution)
    return "".join(lines), removable_names
