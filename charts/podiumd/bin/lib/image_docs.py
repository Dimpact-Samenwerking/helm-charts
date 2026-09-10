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

from lib.chart import (
    canonical_sidecar_row_names, full_repository_for_path, get_path, global_image_paths,
    historical_app_version_for_path, image_paths_for, paths_by_repository, replace_scalar_value,
    repo_group_representative, resolved_digest_pin, version_of, version_paths_for,
)
from lib.component_docs import (
    CHANGES_ITEM_RE, dep_for_values_key, find_images_manifest_changes_header, insert_changes_section,
    insert_images_manifest_header_item, make_changes_section, remove_changes_section, update_component_table,
)
from lib.digest_pinning_check import find_unresolved_subchart_images
from lib.registry import parse_repo, registry_tag_exists
from lib.upgradedoc import (
    actual_app_version, changes_heading_has_app_version, changes_heading_identities, component_order_key,
    extract_source_version, find_all_image_and_version_paths, find_changes_row_correspondence_gaps,
    find_image_tag_paths, find_preceding_comment_line, image_manifest_version_text,
    images_manifest_entry_order_key, normalize_name, normalize_version, parse_upgrade_doc_changes_blocks,
    parse_upgrade_doc_rows, replace_version_pair, resolve_component_identity, values_key_order,
    version_change_suffix,
)


