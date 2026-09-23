"""fix-doc-consistency's own images-manifest url repair and missing-
entry backfill (the biggest single function in the whole script), split
out for pylint's too-many-lines check."""

import re

from dataclasses import dataclass

import yaml

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
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.chart.values_tree_primitives import version_of
from lib.component_docs.images_manifest_changes_header import ensure_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import images_manifest_order_key
from lib.component_docs.images_manifest_changes_header import insert_images_manifest_header_item
from lib.image.repository_check import find_images_without_repository
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffContext
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffInputs
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import images_manifest_block_start
from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text


@dataclass
class UrlFixContext:
    """chart_dir/deps/target_values/repo_map — fix_images_manifest_entry_
    urls' own resolution inputs, bundled since both it and its own per-
    entry helper need all four together."""

    chart_dir: object
    deps: list
    target_values: dict
    repo_map: dict = None


@dataclass
class MissingEntriesContext:
    """chart_dir/deps/target_values/baseline_values/allow_pull/
    upgrade_docs_baseline — add_missing_images_manifest_entries' own six
    raw inputs (everything but the manifest text itself), bundled since
    virtually every helper below needs some subset of the same six
    together."""

    chart_dir: object
    deps: list
    target_values: dict
    baseline_values: dict
    allow_pull: bool = False
    upgrade_docs_baseline: str = None


@dataclass
class BaselineResolution:
    """baseline_paths/baseline_repo_groups — grouped together since
    _baseline_setup computes both from baseline_values in one pass."""

    baseline_paths: dict
    baseline_repo_groups: dict


@dataclass
class RepoResolution:
    """repo_groups/repo_map/path_to_repo — grouped together since
    _repo_setup computes all three from target_values in one pass."""

    repo_groups: dict
    repo_map: dict
    path_to_repo: dict


@dataclass
class MissingEntriesResolution:
    """current_paths/baseline/repo/unresolvable_paths/canonical_names/
    key_order/sibling_fields — every value add_missing_images_manifest_
    entries' own setup phase computes ONCE, up front (see _missing_
    entries_setup), reused unchanged by both passes below (new-entry
    insertion, header backfill). `baseline`/`repo` nest BaselineResolution/
    RepoResolution rather than each field living here directly, purely to
    stay under pylint's max-instance-attributes."""

    current_paths: dict
    baseline: BaselineResolution
    repo: RepoResolution
    unresolvable_paths: set
    canonical_names: dict
    key_order: list
    sibling_fields: object


@dataclass
class AddedEntryFields:
    """name/repo/full_repo_url/pinned_tag — resolved once per missing
    path (see _entry_fields_for_missing_path), then threaded into both
    the comment+entry block and the header item text."""

    name: str
    repo: str
    full_repo_url: str
    pinned_tag: str


def _entry_url_line_index(lines, line_idx):
    """The line index of this entry's own "url:" field, within its own
    block (up to the next entry or blank line) — None if it has none."""
    block_end = len(lines)
    for j in range(line_idx + 1, len(lines)):
        if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
            block_end = j
            break
    for j in range(line_idx, block_end):
        if re.match(r"^\s*url:\s*\S", lines[j]):
            return j
    return None


def _entry_url_status(entry, line_idx, lines, current_paths, context):
    """("unresolved", name) / ("changed", (name, old_url, new_url)) /
    ("unchanged", None) for a single images-manifest entry's own "url:"
    field, resolved against `context` (chart_dir/deps/target_values/
    repo_map, see UrlFixContext). Mutates `lines` in place when the url
    actually changes."""
    name = entry["name"]
    path = resolve_entry_image_path(entry, current_paths.keys(), context.repo_map)
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

    current_url = re.match(r"^\s*url:\s*(\S+)\s*$", lines[url_idx]).group(1)
    if current_url == full_repo:
        return "unchanged", None
    lines[url_idx] = replace_scalar_value(lines[url_idx], full_repo)
    return "changed", (name, current_url, full_repo)


