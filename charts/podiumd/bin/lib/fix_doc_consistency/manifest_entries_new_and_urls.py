"""fix-doc-consistency's own images-manifest url repair and missing-
entry backfill (the biggest single function in the whole script), split
out for pylint's too-many-lines check."""

import re

import yaml

from lib.chart.historical_baselines import baseline_tag_for_sidecar_path, historical_app_version_for_path
from lib.chart.nested_subchart_identity import documented_repository_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths, resolved_digest_pin
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.repo_and_path_resolution import (
    canonical_sidecar_row_names,
    full_repository_for_path,
    paths_by_repository,
    repo_group_representative,
)
from lib.chart.values_tree_primitives import replace_scalar_value, version_of
from lib.component_docs.images_manifest_changes_header import (
    ensure_images_manifest_changes_header,
    find_images_manifest_changes_header,
    images_manifest_order_key,
    insert_images_manifest_header_item,
)
from lib.image.repository_check import find_images_without_repository
from lib.registry import parse_repo, registry_tag_exists
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths, resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import images_manifest_block_start
from lib.upgradedoc.sorting_and_ordering import insertion_index, values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version, extract_target_version, normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text


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
        name = entry["name"]
        path = resolve_entry_image_path(entry, current_paths.keys(), repo_map)
        full_repo = full_repository_for_path(chart_dir, deps, target_values, path) if path is not None else None
        if full_repo is None:
            unresolved_names.append(name)
            continue

        block_end = len(lines)
        for j in range(line_idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
                block_end = j
                break
        url_idx = None
        for j in range(line_idx, block_end):
            if re.match(r"^\s*url:\s*\S", lines[j]):
                url_idx = j
                break
        if url_idx is None:
            unresolved_names.append(name)
            continue

        current_url = re.match(r"^\s*url:\s*(\S+)\s*$", lines[url_idx]).group(1)
        if current_url == full_repo:
            continue
        lines[url_idx] = replace_scalar_value(lines[url_idx], full_repo)
        changed_names.append((name, current_url, full_repo))

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


def add_missing_images_manifest_entries(
    text, chart_dir, deps, target_values, baseline_values, allow_pull=False, upgrade_docs_baseline=None
):
    """Insert a new entry (+ its own "# <name> — <old> -> <new>" comment,
    and a matching numbered item in the "# Changes:" header list) for
    every image lib.upgradedoc.find_images_manifest_list_diff's own
    missing_paths reports — the "changed vs ... but has no entry" gap
    verify-podiumd's own doc-consistency check reports.

    allow_pull (default False, matching every other allow_pull-taking
    function in this codebase — offline unless explicitly opted into)
    gates ONE specific fallback: a path whose repository resolves fine
    but whose current tag has no digest anywhere in values.yaml at all
    (real case: eck-stack's own bare "version:" CRD fields — elastic
    search/kibana/enterprise-search — never carry a digest locally,
    unlike an ordinary "image: {repository, tag}" block) tries a REAL
    registry manifest lookup (lib.registry.registry_tag_exists, the
    same call /fetch-image-digest and update-image-version's own
    missing_entries handling already make) for that exact version,
    using documented_repository_for_path's own UNSTRIPPED repository —
    before falling back to skipped_names. With allow_pull left False,
    behavior is unchanged: skipped exactly as before, network never
    touched.

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
    never causing an EXISTING item to move; it just means a new item
    might land after a cluster of unresolvable ones instead of exactly
    where it "should" go, which is still always at least as good as the
    previous always-append-at-the-end behavior.

    "name:" and "url:" are both set to the SAME resolved repository
    string (lib.chart.paths_by_repository's own stripped form) rather
    than the curated ACR mirror slug docs/images/acr-mirror-naming.md
    documents — that lookup has no reliable mechanical formula and stays
    a human's job to correct by hand; a mechanically-derivable, self-
    consistent placeholder here (it's also exactly the value repo_map's
    own exact-match lookup already expects, so a later fix-doc-
    consistency run resolves it cleanly) beats leaving the whole entry
    out entirely.

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
    repository here either (shouldn't normally happen — missing_paths
    already excludes lib.image.repository_check.find_images_without_
    repository's own result — kept as a defensive fallback, never a
    crash or bad data).

    A SECOND pass then backfills a header item for any entry that
    already has its own comment+entry block (e.g. one this same
    function added on an EARLIER run, before header-list support
    existed) but was never given one — checked by whether the entry's
    own display name appears anywhere in the header block's text at
    all (case-insensitive, whole-word/whole-phrase — "ZAC" covers "zac",
    but "ita" is never mistaken for a substring buried inside an
    unrelated word like "digital"), not by dependency resolution: a
    header item mentioning the same DEPENDENCY (e.g. "Keycloak app image
    26.6.4 -> 26.7.2 (keycloak-operator chart unchanged, ...)") does NOT
    mean a nested sidecar of that same dependency (e.g.
    "keycloak-operator - postgres") is covered too — only an item that
    actually names THAT exact entry counts. An entry whose own display
    name is path_display_name's raw-dotted-path fallback (no real
    dependency or canonical sidecar name resolves it at all — rare, see
    that function's own docstring) is skipped entirely, never even
    checked or reported: a dotted values.yaml path is not a phrase any
    human would write in prose, so it's both unsearchable here and not
    a name worth adding to a curated header list verbatim. Old/new
    version for a backfilled item are read from the entry's own
    existing comment (extract_source_version/extract_target_version),
    never recomputed — the SAME "generated from data already in the
    doc" principle as everywhere else in this function.

    Processes one path/entry at a time, re-parsing the (already
    updated) text before computing the next insertion point — simpler
    and safer than tracking how earlier insertions shift later line
    indices by hand.

    global_image_paths(target_values/baseline_values) is folded into
    current_paths/baseline_paths up front so "global.images.nginx" (and
    every other shared base-image anchor) participates in this same
    missing-entry scan as its own path, not just via whichever
    component happens to alias it. Combined with repo_group_
    representative's own "global" tier (always wins), a changed shared
    image gets EXACTLY ONE entry — named via the bare basename
    (path_display_name's own canonical_names lookup already handles
    this, see canonical_sidecar_row_names' "global" branch) and
    positioned under "global" 's own values.yaml order (first, since
    "global:" is the very first top-level key) — never one entry per
    aliasing component: every OTHER member of that repository group is
    already collapsed to this SAME representative path before missing_
    paths is even computed (find_images_manifest_list_diff), so it can
    never independently show up here as its own separate "missing"
    entry needing one of its own.

    Returns (new_text, added_names, skipped_names, backfilled_names)."""
    current_paths = dict(find_all_image_and_version_paths(target_values, deps))
    current_paths.update(global_image_paths(target_values))
    baseline_paths = dict(find_all_image_and_version_paths(baseline_values, deps)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
    # Grouped once, up front, against baseline_values (NOT target_values
    # — "where did this repository already live in the baseline tree")
    # and reused across every missing path below rather than recomputed
    # per path — the same up-front convention lib.image.docs.
    # add_missing_sidecar_rows already uses for its own baseline_repo_
    # groups, both now feeding the same lib.chart.baseline_tag_for_
    # sidecar_path.
    baseline_repo_groups = (
        paths_by_repository(chart_dir, deps, baseline_values, baseline_paths.keys()) if baseline_values else {}
    )
    try:
        entries = yaml.safe_load(text) or []
    except yaml.YAMLError:
        entries = []
    if not isinstance(entries, list):
        entries = []

    repo_groups = paths_by_repository(chart_dir, deps, target_values, current_paths.keys())
    repo_map = {repo: repo_group_representative(group_paths, deps) for repo, group_paths in repo_groups.items()}
    path_to_repo = {path: repo for repo, group_paths in repo_groups.items() for path in group_paths}
    unresolvable_paths = set(find_images_without_repository(chart_dir))
    canonical_names = canonical_sidecar_row_names(chart_dir, deps, target_values, current_paths.keys())
    key_order = values_key_order(target_values)
    sibling_fields = digest_pinning_exceptions(chart_dir)

    missing_paths, _stale_entry_names, _unmatched_entry_names = find_images_manifest_list_diff(
        entries,
        current_paths,
        baseline_paths,
        repo_map,
        repo_groups,
        unresolvable_paths,
        chart_dir=chart_dir,
        deps=deps,
        upgrade_docs_baseline=upgrade_docs_baseline,
        values=target_values,
        baseline_values=baseline_values,
    )

    def order_key(values_key, is_sidecar):
        return images_manifest_order_key(key_order, values_key, is_sidecar, target_values)

    added_names, skipped_names = [], []
    for path in missing_paths:
        repo = path_to_repo.get(path)
        # repo (path_to_repo, built from paths_by_repository) is the
        # STRIPPED form (strip_registry_host) — correct for the entry's
        # own "name:" field (that's exactly what the ACR-mirror-naming
        # convention wants there), but never for "url:", which needs the
        # REAL registry host — reconstructing one from the ALREADY-
        # stripped remainder would silently assume Docker Hub for any
        # image actually hosted elsewhere. full_repository_for_path
        # resolves the real, unstripped value directly instead (falls
        # back to `repo` only if it can't — never seen in practice, but
        # never worse than the old behavior either).
        full_repo_url = full_repository_for_path(chart_dir, deps, target_values, path, allow_pull=allow_pull) or repo
        current_tag = current_paths[path]
        name = path_display_name(path, deps, canonical_names)
        pinned_tag = resolved_digest_pin(target_values, path, current_tag, sibling_fields)
        if pinned_tag is None and allow_pull:
            full_repo = documented_repository_for_path(chart_dir, deps, path)
            if full_repo:
                host, repo_path = parse_repo(full_repo)
                print(f"  fetching digest for {full_repo}:{current_tag} from the registry...")
                try:
                    # OSError covers every urllib.error type (URLError/HTTPError
                    # are OSError subclasses), incl. lib.registry's non-JSON-
                    # response case — a registry hiccup must degrade to
                    # "skipped, pin it by hand", never abort a partial rewrite.
                    exists, digest_hex = registry_tag_exists(host, repo_path, current_tag)
                except OSError as e:
                    print(f"  registry lookup failed ({e}) — skipping {name}")
                    exists, digest_hex = False, None
                if exists and digest_hex:
                    pinned_tag = f"{current_tag}@{digest_hex}"
        if repo is None or pinned_tag is None:
            skipped_names.append(name)
            continue

        new_version, digest = pinned_tag.split("@", 1)
        baseline_tag = baseline_paths.get(path)
        digest_only_change = False
        if baseline_tag:
            old_version = version_of(baseline_tag)
            # A same-version/changed-digest re-pin (lib.upgradedoc.find_
            # images_manifest_list_diff's own digest-comparison branch)
            # would otherwise render as "<name> <version> -> <version>"
            # here — reads as "nothing changed" even though the digest
            # did. Real case: clamav 1.5.4, digest re-pinned with no
            # version bump.
            if normalize_version(old_version) == normalize_version(new_version):
                baseline_pinned_tag = resolved_digest_pin(baseline_values, path, baseline_tag, sibling_fields)
                if baseline_pinned_tag:
                    digest_only_change = pinned_tag.split("@", 1)[1] != baseline_pinned_tag.split("@", 1)[1]
        else:
            # No EXACT baseline value for this path at all — before
            # concluding "genuinely new" (never falling back to
            # `new_version` itself as a fake "old" value, which would
            # wrongly render "(digest changed)" for a brand-new image
            # instead of "(new)" — real bug, real doc: images-4.9.1.
            # yaml's own zac otel sidecar comment read "0.158.0 ->
            # 0.158.0"), check two fallback tiers, in order:
            # 1. lib.chart.baseline_tag_for_sidecar_path — does this same
            #    repository already live somewhere else in baseline_
            #    values, under a different values-tree path? Real case:
            #    podiumd 4.9.1 consolidated two separate postgres pins
            #    (keycloak-operator's own ensurePodiumdAdminUser job and
            #    openbao's own schemaJob) into one new shared
            #    global.images.postgres anchor — that exact path never
            #    existed in the baseline, but the same "postgres"
            #    repository already did, at openbao.database.schemaJob.
            #    image. The SAME function lib.image.docs.add_missing_
            #    sidecar_rows' own "Component versions" table row and
            #    lib.upgradedoc.resolve_component_row's own Changes
            #    heading already use, so this entry's own comment can
            #    never disagree with either of those again.
            # 2. Only once that also finds nothing: check this chart's
            #    own PAST images-<version>.yaml manifests, the same way
            #    resolve_component_row's own sidecar branch already does.
            old_version = baseline_tag_for_sidecar_path(
                chart_dir, deps, target_values, baseline_values, baseline_paths, baseline_repo_groups, path
            )
            if old_version is None:
                old_version = historical_app_version_for_path(
                    chart_dir, deps, target_values, path, upgrade_docs_baseline
                )
        new_key = order_key(path, " - " in name)
        version_text = f"{name} {image_manifest_version_text(old_version, new_version, digest_only_change)}"

        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        # A still-untouched IMAGES_STUB_TEMPLATE (or any manifest with no
        # entries yet) ends in a literal bare "[]" — yaml.safe_load's own
        # valid empty-list spelling. Leaving it in place while inserting
        # the first real entry below it would produce "[]" followed by a
        # "- name: ..." block, which is not valid YAML for a SECOND
        # document — yaml.safe_load raises on it, and the try/except
        # above that parses `entries` silently falls back to treating the
        # (now actually non-empty) file as having NO entries at all on
        # every subsequent run, re-adding everything already there.
        # Stripped here (only when actually present — never touches an
        # unrelated trailing blank line on every OTHER insert) instead of
        # at parse time so it's gone even before the very first insert. A
        # manifest that still has this stub can only be entirely empty of
        # real entries (the stub is never left behind once anything gets
        # added past this point), so trimming the file's own trailing
        # blank lines afterward is always safe here.
        if any(line.strip() == "[]" for line in lines):
            lines = [line for line in lines if line.strip() != "[]"]
            while lines and not lines[-1].strip():
                lines.pop()

        # A multi-image "lockstep" component (zgw-office-addin's frontend +
        # backend, eck-stack's elasticsearch + kibana, internetaakafhandeling's
        # web + poller — see settings.yaml's component_resolution.image_
        # paths/version_paths)
        # contributes SEVERAL missing_paths sharing the SAME path_display_name,
        # each getting its own comment+entry block below — but they're still
        # ONE logical change, so only the FIRST one gets a header item; the
        # same whole-word/whole-phrase check the second pass (backfilled_names)
        # already uses to skip an entry whose name is already mentioned.
        ensure_images_manifest_changes_header(lines)
        header_text = _images_manifest_changes_header_text(lines)
        if not re.search(rf"\b{re.escape(name)}\b", header_text, re.IGNORECASE):
            insert_images_manifest_header_item(lines, deps, key_order, new_key, f"{version_text}.")

        entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
        entry_keys = []
        for idx in entry_line_indices:
            m = re.match(r"^-\s*name:\s*(\S+)\s*$", lines[idx])
            entry_path = resolve_entry_image_path({"name": m.group(1)}, current_paths.keys(), repo_map) if m else None
            if entry_path is None:
                entry_keys.append((len(key_order), 0))
                continue
            entry_display = path_display_name(entry_path, deps, canonical_names)
            entry_keys.append(order_key(entry_path, " - " in entry_display))

        header_prefix = "# " if is_primary_image_path(path, deps, chart_dir) else "#   sidecar: "
        block_lines = [
            f"{header_prefix}{version_text}\n",
            f"- name: {repo}\n",
            f"  url: {full_repo_url}\n",
            f'  version: "{new_version}"\n',
            f'  digest: "{digest}"\n',
        ]
        body_slot = insertion_index(new_key, entry_keys)
        if body_slot < len(entry_line_indices):
            insert_at = images_manifest_block_start(lines, entry_line_indices[body_slot])
            lines[insert_at:insert_at] = block_lines + ["\n"]
        else:
            lines.append("\n")
            lines.extend(block_lines)

        text = "".join(lines)
        added_names.append(name)

    backfilled_names = []
    while True:
        lines = text.splitlines(keepends=True)
        ensure_images_manifest_changes_header(lines)
        header_text = _images_manifest_changes_header_text(lines)
        if not header_text:
            break
        text = "".join(lines)

        entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
        target = None
        for idx in entry_line_indices:
            m = re.match(r"^-\s*name:\s*(\S+)\s*$", lines[idx])
            entry_path = resolve_entry_image_path({"name": m.group(1)}, current_paths.keys(), repo_map) if m else None
            if entry_path is None:
                continue
            entry_name = path_display_name(entry_path, deps, canonical_names)
            if entry_name == ".".join(entry_path):
                # path_display_name's own raw-dotted-path fallback (no
                # real dependency/canonical-sidecar name resolves this
                # path at all — see that function's own docstring) —
                # never a phrase a human would write in prose, so it's
                # both unsearchable (see the word-boundary check below)
                # and not a name worth adding to a curated header list
                # verbatim. Left alone entirely, not even reported.
                continue
            if re.search(rf"\b{re.escape(entry_name)}\b", header_text, re.IGNORECASE):
                continue
            comment_text = "".join(lines[images_manifest_block_start(lines, idx) : idx])
            entry_new = extract_target_version(comment_text)
            if entry_new is None:
                continue
            entry_old = extract_source_version(comment_text) or entry_new
            target = (entry_path, entry_name, entry_old, entry_new)
            break

        if target is None:
            break

        entry_path, entry_name, entry_old, entry_new = target
        new_key = order_key(entry_path, " - " in entry_name)
        insert_images_manifest_header_item(lines, deps, key_order, new_key, f"{entry_name} {entry_old} -> {entry_new}.")
        text = "".join(lines)
        backfilled_names.append(entry_name)

    return text, added_names, skipped_names, backfilled_names