def make_image_changes_section(basename, target, old_version, new_version, pinned):
    """The "### <basename> <old> → <new>" Changes block for a shared
    image basename bump. `pinned` is [(dotted_path, old_version), ...]
    for every values.yaml tag pin actually bumped (see
    lib.image_version.update_image_version's own return value) — listed
    individually rather than assuming one uniform "old" version, since a
    basename's various pins aren't guaranteed to have all started at the
    exact same one.

    `old_version` (and, independently, each pin's own `path_old_version`)
    is None when that specific pin never had a prior value to diff
    against at all (genuinely new — real case: a brand-new shared
    "redis" cache sidecar aliased into a dozen components at once) —
    renders "(new)" there instead of a nonsensical "None → <new>".
    `old_version`/`path_old_version` already equal to `new_version`
    (already resolved as "unchanged" by the caller — e.g. the images-
    baseline.yaml fallback matching a digest-only re-pin, or a
    genuinely new path pinned to an already-known image) renders
    "(unchanged)" instead of an equally nonsensical "<version> →
    <version>" self-transition — same reasoning throughout: this doc is
    about version changes, and there isn't one to report in either
    case."""
    suffix = version_change_suffix(old_version, new_version)
    if old_version is None:
        heading_suffix = f"{new_version} {suffix}"
        intro = f"PodiumD {target} introduces the shared **{basename}** image at {new_version},\n"
    elif suffix:
        heading_suffix = f"{new_version} {suffix}"
        intro = f"PodiumD {target} keeps the shared **{basename}** image at {new_version},\n"
    else:
        heading_suffix = f"{old_version} → {new_version}"
        intro = f"PodiumD {target} upgrades the shared **{basename}** image to {new_version},\n"
    lines = [f"### {basename} {heading_suffix}\n\n", intro, "pinned at:\n\n"]
    for path, path_old_version in pinned:
        path_suffix = version_change_suffix(path_old_version, new_version)
        if path_suffix:
            lines.append(f"- `{path}` `{new_version}` {path_suffix}\n")
        else:
            lines.append(f"- `{path}` `{path_old_version}` → `{new_version}`\n")
    lines.append(f"\n- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def add_missing_sidecar_rows(text, chart_dir, deps, target_values, baseline_values, target,
                              upgrade_docs_baseline=None):
    """Insert a new "Component versions" table row + matching "### ..."
    Changes section for every canonical sidecar/shared-image name (see
    lib.chart.canonical_sidecar_row_names — "<values_key> - <basename>"
    for a sidecar nested under a real dependency, bare "<basename>" for
    a shared "global" image) whose VERSION (lib.chart.version_of — the
    tag with any "@sha256:..." digest suffix stripped) changed vs
    baseline but doesn't already have a row of its own. A digest-only
    re-pin with the same version is deliberately NOT enough on its own
    to add a row/section here — -upgrade.md documents version changes,
    never a digest re-pin alone (that's the images-manifest's own
    concern; see find_images_manifest_list_diff's docstring for the
    same reasoning). The sidecar/shared-image counterpart
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
    `actual_chart = None` for the sidecar branch). global_image_paths is
    folded into current_paths/baseline_paths so a shared global.images.*
    anchor (e.g. nginx-unprivileged, aliased by 10+ components' own
    sidecars at once) resolves to canonical_sidecar_row_names' own bare-
    basename "global" row — ONE row for the whole chart — rather than
    each aliasing component's own dependency independently qualifying
    for its OWN "<dep> - <basename>" row for the exact same image bump
    (real case: "zac - nginx-unprivileged" and "frankgateway - nginx-
    unprivileged" both showing up as separate rows for what is, via the
    shared anchor, the identical version change). Returns (new_text,
    added_names)."""
    current_paths = dict(find_image_tag_paths(target_values))
    current_paths.update(global_image_paths(target_values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
    canonical_names = canonical_sidecar_row_names(chart_dir, deps, target_values, current_paths.keys())

    matched_paths = {path for row in parse_upgrade_doc_rows(text)
                      for path in [canonical_names.get(row["name"])] if path is not None}

    added_names = []
    for name, path in sorted(canonical_names.items()):
        if path in matched_paths:
            continue
        current_tag = current_paths.get(path)
        baseline_tag = baseline_paths.get(path)
        if current_tag is None or (baseline_tag is not None and version_of(current_tag) == version_of(baseline_tag)):
            continue
        new_app = current_tag.split("@", 1)[0]
        # `path` not in baseline_paths at all (real case: redis-operator's
        # own "k8s" sidecar, added in 4.9.0) means baseline_tag is None —
        # the git baseline genuinely has nothing to compare against.
        # Before concluding "genuinely new", check whether this
        # repository already appears in any of this chart's own PAST
        # images-<version>.yaml manifests (real, already-committed
        # per-release documents) — if so, that release's own recorded
        # version is the true prior app version, even though this exact
        # sidecar path is new. Never a fallback to the removed images-
        # baseline.yaml side-file (ACR-mirror digest provenance, a
        # genuinely different, unrelated question).
        old_app = baseline_tag.split("@", 1)[0] if baseline_tag else None
        if old_app is None and baseline_values:
            old_app = historical_app_version_for_path(chart_dir, deps, target_values, path, upgrade_docs_baseline)

        text, table_action = update_component_table(text, name, old_app, new_app, None, "-", deps, target_values,
                                                     canonical_names)
        if table_action is None:
            continue  # doc has no "Component versions" table at all to insert into

        text, _ = remove_changes_section(text, name)
        dotted_path = ".".join(path) + ".tag"
        section = make_image_changes_section(name, target, old_app, new_app, [(dotted_path, old_app)])
        text = insert_changes_section(text, section, name, deps, target_values, canonical_names)
        added_names.append(name)

    return text, added_names


def build_changes_section_for_row(row, ident, deps, target):
    """The "### ..." Changes section for a single table row + its already-
    resolved identity (see resolve_component_identity) — make_changes_
    section for a real Chart.yaml dependency, make_image_changes_section
    for a canonical sidecar/shared-image. Always built from the row's OWN
    app/chart cells verbatim, never recomputed from actual_app_version or
    a git baseline — the generated section can never disagree with what
    the row right above it already visibly says. A row whose own app
    cell has no resolvable target version at all (e.g. "-") gets a short
    TODO-stub section instead of guessing at prose, the same fallback
    add_missing_component_rows uses for the same reason. None if `ident`
    names a "dep" identity whose Chart.yaml dependency can't be found
    (shouldn't happen — ident was itself resolved against `deps`)."""
    kind, value = ident
    if row["app"] is None:
        chart_bit = row["chart"] or row["chart_source"] or "-"
        return (f"### {row['name']} {chart_bit}\n\n"
                f"TODO: describe this component's changes — its app version could not be "
                f"resolved from the table row.\n\n")
    if kind == "dep":
        dep = dep_for_values_key(deps, value)
        if dep is None:
            return None
        # version_paths_for wins outright when registered — a component
        # listed there (e.g. eck-stack's bare "...version:" fields, the
        # ECK operator's own CRD convention) has no "{repository, tag}"
        # block at all, so falling back to image_paths_for's generic
        # DEFAULT_IMAGE_PATHS guess (the ordinary "<key>.image.tag"
        # shape) would point the bullet at a path that doesn't exist.
        version_paths = version_paths_for(dep["name"])
        image_paths = [] if version_paths else image_paths_for(dep["name"])
        return make_changes_section(
            row["name"], target, dep["name"], value,
            row["app_source"] or row["app"], row["app"],
            row["chart_source"] or row["chart"] or str(dep["version"]), row["chart"] or str(dep["version"]),
            image_paths, version_paths
        )
    dotted_path = ".".join(value) + ".tag"
    return make_image_changes_section(
        row["name"], target, row["app_source"] or row["app"], row["app"],
        [(dotted_path, row["app_source"] or row["app"])]
    )


def add_missing_changes_sections(text, deps, target_values, target, canonical_names):
    """Insert a "### ..." Changes section (see build_changes_section_for_
    row) for every "Component versions" table row that already exists
    but has no matching section of its own yet (see lib.upgradedoc.
    find_changes_row_correspondence_gaps's own rows_without_heading, the
    same gap lib.docs_consistency.check_docs_consistency's "table row
    ... has no matching "### ..." section" finding reports). A row
    resolving to neither a real dependency nor a canonical sidecar is
    skipped (already reported elsewhere as wrong/stale — see find_
    wrong_or_duplicate_dependency_claims). Returns (new_text,
    added_names)."""
    rows = parse_upgrade_doc_rows(text)
    headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(text)]
    rows_without_heading, _ = find_changes_row_correspondence_gaps(rows, headings, deps, canonical_names)
    if not rows_without_heading:
        return text, []
    missing = set(rows_without_heading)

    added_names = []
    for row in rows:
        if row["name"] not in missing:
            continue
        ident = resolve_component_identity(row["name"], deps, canonical_names)
        if ident is None:
            continue
        section = build_changes_section_for_row(row, ident, deps, target)
        if section is None:
            continue
        text = insert_changes_section(text, section, row["name"], deps, target_values, canonical_names)
        added_names.append(row["name"])

    return text, added_names


def _remove_changes_block_by_exact_heading(text, heading):
    """remove_changes_section, but matched by EXACT heading text instead
    of fuzzy word-span containment — used for replacing a specific,
    already-identified stale heading (see update_stale_app_version_
    headings), where a fuzzy match risks hitting the wrong block if some
    OTHER heading happens to share words with this one. Returns
    (new_text, removed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    block = next((b for b in blocks if b["heading"] == heading), None)
    if block is None:
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


def update_stale_app_version_headings(text, chart_dir, deps, target_values, target, canonical_names):
    """Regenerate a "### ..." Changes section whose own heading is
    missing the primary-image app version (see lib.upgradedoc.changes_
    heading_has_app_version) for a component that DOES have one
    resolvable now (real case: "### openbao 0.28.4" — add_missing_
    component_rows' own chart-only TODO-stub shape, written back before
    actual_app_version could resolve anything — fixed later by
    registering openbao in COMPONENT_IMAGE_PATHS/adding the vendored-
    chart appVersion fallback, but the already-written heading never
    gets touched just because resolution got smarter). Built the exact
    same way add_missing_changes_sections builds a genuinely missing
    section (see build_changes_section_for_row), from that component's
    OWN table row — the stale heading's entire old body is discarded
    (there's no reliable way to tell which part of its own prose is
    still accurate once the heading itself was already wrong, same
    reasoning as a freshly-added section).

    Only ever touches a heading naming EXACTLY ONE real "dep" component
    (never a sidecar — a canonical sidecar heading is only ever written
    once its own tag is already known, so this gap doesn't apply to
    it — see canonical_sidecar_row_names) whose actual_app_version DOES
    resolve; a heading that's ambiguous, orphaned, or genuinely has no
    resolvable app version yet is left exactly as-is, matching the same
    finding lib.docs_consistency.check_docs_consistency's own "is
    missing the primary-image app version" check reports. Returns
    (new_text, updated_headings) — updated_headings is the ORIGINAL
    (pre-fix) heading text for every section actually rewritten."""
    rows_by_identity = {}
    for row in parse_upgrade_doc_rows(text):
        ident = resolve_component_identity(row["name"], deps, canonical_names)
        if ident is not None:
            rows_by_identity[ident] = row

    stale_headings = []
    for heading in [b["heading"] for b in parse_upgrade_doc_changes_blocks(text)]:
        if changes_heading_has_app_version(heading):
            continue
        idents = changes_heading_identities(heading, deps, canonical_names)
        if len(idents) != 1:
            continue
        ident = next(iter(idents))
        if ident[0] != "dep":
            continue
        stale_headings.append((heading, ident))

    updated_headings = []
    for heading, ident in stale_headings:
        _, values_key = ident
        dep = dep_for_values_key(deps, values_key)
        if dep is None:
            continue
        actual_app = actual_app_version(target_values, values_key, dep["name"], chart_dir=chart_dir, dep=dep)
        if not actual_app:
            continue
        row = rows_by_identity.get(ident)
        if row is None:
            continue
        section = build_changes_section_for_row(row, ident, deps, target)
        if section is None:
            continue

        text, removed = _remove_changes_block_by_exact_heading(text, heading)
        if not removed:
            continue
        text = insert_changes_section(text, section, row["name"], deps, target_values, canonical_names)
        updated_headings.append(heading)

    return text, updated_headings


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


def update_image_manifest(images_path, basename, repository, old_version, new_version, digest, deps=(), values=None,
                           canonical_names=None):
    """Update the "# <N> changes:" header list and the images-manifest
    entry for a shared image basename bump — keyed by `repository` (an
    entry's "url:" resolving to it, host-stripped same as the "name:"
    convention docs/images/acr-mirror-naming.md documents), not a
    values-tree path. Returns (changes_action, entry_updated) —
    entry_updated is False (not an error) when no existing entry's
    "url:" matches this repository; the caller reports the correct
    name/url to add by hand instead, same convention as
    lib.component_docs.update_images_manifest's own missing_entries.

    deps/values/canonical_names position a BRAND-NEW header item at this
    basename's own real values.yaml order slot (lib.upgradedoc.
    component_order_key — the SAME convention update-image-version's own
    update_docs_shared_image already uses to position this exact
    basename's "Component versions" table row/"### ..." Changes section
    in the upgrade doc, via canonical_names' "global" shared-image
    fallback) — real bug this fixes: this function used to always
    APPEND a new item at the very end of the existing list regardless of
    where it really belongs, while lib.component_docs.update_images_
    manifest (the sibling function for a real Chart.yaml dependency's
    own bump) already positioned ITS new items by values.yaml order —
    the two disagreeing on ordering convention meant a component bumped
    through THIS function (e.g. a shared "global.images" anchor) could
    land its header item in a position that contradicted another
    component's own item bumped through the OTHER function in the very
    same run, scrambling the header list's order relative to the entries
    below it even though neither individual insert was wrong on its own
    (confirmed live: images-4.9.1.yaml's own "redis 8.0 (new)." item,
    always appended last here, ended up AFTER "mi ...unchanged."'s own
    values.yaml-order-positioned item even though redis's real entry
    sits earlier). Omit (or pass deps=(), values=None) only where no
    real ordering context is available at all — falls back to appending
    at the end, same as before, never crashes."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    # find_images_manifest_changes_header (not a bare CHANGES_HEADER_RE
    # scan) — the real, hand-curated images-manifest header is the plain
    # "# Changes:" form (no count word at all), which CHANGES_HEADER_RE
    # alone never recognizes (see that function's own docstring for the
    # identical bug already fixed in update_images_manifest/lib.
    # component_docs — this was the same gap in THIS function, just never
    # given the same fix). Silently finding no header at all meant this
    # whole block — and so the header-list item — was skipped outright
    # for every MULTIPLE-scope basename bump against a real manifest,
    # never even reaching the "no existing entry" case a human could act
    # on.
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)

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

        item_text = f"{basename} {image_manifest_version_text(old_version, new_version)}."

        if match_idx is not None:
            m = CHANGES_ITEM_RE.match(lines[match_idx])
            lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
            changes_action = "updated"
        elif values is not None:
            # insert_images_manifest_header_item never rewrites the
            # header's own wording into a counted form ("# Three
            # changes:") — same bare "# Changes:" convention this
            # function already matched before this fix.
            key_order = values_key_order(values)
            new_key = component_order_key(basename, deps, key_order, canonical_names, values)
            insert_images_manifest_header_item(lines, deps, key_order, new_key, item_text)
            changes_action = "added"
        else:
            # No ordering context given at all — fall back to the
            # previous always-append behavior rather than guessing.
            new_num = len(item_indices) + 1
            insert_at = block_end if item_indices else header_idx + 1
            lines.insert(insert_at, f"#   {new_num}. {item_text}\n")
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

    # Same bare-header fix as update_image_manifest above — see its own
    # comment for why a plain CHANGES_HEADER_RE scan alone never finds
    # the real manifest's own "# Changes:" header.
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)

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
            # Never rewrites the header's own wording — see
            # update_image_manifest's identical comment above.
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