def fix_images_manifest_entry_urls(text, chart_dir, deps, target_values, repo_map=None):
    """Rewrite each images-manifest entry's own "url:" field to the REAL,
    fully host-qualified repository for its matched values-tree path
    (lib.chart.full_repository_for_path — the same convention add_
    missing_images_manifest_entries's own url-qualification already
    uses when writing a BRAND NEW entry), when it doesn't already match.

    Real bug this closes: a historical (now-superseded) reordering
    commit silently stripped the registry host off several "url:"
    fields while moving their own entry blocks — confirmed live:
    images-4.9.1.yaml's own zac otel sidecar ("otel/opentelemetry-
    collector-contrib" instead of "docker.io/otel/opentelemetry-
    collector-contrib") and three of openbao's own sidecars (vault-k8s/
    openbao-csi-provider/openbao-snapshot-agent) similarly — never
    caught since, since nothing ever re-verified an EXISTING entry's own
    url against what it should actually be, only ever a freshly-added
    entry's own url at write time.

    allow_pull is deliberately not exposed here — always offline
    (full_repository_for_path's own default), same reasoning as
    regenerate_images_baseline_manifest's own: a real chart always has
    every dependency already vendored, so this never needs a fresh
    `helm pull`.

    Returns (new_text, changed_names, unresolved_names) — changed_names
    is [(name, old_url, new_url), ...] for every entry actually
    rewritten; unresolved_names is every entry whose own values-tree
    path (or full_repository_for_path result) couldn't be resolved at
    all, or that has no "url:" field to check — never guessed at, same
    "report it, don't touch it" discipline every other fixer here uses."""
    lines = text.splitlines(keepends=True)
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError:
        return text, [], []
    if not isinstance(entries, list):
        return text, [], []

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    current_paths = dict(find_all_image_and_version_paths(target_values, deps))
    current_paths.update(global_image_paths(target_values))

    changed_names, unresolved_names = [], []
    for entry, line_idx in zip(entries, entry_line_indices, strict=False):
        status, payload = _entry_url_status(
            entry, line_idx, lines, current_paths, UrlFixContext(chart_dir, deps, target_values, repo_map)
        )
        if status == "unresolved":
            unresolved_names.append(payload)
        elif status == "changed":
            changed_names.append(payload)

    return "".join(lines), changed_names, unresolved_names


def _images_manifest_changes_header_text(lines):
    """The full "# Changes:" header block's own text — header line
    through its last numbered item (and any wrapped continuation
    lines) — or "" if the file has no header at all. Used to check
    whether some entry's own display name is already mentioned
    somewhere in there, before deciding it needs a header item of its
    own backfilled."""
    header_idx, _has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return ""
    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1
    return "".join(lines[header_idx:block_end])


def _baseline_setup(context):
    """(baseline_paths, baseline_repo_groups) — baseline_repo_groups
    grouped against baseline_values (NOT target_values — "where did
    this repository already live in the baseline tree"), reused across
    every missing path below rather than recomputed per path, same
    up-front convention lib.image.docs.add_missing_sidecar_rows already
    uses for its own baseline_repo_groups, both now feeding the same
    lib.chart.baseline_tag_for_sidecar_path."""
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


def _repo_setup(context, current_paths):
    """(repo_groups, repo_map, path_to_repo) for `context`'s own
    target_values."""
    repo_groups = paths_by_repository(context.chart_dir, context.deps, context.target_values, current_paths.keys())
    repo_map = {repo: repo_group_representative(group_paths, context.deps) for repo, group_paths in repo_groups.items()}
    path_to_repo = {path: repo for repo, group_paths in repo_groups.items() for path in group_paths}
    return repo_groups, repo_map, path_to_repo


def _missing_paths_for_entries(text, context, resolution):
    """The list of paths find_images_manifest_list_diff reports as
    changed vs baseline but with no images-manifest entry yet — `text`
    is only ever parsed here, never needed again afterward."""
    try:
        entries = yaml.safe_load(text) or []
    except yaml.YAMLError:
        entries = []
    if not isinstance(entries, list):
        entries = []
    missing_paths, _stale_entry_names, _unmatched_entry_names = find_images_manifest_list_diff(
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
    return missing_paths


def _missing_entries_setup(text, context):
    """(resolution, missing_paths) — add_missing_images_manifest_
    entries' own one-time setup phase: current_paths/baseline_paths/
    repo groups/canonical names/key order/digest-pinning exceptions
    (bundled as a MissingEntriesResolution) and the actual list of
    paths that changed vs baseline but have no entry yet."""
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

    resolution = MissingEntriesResolution(
        current_paths,
        BaselineResolution(baseline_paths, baseline_repo_groups),
        RepoResolution(repo_groups, repo_map, path_to_repo),
        unresolvable_paths,
        canonical_names,
        key_order,
        sibling_fields,
    )
    missing_paths = _missing_paths_for_entries(text, context, resolution)
    return resolution, missing_paths


def _pinned_tag_for_path(path, context, resolution, current_tag, name):
    """The resolved digest-pinned tag for `path` (see resolved_digest_
    pin) — when allow_pull is set and no digest is pinned locally at
    all, tries a real registry lookup instead of giving up immediately
    (see add_missing_images_manifest_entries' own docstring: eck-stack's
    own bare "version:" CRD fields never carry a digest locally, unlike
    an ordinary "image: {repository, tag}" block). With allow_pull left
    False, behavior is unchanged: skipped exactly as before, network
    never touched."""
    pinned_tag = resolved_digest_pin(context.target_values, path, current_tag, resolution.sibling_fields)
    if pinned_tag is not None or not context.allow_pull:
        return pinned_tag
    full_repo = documented_repository_for_path(context.chart_dir, context.deps, path)
    if not full_repo:
        return None
    host, repo_path = parse_repo(full_repo)
    print(f"  fetching digest for {full_repo}:{current_tag} from the registry...")
    try:
        # OSError covers every urllib.error type (URLError/HTTPError are
        # OSError subclasses), incl. lib.registry's non-JSON-response
        # case — a registry hiccup must degrade to "skipped, pin it by
        # hand", never abort a partial rewrite.
        exists, digest_hex = registry_tag_exists(host, repo_path, current_tag)
    except OSError as e:
        print(f"  registry lookup failed ({e}) — skipping {name}")
        exists, digest_hex = False, None
    if exists and digest_hex:
        return f"{current_tag}@{digest_hex}"
    return None


def _entry_fields_for_missing_path(path, context, resolution):
    """(name, AddedEntryFields | None) for `path` — fields is None when
    it can't be resolved to a real repository or a digest-pinned tag at
    all (the caller reports `name` as skipped in that case; `name` is
    still resolved even then, purely for that report)."""
    repo = resolution.repo.path_to_repo.get(path)
    # repo (path_to_repo, built from paths_by_repository) is the
    # STRIPPED form (strip_registry_host) — correct for the entry's own
    # "name:" field, but never for "url:", which needs the REAL registry
    # host — full_repository_for_path resolves the real, unstripped
    # value directly instead (falls back to `repo` only if it can't).
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


def _entry_old_version_and_digest_change(path, new_version, pinned_tag, context, resolution):
    """(old_version, digest_only_change) for a newly-added entry's own
    comment — old_version from the exact baseline path when one exists
    (flagging a same-version/changed-digest re-pin via digest_only_
    change, so it doesn't misleadingly render as "<v> -> <v>"), else via
    baseline_tag_for_sidecar_path/historical_app_version_for_path's own
    two fallback tiers (see add_missing_images_manifest_entries' own
    docstring)."""
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


def _manifest_lines_for_insert(text):
    """splitlines(keepends=True), with a trailing newline ensured and any
    leftover bare "[]" empty-list stub (see IMAGES_STUB_TEMPLATE) and its
    own trailing blank lines stripped. A still-untouched stub manifest
    ends in this literal "[]" — yaml.safe_load's own valid empty-list
    spelling; leaving it in place while inserting the first real entry
    below it would produce invalid YAML for a second document, which
    then makes every SUBSEQUENT run's own parse silently treat the (now
    actually non-empty) file as having no entries at all, re-adding
    everything already there. Stripped here, before the very first
    insert — a manifest that still has this stub can only be entirely
    empty of real entries, so trimming its own trailing blank lines
    afterward is always safe."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if any(line.strip() == "[]" for line in lines):
        lines = [line for line in lines if line.strip() != "[]"]
        while lines and not lines[-1].strip():
            lines.pop()
    return lines


def _entry_insertion_keys(lines, context, resolution):
    """(entry_line_indices, entry_keys) — every existing entry's own
    line index and sort key (see images_manifest_order_key), used to
    find where a new entry belongs (see insertion_index)."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    entry_keys = []
    for idx in entry_line_indices:
        m = re.match(r"^-\s*name:\s*(\S+)\s*$", lines[idx])
        entry_path = (
            resolve_entry_image_path({"name": m.group(1)}, resolution.current_paths.keys(), resolution.repo.repo_map)
            if m
            else None
        )
        if entry_path is None:
            entry_keys.append((len(resolution.key_order), 0))
            continue
        entry_display = path_display_name(entry_path, context.deps, resolution.canonical_names)
        entry_keys.append(
            images_manifest_order_key(resolution.key_order, entry_path, " - " in entry_display, context.target_values)
        )
    return entry_line_indices, entry_keys


def _splice_added_entry_block(lines, context, resolution, new_key, block_lines):
    """Insert `block_lines` (a new entry's own comment+entry block) at
    the position matching values.yaml's own component order relative to
    what's already in `lines` (see insertion_index/images_manifest_
    block_start), or append it at the end when nothing sorts after it."""
    entry_line_indices, entry_keys = _entry_insertion_keys(lines, context, resolution)
    body_slot = insertion_index(new_key, entry_keys)
    if body_slot < len(entry_line_indices):
        insert_at = images_manifest_block_start(lines, entry_line_indices[body_slot])
        lines[insert_at:insert_at] = [*block_lines, "\n"]
    else:
        lines.append("\n")
        lines.extend(block_lines)


def _insert_added_entry(text, path, context, resolution, fields):
    """Insert `fields`'s own comment+entry block (and header item, when
    not already covered by an earlier lockstep sibling's own item — see
    add_missing_images_manifest_entries' own docstring) at the position
    matching values.yaml's own component order. Returns the updated
    text."""
    new_version, digest = fields.pinned_tag.split("@", 1)
    old_version, digest_only_change = _entry_old_version_and_digest_change(
        path, new_version, fields.pinned_tag, context, resolution
    )
    new_key = images_manifest_order_key(resolution.key_order, path, " - " in fields.name, context.target_values)
    version_text = f"{fields.name} {image_manifest_version_text(old_version, new_version, digest_only_change)}"

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


def _backfilled_header_target(lines, header_text, context, resolution):
    """The (entry_path, entry_name, entry_old, entry_new) for the FIRST
    entry (in manifest order) whose own display name isn't already
    mentioned anywhere in `header_text` — None if every entry is already
    covered, or has no matching real dependency/canonical-sidecar name
    to check at all (path_display_name's own raw-dotted-path fallback —
    never a phrase a human would write in prose, so it's both
    unsearchable and not worth adding to a curated header list
    verbatim)."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    for idx in entry_line_indices:
        m = re.match(r"^-\s*name:\s*(\S+)\s*$", lines[idx])
        entry_path = (
            resolve_entry_image_path({"name": m.group(1)}, resolution.current_paths.keys(), resolution.repo.repo_map)
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


def _backfill_header_items(text, context, resolution):
    """Second pass: insert a header item for any entry that already has
    its own comment+entry block (e.g. added by an earlier run, before
    header-list support existed) but was never given one. Old/new
    version for a backfilled item are read from the entry's own existing
    comment, never recomputed. Returns (text, backfilled_names)."""
    backfilled_names = []
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
            resolution.key_order, entry_path, " - " in entry_name, context.target_values
        )
        insert_images_manifest_header_item(
            lines, context.deps, resolution.key_order, new_key, f"{entry_name} {entry_old} -> {entry_new}."
        )
        text = "".join(lines)
        backfilled_names.append(entry_name)
    return text, backfilled_names


def add_missing_images_manifest_entries(text, context):
    """Insert a new entry (+ its own "# <name> — <old> -> <new>" comment,
    and a matching numbered item in the "# Changes:" header list) for
    every image lib.upgradedoc.find_images_manifest_list_diff's own
    missing_paths reports — the "changed vs ... but has no entry" gap
    verify-podiumd's own doc-consistency check reports. `context` is a
    MissingEntriesContext.

    context.allow_pull (default False, matching every other allow_pull-
    taking function in this codebase — offline unless explicitly opted
    into) gates ONE specific fallback: a path whose repository resolves
    fine but whose current tag has no digest anywhere in values.yaml at
    all tries a REAL registry manifest lookup (see _pinned_tag_for_path)
    before falling back to skipped_names.

    Both the header item and the comment+entry block are inserted at the
    position matching values.yaml's own top-level component order
    relative to what's already there (see lib.upgradedoc.
    component_order_key/insertion_index — the SAME ordering convention
    upgrade.md's own table rows/Changes sections use), not always
    appended at the end. An existing header item (free-form prose,
    matched via match_dependency_excluding_sidecar_names the same way
    check_images_manifest_format's own Changes-item check does) or entry
    (via its own resolved values-tree path) that can't be resolved to a
    real dependency sorts last for THIS purpose only — never guessed at,
    never causing an EXISTING item to move.

    "name:" and "url:" are both set to the SAME resolved repository
    string (lib.chart.paths_by_repository's own stripped form) rather
    than the curated ACR mirror slug docs/images/acr-mirror-naming.md
    documents — that lookup has no reliable mechanical formula and stays
    a human's job to correct by hand; a mechanically-derivable, self-
    consistent placeholder here beats leaving the whole entry out
    entirely.

    version/digest come directly from target_values' own already-pinned
    tag — no registry call needed here, unlike update-image-version's
    OWN missing_entries handling (lib.component_docs.
    update_images_manifest), which fetches a real digest as part of ITS
    job of writing a brand new pin in the first place; this function
    only ever documents a pin that already exists.

    A path whose current tag has no "@sha256:..." digest at all (rare —
    almost every image is digest-pinned after the chart-wide digest-
    pinning sweep, #437) can't produce a valid entry (digest is a
    required field — see check_images_manifest_format's own entry-key
    validation) and is reported separately rather than silently skipped
    or written incomplete; same treatment for a path find_images_
    manifest_list_diff reports as missing but that has no resolvable
    repository here either (shouldn't normally happen — kept as a
    defensive fallback, never a crash or bad data).

    A SECOND pass then backfills a header item for any entry that
    already has its own comment+entry block but was never given one
    (see _backfill_header_items).

    Processes one path/entry at a time, re-parsing the (already
    updated) text before computing the next insertion point — simpler
    and safer than tracking how earlier insertions shift later line
    indices by hand.

    global_image_paths(target_values/baseline_values) is folded into
    current_paths/baseline_paths up front (see _missing_entries_setup)
    so "global.images.nginx" (and every other shared base-image anchor)
    participates in this same missing-entry scan as its own path, not
    just via whichever component happens to alias it. Combined with
    repo_group_representative's own "global" tier (always wins), a
    changed shared image gets EXACTLY ONE entry — never one per aliasing
    component: every OTHER member of that repository group is already
    collapsed to this SAME representative path before missing_paths is
    even computed, so it can never independently show up here as its
    own separate "missing" entry needing one of its own.

    Returns (new_text, added_names, skipped_names, backfilled_names)."""
    resolution, missing_paths = _missing_entries_setup(text, context)

    added_names, skipped_names = [], []
    for path in missing_paths:
        name, fields = _entry_fields_for_missing_path(path, context, resolution)
        if fields is None:
            skipped_names.append(name)
            continue
        text = _insert_added_entry(text, path, context, resolution, fields)
        added_names.append(name)

    text, backfilled_names = _backfill_header_items(text, context, resolution)
    return text, added_names, skipped_names, backfilled_names