IMAGES_BASELINE_HEADER = (
    "# Baseline images — the single, complete strip-registry mirror manifest.\n"
    "#\n"
    "# This is a full, CURRENT snapshot of every image PodiumD pulls right now —\n"
    "# every component's own primary image, every sidecar, every MULTIPLE/global-\n"
    "# anchored shared image — under the strip-registry mirror convention:\n"
    "#   name = strip_registry(url): upstream url with the registry host removed,\n"
    "#   full <namespace>/<repo> path kept.\n"
    "# Versions are the tags currently pinned in charts/podiumd/values.yaml (or the\n"
    "# owning subchart). Digests are the tag's own embedded \"@sha256:...\" suffix\n"
    "# when it has one, else resolved live against the source registry\n"
    "# (Docker-Content-Digest / manifest_digest).\n"
    "#\n"
    "# Fully regenerated by fix-doc-consistency on every run (lib.image_docs.\n"
    "# regenerate_images_baseline_manifest) — always a complete, wholesale\n"
    "# snapshot, never incremental patching: no hand-maintained gap-fillers, no\n"
    "# \"NOT INCLUDED\" exclusion notes, no stale dual-version entries. Editing this\n"
    "# file by hand is pointless — the next run overwrites it entirely.\n"
)


def regenerate_images_baseline_manifest(chart_dir, deps, values, images_baseline_path, rendered_paths):
    """Overwrite docs/images/images-baseline.yaml WHOLESALE with a full,
    CURRENT snapshot of every image pinned anywhere in the chart right
    now — every component's own primary image, every sidecar, every
    MULTIPLE/global-anchored shared image (find_all_image_and_version_
    paths(values, deps) + global_image_paths(values), the SAME
    enumeration images-<target>.yaml's own diffing already uses, just
    never filtered down to "changed since baseline" — every path,
    always) PLUS every image find_unresolved_subchart_images(chart_dir,
    rendered_paths) finds: a genuinely-live image defined only in a
    vendored dependency's own default values.yaml, with no podiumd
    override at all (e.g. eck-operator's own top-level "image:", null
    tag, resolved to the dependency's own Chart.yaml appVersion — see
    lib.chart.resolve_subchart_default) — otherwise invisible to this
    regeneration the same way it's invisible to check_digest_pinning,
    since neither one ever looks past podiumd's own values.yaml on its
    own. `rendered_paths` (see lib.render_scope.rendered_chart_paths, a
    real `helm template` render) gates these exactly as check_subchart_
    image_visibility's own findings are gated — a dependency (or one of
    ITS OWN nested dependencies) disabled via condition:/tags: never
    contributes an entry here, e.g. openinwoner's own bundled nested
    eck-operator (globally disabled via tags:) or zaakbrug's own
    condition-disabled "staging" block.

    One entry per distinct repository (paths_by_repository/
    repo_group_representative's own dedup convention — a shared anchor
    like global.images.nginx, aliased by several components, collapses
    to ONE entry, same as images-<target>.yaml already does), sorted by
    images_manifest_entry_order_key — the exact same sort key images-
    <target>.yaml's own entries already use.

    Never incremental: no gap-fillers, no "NOT INCLUDED" exclusion
    notes, no stale dual-version entries (e.g. frankgateway's old
    pre-SemVer "104" alongside its current pin) — a fresh, complete
    regeneration every time this runs, replacing whatever was there
    before entirely.

    `name` is the stripped repo (paths_by_repository's own group key —
    already in the correct strip_registry(url) form, no host); `url` is
    the REAL, fully host-qualified repository (lib.chart.full_
    repository_for_path — the same helper the "url:" host-qualification
    fix added, reused here so the two can never drift on what a
    repository's real url is); `version`/`digest` come from the pin's
    own embedded "@sha256:..." suffix (lib.chart.resolved_digest_pin)
    when it has one, else a live registry lookup (lib.registry.
    registry_tag_exists) — matching the file's own header comment
    ("Digests are ... resolved live against the source registry").

    Repository resolution itself (paths_by_repository/full_repository_
    for_path) stays offline-only (allow_pull=False, their own default) —
    a real chart always has every dependency already vendored, so this
    never needs a fresh `helm pull`; only the DIGEST lookup, when
    needed, ever goes over the network. Never allow_pull=True here: a
    synthetic/test dependency with no real Helm repository behind it
    would otherwise make every run of this attempt one regardless.

    Returns (written, skipped, changed) — written is the number of
    entries in the freshly-computed snapshot (whether or not it was
    actually written to disk this run); skipped is [repo, ...] for
    every repository group whose full url couldn't be resolved, or
    whose digest couldn't be resolved at all (no embedded digest AND
    the live registry lookup failed) — never silently dropped without
    a trace, same "report it, don't guess" convention every other
    entry-writer here uses; changed is True only when the freshly-
    computed content actually differs from what's already on disk (or
    the file doesn't exist yet) — write_text is only ever called in
    that case, the same "no spurious write, no spurious mtime/git-diff
    churn" gating fix-doc-consistency's own main() already applies to
    every OTHER doc it manages (upgrade.md/images-<target>.yaml/
    values-deltas.md's own write_needed-style checks) — this was the
    one exception, confirmed live: every run rewrote (and reported on)
    this file regardless of whether anything about it actually
    changed."""
    current_paths = dict(find_all_image_and_version_paths(values, deps))
    current_paths.update(global_image_paths(values))
    for scope_key, subpath, tag, _already_pinned in find_unresolved_subchart_images(chart_dir, deps, values, rendered_paths):
        current_paths.setdefault((scope_key, *subpath.split(".")), tag)
    repo_groups = paths_by_repository(chart_dir, deps, values, current_paths.keys())
    key_order = values_key_order(values)

    resolved, skipped = [], []
    for repo, group_paths in repo_groups.items():
        representative = repo_group_representative(group_paths, deps)
        tag = current_paths[representative]
        full_repo = full_repository_for_path(chart_dir, deps, values, representative)
        if full_repo is None:
            skipped.append(repo)
            continue

        pinned = resolved_digest_pin(values, representative, tag)
        if pinned is not None:
            new_version, digest = pinned.split("@", 1)
        else:
            new_version = tag.split("@", 1)[0]
            host, repo_path = parse_repo(full_repo)
            exists, digest = registry_tag_exists(host, repo_path, new_version)
            if not exists or not digest:
                skipped.append(repo)
                continue

        sort_key = images_manifest_entry_order_key(representative, deps, key_order, values)
        resolved.append((sort_key, repo, full_repo, new_version, digest))

    resolved.sort(key=lambda entry: entry[0])

    lines = [IMAGES_BASELINE_HEADER, "\n"]
    for _sort_key, repo, full_repo, new_version, digest in resolved:
        lines.append(f"- name: {repo}\n")
        lines.append(f"  url: {full_repo}\n")
        lines.append(f'  version: "{new_version}"\n')
        lines.append(f'  digest: "{digest}"\n')
        lines.append("\n")
    text = "".join(lines)
    # A blank line after every entry (including the last) leaves the
    # file ending in "...\n\n" — one syntactic blank line before EOF.
    # Collapsed down to a single trailing newline, the same "exactly one
    # final newline, never a blank line right before EOF" convention
    # collapse_multiple_blank_lines already enforces for the three
    # .md docs this script manages.
    if text.endswith("\n\n"):
        text = text[:-1]
    current_text = images_baseline_path.read_text(encoding="utf-8") if images_baseline_path.is_file() else None
    changed = text != current_text
    if changed:
        images_baseline_path.write_text(text, encoding="utf-8")
    return len(resolved), skipped, changed
