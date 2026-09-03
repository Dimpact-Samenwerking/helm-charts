"""Checks that component versions in Chart.yaml + values.yaml match the
matching docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and
docs/images/images-<version>.yaml — and, given upgrade_docs_baseline
(see lib.chart.upgrade_docs_baseline), that every component that
actually changed vs. that baseline has a row/mention/entry in the right
doc, even if no doc mentions it yet. Only ever this one baseline —
lib.chart.release_table_baseline never flows into this file; see that
function's own docstring for why podiumd needs two baselines now."""
import re

import yaml

from lib.chart import canonical_sidecar_row_names, load_yaml, paths_by_repository
from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.image_repository_check import find_images_without_repository
from lib.upgradedoc import (
    actual_app_version, changes_heading_has_app_version, changes_heading_identities, compute_changed_components,
    diff_keys, extract_mentioned_dependency_keys, extract_source_version, extract_target_version,
    find_changes_row_correspondence_gaps, find_grouped_preceding_comment, find_image_tag_paths,
    find_images_manifest_list_diff, find_out_of_order_names, find_wrong_or_duplicate_dependency_claims,
    match_dependency, match_dependency_excluding_sidecar_names, normalize_version, pair_renames,
    parse_changes_block, parse_upgrade_doc_changes_blocks, parse_upgrade_doc_rows as _parse_upgrade_doc_rows,
    path_display_name, resolve_component_row, resolve_entry_path, strip_fenced_code_blocks,
    values_key_order,
)


def parse_upgrade_doc_rows(doc_path):
    return _parse_upgrade_doc_rows(doc_path.read_text(encoding="utf-8"))


def check_doc_title(doc_path, upgrade_docs_baseline, podiumd_version):
    """Verify a doc's first line states the "<upgrade_docs_baseline> → <podiumd_version>"
    pair — catches a doc that was renamed without updating its own heading."""
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    first_line = lines[0] if lines else ""
    if not re.search(rf"{re.escape(upgrade_docs_baseline)}\s*(?:→|->)\s*{re.escape(podiumd_version)}", first_line):
        return [f'{doc_path.name} title line "{first_line}" does not read '
                f'"{upgrade_docs_baseline} → {podiumd_version}"']
    return []


def check_companion_doc(doc_dir, upgrade_docs_baseline, podiumd_version, suffix):
    """When a bare-version upgrade_docs_baseline is given, verify the matching
    <upgrade_docs_baseline>-to-<podiumd_version>-<suffix>.md exists and its title line
    states the same "<upgrade_docs_baseline> → <podiumd_version>" pair."""
    name = f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
    doc_path = doc_dir / name
    if not doc_path.is_file():
        return name, [f'expected "{name}" does not exist']
    return name, check_doc_title(doc_path, upgrade_docs_baseline, podiumd_version)


def check_markdown_format(doc_path):
    """Minimal sanity check that a doc is well-formed markdown, before trying
    to parse anything out of it: non-empty, opens with a level-1 heading, and
    any fenced code blocks are balanced (an unclosed ``` silently swallows
    the rest of the file when rendered)."""
    text = doc_path.read_text(encoding="utf-8")
    if not text.strip():
        return ["file is empty"]

    issues = []
    first_line = text.splitlines()[0]
    if not first_line.startswith("# "):
        issues.append(f'first line "{first_line}" is not a level-1 heading ("# ...")')

    fence_count = len(re.findall(r"^```", text, re.MULTILINE))
    if fence_count % 2 != 0:
        issues.append(f"{fence_count} fenced code block markers (```) — unbalanced")

    return issues


def check_baseline_doc_set(doc_dir, upgrade_docs_baseline, podiumd_version):
    """Existence + markdown-format precheck for all three upgrade_docs_baseline docs,
    run BEFORE any content-based check on them — a doc that's missing or
    malformed makes every downstream check on it meaningless."""
    issues = []
    for suffix in ("upgrade", "gemeente-specific", "values-deltas"):
        name = f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
        doc_path = doc_dir / name
        if not doc_path.is_file():
            issues.append(f'expected "{name}" does not exist')
            continue
        issues.extend(f"{name}: {issue}" for issue in check_markdown_format(doc_path))
    return issues


SIBLING_DOC_RE = re.compile(
    r"(\d+\.\d+\.\d+)-to-(\d+\.\d+\.\d+)-(upgrade|gemeente-specific|values-deltas)\.md")
IMAGES_REF_RE = re.compile(r"images-(\d+\.\d+\.\d+)\.yaml")


def check_pointer_consistency(doc_path, upgrade_docs_baseline, podiumd_version, doc_dir, images_dir):
    """Every reference to a sibling <X>-to-<Y>-*.md doc or an images-<Z>.yaml
    manifest found anywhere in this doc — comment, prose, or markdown link.
    A reference whose target release (Y or Z) isn't podiumd_version is about
    some other historical hop and is left alone; one that targets the current
    release must have the current upgrade_docs_baseline as its source, and must actually
    exist (catches a reference left stale after a rename)."""
    text = doc_path.read_text(encoding="utf-8")
    issues = []

    for m in SIBLING_DOC_RE.finditer(text):
        from_v, to_v, suffix = m.groups()
        if normalize_version(to_v) != normalize_version(podiumd_version):
            continue
        if normalize_version(from_v) != normalize_version(upgrade_docs_baseline):
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" targets podiumd '
                           f'{podiumd_version} but its upgrade_docs_baseline is "{from_v}", expected "{upgrade_docs_baseline}"')
        elif not (doc_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    for m in IMAGES_REF_RE.finditer(text):
        version = m.group(1)
        if normalize_version(version) != normalize_version(podiumd_version):
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" targets podiumd '
                           f'{version}, expected "{podiumd_version}"')
        elif not (images_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    return issues


def _match_changes_item_to_entry(item_name, entries):
    """Best-effort match of a Changes-block item's free-form name (e.g.
    "Python (ensurePodiumdAdminUser init image)") to one of this SAME
    images-manifest's own entries — for an item that isn't a component at
    all (a plain image with no Chart.yaml dependency of its own to check
    against), so it isn't wrongly flagged as "no matching Chart.yaml
    dependency" just because it was never going to have one. Deliberately
    self-contained (reads only the file already being validated) rather
    than reaching into release-table.csv's own "used_by" column — that
    file is release_table_baseline-scoped, not upgrade_docs_baseline-
    scoped, and isn't guaranteed to exist or be current for whatever hop
    is being checked here.

    Reuses match_dependency's own word-containment matching, against each
    entry's final name segment (e.g. "python" from "library/python", an
    ACR-mirror-style slug the item's own prose never spells out in full)
    rather than a Chart.yaml dependency's name/alias. None if no entry's
    basename shows up this way.

    A canonical "<key> - <basename>" sidecar name (see
    lib.chart.canonical_sidecar_row_names — the same " - " delimiter
    match_dependency_excluding_sidecar_names already trusts as never
    appearing in a real dependency's own name/alias) is matched on its
    OWN basename specifically, not the whole string: matching the whole
    string risks the LEADING <key> word fuzzy-matching an UNRELATED
    entry that happens to share that word — real case: "keycloak-
    operator - postgres" (the postgres client image bundled with the
    keycloak-operator dependency) wrongly matched the "keycloak" entry
    (keycloak's own, unrelated primary image) instead of "postgres",
    since match_dependency has no reason to prefer the trailing word."""
    candidates = [{"name": entry["name"].rsplit("/", 1)[-1], "_entry": entry}
                  for entry in entries if entry.get("name")]
    search_text = item_name.split(" - ", 1)[1] if " - " in item_name else item_name
    match = match_dependency(search_text, candidates)
    return match["_entry"] if match else None


def check_images_manifest_format(images_path, upgrade_docs_baseline, podiumd_version, deps, values, baseline_values,
                                  chart_dir=None):
    """Existence + YAML-validity + header-comment-accuracy precheck for the
    images manifest, run BEFORE the entry-by-entry content checks — mirrors
    check_baseline_doc_set for the three markdown docs. Also checks the
    manifest's own entry LIST against the full, actual set of images that
    changed vs upgrade_docs_baseline (see find_images_manifest_list_diff)
    — every changed image must have an entry, and every entry must
    correspond to a real change, once chart_dir is given."""
    if not images_path.is_file():
        return [f'expected "{images_path.name}" does not exist']

    text = images_path.read_text(encoding="utf-8")
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"{images_path.name} is not valid YAML: {e}"]
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return [f"{images_path.name} does not contain a YAML list of mappings"]
    for i, entry in enumerate(entries):
        missing = [k for k in ("name", "url", "version", "digest") if k not in entry]
        if missing:
            return [f'{images_path.name} entry #{i + 1} is missing key(s): {", ".join(missing)}']

    issues = []

    baseline_m = re.search(r"Baseline:\s*podiumd\s+([\w.\-]+)", text)
    if not baseline_m:
        issues.append(f'{images_path.name}: no "Baseline: podiumd <version>" line found')
    elif normalize_version(baseline_m.group(1)) != normalize_version(upgrade_docs_baseline):
        issues.append(f'{images_path.name}: upgrade_docs_baseline line says "{baseline_m.group(1)}", expected "{upgrade_docs_baseline}"')

    vs_m = re.search(r"podiumd\s+([\w.\-]+)\s+vs\s+([\w.\-]+)", text)
    if not vs_m:
        issues.append(f'{images_path.name}: no "podiumd <target> vs <upgrade_docs_baseline>" line found')
    else:
        vs_target, vs_baseline = vs_m.group(1).rstrip("."), vs_m.group(2).rstrip(".")
        if normalize_version(vs_target) != normalize_version(podiumd_version):
            issues.append(f'{images_path.name}: "... vs ..." line says target "{vs_target}", '
                           f'expected "{podiumd_version}"')
        if normalize_version(vs_baseline) != normalize_version(upgrade_docs_baseline):
            issues.append(f'{images_path.name}: "... vs ..." line says upgrade_docs_baseline "{vs_baseline}", '
                           f'expected "{upgrade_docs_baseline}"')

    items = list(parse_changes_block(text))
    # Same two deterministic gaps as lib.docs_consistency's own upgrade-doc
    # row loop (see find_wrong_or_duplicate_dependency_claims) — a
    # free-form Changes item fuzzy-matching a dependency another item
    # already exactly claims. Real, live case this catches: item "Kiss's
    # ECK-managed Elasticsearch/Kibana/Enterprise Search 8.19.3 ->
    # 8.19.19" fuzzy-matches the real "kiss" dependency on the word
    # "kiss" (there's also an exact "KISS 2.2.4 -> 3.0.0" item) and was
    # being compared against kiss's own unrelated actual app version —
    # same for "clamav_exporter (metrics sidecar) ..." vs the exact
    # "ClamAV ..." item.
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [item["name"] for item in items], deps)

    for item in items:
        if item["name"] in duplicate_names or item["name"] in wrong_fuzzy_names:
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" is wrong or stale — '
                           f'not found in Chart.yaml or values.yaml')
            continue

        # match_dependency_excluding_sidecar_names, not match_dependency
        # directly — a canonical sidecar/shared-image Changes item like
        # "keycloak-operator - python 3.14-slim -> 3.14.7-slim." must
        # never fuzzy-match the real "keycloak-operator" dependency on
        # its leading word and get compared against ITS OWN unrelated
        # actual app version; it falls through to the "plain image"
        # entry-matching branch below instead, same as any other
        # non-component Changes item.
        dep = match_dependency_excluding_sidecar_names(item["name"], deps)
        if dep:
            values_key = dep.get("alias", dep["name"])
            actual_app = actual_app_version(values, values_key, dep["name"], chart_dir=chart_dir, dep=dep)
            actual_chart = dep["version"]
            baseline_app = actual_app_version(baseline_values, values_key, dep["name"]) if baseline_values else None
        else:
            # Not every Changes item is a component — a plain image (e.g. an
            # init-container image with no subchart/dependency of its own)
            # has nothing in Chart.yaml to match against at all; fall back
            # to this same manifest's own entries instead of treating that
            # as an error (see _match_changes_item_to_entry).
            entry = _match_changes_item_to_entry(item["name"], entries)
            if entry is None:
                issues.append(f'{images_path.name}: Changes item "{item["name"]}" — no matching '
                               f'Chart.yaml dependency or images-manifest entry')
                continue
            actual_app = entry.get("version")
            actual_chart = None  # a plain image has no chart version to check
            baseline_app = None  # no baseline lookup available without a component scope

        if item["app"] and actual_app and normalize_version(item["app"]) != normalize_version(actual_app):
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" target app '
                           f'"{item["app"]}" != values.yaml "{actual_app}"')
        if item["chart"] and actual_chart and normalize_version(item["chart"]) != normalize_version(actual_chart):
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" target chart '
                           f'"{item["chart"]}" != Chart.yaml "{actual_chart}"')
        if item["app_source"] and baseline_app and \
                normalize_version(item["app_source"]) != normalize_version(baseline_app):
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" source app '
                           f'"{item["app_source"]}" != upgrade_docs_baseline "{baseline_app}"')

    lines = text.splitlines()
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    current_paths = dict(find_image_tag_paths(values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}

    def component_of(entry):
        path = resolve_entry_path(entry["name"], current_paths.keys())
        return path[0] if path else None

    def same_group(entry_a, entry_b):
        return (component_of(entry_a) is not None
                and component_of(entry_a) == component_of(entry_b)
                and entry_a.get("version") == entry_b.get("version"))

    for index, (entry, line_idx) in enumerate(zip(entries, entry_line_indices)):
        comment = find_grouped_preceding_comment(
            lines, entries, entry_line_indices, index, same_group)
        if not comment:
            issues.append(f'{images_path.name}: entry "{entry["name"]}" has no preceding comment')
            continue

        target = extract_target_version(comment)
        if target and normalize_version(target) != normalize_version(entry["version"]):
            issues.append(f'{images_path.name}: entry "{entry["name"]}" comment says target '
                           f'"{target}", entry version is "{entry["version"]}"')

        if baseline_paths:
            path = resolve_entry_path(entry["name"], current_paths.keys())
            baseline_tag = baseline_paths.get(path) if path else None
            baseline_version = baseline_tag.split("@")[0] if baseline_tag else None
            source = extract_source_version(comment)
            if source and baseline_version and \
                    normalize_version(source) != normalize_version(baseline_version):
                issues.append(f'{images_path.name}: entry "{entry["name"]}" comment says source '
                               f'"{source}", upgrade_docs_baseline actually has "{baseline_version}"')

    # Only checked once there's something real to diff against — without
    # a resolvable upgrade_docs_baseline, "changed" can't be computed at
    # all (baseline_values is {} in that case, so baseline_paths is too).
    if baseline_paths and chart_dir is not None:
        repo_groups = paths_by_repository(chart_dir, deps, values, current_paths.keys())
        repo_map = {repo: paths[-1] for repo, paths in repo_groups.items()}
        canonical_names = canonical_sidecar_row_names(chart_dir, deps, values, current_paths.keys())
        unresolvable_paths = set(find_images_without_repository(chart_dir))
        missing_paths, extra_entry_names = find_images_manifest_list_diff(
            entries, current_paths, baseline_paths, repo_map, repo_groups, unresolvable_paths)
        for path in missing_paths:
            name = path_display_name(path, deps, canonical_names)
            issues.append(f'{images_path.name}: image "{name}" changed vs '
                           f'{upgrade_docs_baseline} but has no entry')
        for name in extra_entry_names:
            issues.append(f'{images_path.name}: entry "{name}" is listed but its image did not '
                           f'change vs {upgrade_docs_baseline}')

    return issues


def check_values_deltas_content(doc_path, changed_component_keys, baseline_values, values):
    """Verify every top-level component key that was added, removed, or
    renamed between the upgrade_docs_baseline and now is actually mentioned (backtick-
    quoted, matching the doc convention) in values-deltas.md."""
    text = doc_path.read_text(encoding="utf-8")
    backtick_spans = re.findall(r"`([^`]+)`", strip_fenced_code_blocks(text))
    no_changes_claimed = bool(re.search(
        r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", text, re.IGNORECASE))

    issues = []
    all_added, all_removed, all_renamed = [], [], []
    for values_key in sorted(changed_component_keys):
        baseline_subtree = baseline_values.get(values_key, {}) if isinstance(baseline_values, dict) else {}
        current_subtree = values.get(values_key, {}) if isinstance(values, dict) else {}
        diffs = list(diff_keys(baseline_subtree, current_subtree, (values_key,)))
        added = [p for kind, p in diffs if kind == "added"]
        removed = [p for kind, p in diffs if kind == "removed"]
        renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)
        all_added.extend(added)
        all_removed.extend(removed)
        all_renamed.extend(renamed)

    def mentioned(dotted):
        return any(dotted in span or span in dotted for span in backtick_spans)

    for path in all_added:
        dotted = ".".join(path)
        if not mentioned(dotted):
            issues.append(f'{doc_path.name}: key "{dotted}" was added but is not mentioned '
                           f'(backtick-quoted) anywhere in the doc')
    for path in all_removed:
        dotted = ".".join(path)
        if not mentioned(dotted):
            issues.append(f'{doc_path.name}: key "{dotted}" was removed but is not mentioned '
                           f'(backtick-quoted) anywhere in the doc')
    for old_path, new_path in all_renamed:
        old_dotted, new_dotted = ".".join(old_path), ".".join(new_path)
        if not (mentioned(old_dotted) and mentioned(new_dotted)):
            issues.append(f'{doc_path.name}: key "{old_dotted}" appears renamed to "{new_dotted}" '
                           f'but this rename is not mentioned (backtick-quoted, both sides) in the doc')

    if issues and no_changes_claimed:
        issues.insert(0, f'{doc_path.name}: claims "No gemeente podiumd.yml changes are required" '
                          f'but {len(issues)} key change(s) were found — see below')
    return issues


def check_docs_consistency(chart_dir, upgrade_docs_baseline=None):
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    podiumd_version = str(chart_yaml["version"])
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}

    mismatches = []
    checked = []
    changed_component_keys = set()
    # (kind, values_key) identity -> its resolved, real app version (see
    # resolve_component_identity) — populated below for every "dep" row
    # whose own actual_app_version resolves to something. Used after the
    # row loop to catch a Changes heading whose own text never shows an
    # app-version pair at all for a component that DOES have one — see
    # "is missing the primary-image app version" below.
    resolved_app_by_identity = {}

    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    is_bare_version = bool(upgrade_docs_baseline and re.match(r"^\d+\.\d+\.\d+", upgrade_docs_baseline))

    if is_bare_version:
        precheck_issues = check_baseline_doc_set(doc_dir, upgrade_docs_baseline, podiumd_version)
        if precheck_issues:
            print(f"FOUND {len(precheck_issues)} issue(s) with the upgrade_docs_baseline doc set "
                  f"(checked before any other check on these documents):")
            for issue in sorted(precheck_issues):
                print(" ", issue)
            return False, f"{len(precheck_issues)} upgrade_docs_baseline doc issue(s)"

        # Unlike check_baseline_doc_set above, a stale sibling-doc/images-
        # manifest reference is a pure content finding about a doc that DOES
        # exist and IS well-formed — nothing downstream needs to read or
        # parse the reference itself, so there's no crash risk in still
        # running every other check. Recorded into `mismatches` (reported
        # together with everything else at the end) rather than an early
        # return, so a single stale link can no longer hide every other
        # finding this function would otherwise have made (e.g. missing
        # "Component versions" rows, missing values-deltas mentions,
        # images-manifest content mismatches) — the exact bug class fixed
        # for check_images_manifest_format's own early return, just here
        # for a precheck that had NOTHING already computed to lose, so it
        # was invisible until a real doc set tripped it.
        images_dir = chart_dir / "docs" / "images"
        pointer_docs = [doc_dir / f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
                        for suffix in ("upgrade", "gemeente-specific", "values-deltas")]
        images_path_for_pointers = images_dir / f"images-{podiumd_version}.yaml"
        if images_path_for_pointers.is_file():
            pointer_docs.append(images_path_for_pointers)
        pointer_issues = [issue for doc in pointer_docs
                           for issue in check_pointer_consistency(doc, upgrade_docs_baseline, podiumd_version,
                                                                   doc_dir, images_dir)]
        mismatches.extend(pointer_issues)

    if is_bare_version:
        doc_glob = f"{upgrade_docs_baseline}-to-{podiumd_version}-upgrade.md"
    else:
        doc_glob = f"*-to-{podiumd_version}-upgrade.md"
    doc_matches = sorted(doc_dir.glob(doc_glob))

    if upgrade_docs_baseline:
        if is_bare_version:
            for suffix in ("gemeente-specific", "values-deltas"):
                doc_name, doc_mismatches = check_companion_doc(doc_dir, upgrade_docs_baseline, podiumd_version, suffix)
                checked.append(doc_name)
                mismatches.extend(doc_mismatches)
        else:
            print(f'WARNING: upgrade_docs_baseline "{upgrade_docs_baseline}" is not a bare version — cannot check '
                  f'for matching gemeente-specific / values-deltas docs')

    baseline_ref, baseline_chart_yaml, baseline_values = None, None, {}
    if upgrade_docs_baseline:
        repo_root = find_repo_root(chart_dir)
        candidates = baseline_ref_candidates(upgrade_docs_baseline)
        if not repo_root:
            mismatches.append(f'upgrade_docs_baseline "{upgrade_docs_baseline}": {chart_dir} is not inside a git repository')
        else:
            baseline_ref = resolve_git_ref(repo_root, candidates)
            if not baseline_ref:
                mismatches.append(f'upgrade_docs_baseline "{upgrade_docs_baseline}": could not resolve to a git ref '
                                   f'(tried {", ".join(candidates)})')
            else:
                rel_chart_dir = chart_dir.relative_to(repo_root)
                baseline_chart_yaml = git_show_yaml(repo_root, baseline_ref, f"{rel_chart_dir}/Chart.yaml")
                baseline_values = git_show_yaml(repo_root, baseline_ref, f"{rel_chart_dir}/values.yaml") or {}
                if baseline_chart_yaml is None:
                    mismatches.append(f'upgrade_docs_baseline "{upgrade_docs_baseline}" (ref {baseline_ref}): '
                                       f'could not read Chart.yaml at that ref')
                    baseline_ref = None

    baseline_deps = baseline_chart_yaml.get("dependencies", []) if baseline_chart_yaml else []
    # Ground truth for "did this component actually change" — independent of
    # what the docs currently say, so it also catches a component that
    # changed but was never added to any doc at all.
    actual_changed_keys = (
        compute_changed_components(deps, baseline_deps, values, baseline_values)
        if baseline_ref else set()
    )
    current_paths = dict(find_image_tag_paths(values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_ref else {}

    if not doc_matches:
        print(f"WARNING: no upgrade doc matches {doc_glob} — skipping doc check")
    else:
        if len(doc_matches) > 1:
            print(f"WARNING: multiple upgrade docs match {doc_glob}: "
                  f"{', '.join(p.name for p in doc_matches)} — using {doc_matches[-1].name}")
        doc_path = doc_matches[-1]
        checked.append(doc_path.name)
        if is_bare_version:
            mismatches.extend(check_doc_title(doc_path, upgrade_docs_baseline, podiumd_version))
        if baseline_ref:
            checked.append(f"upgrade_docs_baseline {baseline_ref}")

        canonical_names = canonical_sidecar_row_names(chart_dir, deps, values, current_paths.keys())
        matched_sidecar_paths = set()

        rows = list(parse_upgrade_doc_rows(doc_path))

        # Two more deterministic gaps, checked once up front before the
        # main per-row pass below — see find_wrong_or_duplicate_dependency_
        # claims for exactly what these catch (duplicate row names, and a
        # free-form row fuzzy-matching a dependency another row already
        # exactly claims, e.g. a stale "Kiss Elasticsearch" row).
        duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
            [row["name"] for row in rows], deps)

        for name in sorted(duplicate_names | wrong_fuzzy_names):
            mismatches.append(
                f'{doc_path.name}: doc row "{name}" is wrong or stale — not found in Chart.yaml or values.yaml'
            )

        for row in rows:
            if row["name"] in duplicate_names or row["name"] in wrong_fuzzy_names:
                continue

            # resolve_component_row is shared with fix-doc-consistency's own
            # row-rewriter (fix_component_version_table) — see its docstring
            # for why (a checker/fixer that resolve a row two different ways
            # can silently drift apart on what "correct" even means).
            resolved = resolve_component_row(
                row["name"], chart_dir, canonical_names, deps, values,
                baseline_deps=baseline_deps if baseline_ref else None, baseline_values=baseline_values,
            )
            if resolved["kind"] == "unmatched":
                mismatches.append(
                    f'{doc_path.name}: doc row "{row["name"]}" does not match a Chart.yaml '
                    f'dependency or a canonical sidecar/shared-image name ("<component> - '
                    f'<basename>" or "<basename>", the exact form update-image-version writes) '
                    f'— wrong phrasing, or a stale row'
                )
                continue

            dep, sidecar_path = resolved["dep"], resolved["sidecar_path"]
            values_key, top_level_key = resolved["values_key"], resolved["top_level_key"]
            actual_chart, actual_app = resolved["target_chart"], resolved["target_app"]

            if dep is not None:
                if actual_app:
                    resolved_app_by_identity[("dep", values_key)] = actual_app
            else:
                matched_sidecar_paths.add(sidecar_path)

            changed_component_keys.add(top_level_key)

            if row["chart"] and normalize_version(row["chart"]) != normalize_version(actual_chart):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") target chart: Chart.yaml has "{actual_chart}", '
                    f'{doc_path.name} says "{row["chart"]}"'
                )
            if actual_app and normalize_version(row["app"]) != normalize_version(actual_app):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") target app: values.yaml image tag is "{actual_app}", '
                    f'{doc_path.name} says "{row["app"] or "-"}"'
                )

            if not baseline_ref:
                continue

            if resolved["baseline_resolved"] is False:
                # A warning, not a mismatch — most commonly a brand-new
                # component with no baseline version to compare against at
                # all (fix-doc-consistency's own fix_component_version_
                # table writes "(new)" cells for exactly this row shape),
                # not a doc/reality disagreement this check exists to catch.
                print(
                    f'WARNING: {doc_path.name}: doc row "{row["name"]}" source version could not '
                    f'be verified against {baseline_ref} — the component didn\'t exist there yet, '
                    f'or its version isn\'t resolvable there; source cells left unchecked'
                )
                continue

            baseline_chart_actual, baseline_app_actual = resolved["baseline_chart"], resolved["baseline_app"]

            if row["chart_source"] and baseline_chart_actual and \
                    normalize_version(row["chart_source"]) != normalize_version(baseline_chart_actual):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") source chart: {baseline_ref} has '
                    f'"{baseline_chart_actual}", {doc_path.name} says "{row["chart_source"]}"'
                )
            if baseline_app_actual and \
                    normalize_version(row["app_source"]) != normalize_version(baseline_app_actual):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") source app: {baseline_ref} has '
                    f'"{baseline_app_actual}", {doc_path.name} says "{row["app_source"] or "-"}"'
                )

        if baseline_ref:
            for key in sorted(actual_changed_keys - changed_component_keys):
                mismatches.append(
                    f'{doc_path.name}: component "{key}" changed vs {baseline_ref} but has no row '
                    f'in the "Component versions" table'
                )

            # The check above only catches a component with NO row at all —
            # a dependency whose own primary row exists already satisfies
            # it, even when one of ITS OWN sidecars changed and has no row
            # of its own (e.g. redis-operator's own row exists, but its
            # nested redis-ha image bump has never been added at all — a
            # true omission match_dependency's own row-matching can't see,
            # since there's no row whose name even claims to be about it).
            for name, path in sorted(canonical_names.items()):
                if path in matched_sidecar_paths:
                    continue
                if baseline_paths.get(path) != current_paths.get(path):
                    mismatches.append(
                        f'{doc_path.name}: sidecar/shared image "{name}" changed vs {baseline_ref} '
                        f'but has no row in the "Component versions" table'
                    )

        key_order = values_key_order(values)
        row_names = [row["name"] for row in parse_upgrade_doc_rows(doc_path)]
        for name_a, name_b in find_out_of_order_names(row_names, deps, key_order):
            mismatches.append(
                f'{doc_path.name}: "Component versions" table lists "{name_b}" right after "{name_a}", '
                f'but values.yaml lists {name_b} before {name_a} — rows should follow values.yaml\'s '
                f'own component order'
            )

        doc_text = doc_path.read_text(encoding="utf-8")
        changes_headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(doc_text)]
        for name_a, name_b in find_out_of_order_names(changes_headings, deps, key_order):
            mismatches.append(
                f'{doc_path.name}: "## Changes" section has "### {name_b}" right after "### {name_a}", '
                f'but values.yaml lists the {name_b} component before {name_a} — Changes blocks should '
                f'follow values.yaml\'s own component order'
            )

        # Only checked when the doc actually has a "## Changes" heading at
        # all — a fixture/stub doc that never got that far yet (no section
        # to compare against) would otherwise have EVERY row reported as
        # missing its heading, which isn't the gap this check exists to
        # catch.
        has_changes_section = any(line.strip() == "## Changes" for line in doc_text.splitlines())
        if has_changes_section:
            rows_without_heading, headings_without_row = find_changes_row_correspondence_gaps(
                rows, changes_headings, deps, canonical_names)
            for name in rows_without_heading:
                mismatches.append(
                    f'{doc_path.name}: table row "{name}" has no matching "### ..." section under "## Changes"'
                )
            for heading in headings_without_row:
                mismatches.append(
                    f'{doc_path.name}: "## Changes" section "### {heading}" has no matching row in the '
                    f'"Component versions" table'
                )

            # A heading naming exactly one "dep" component that DOES have a
            # real, resolved app version (see resolved_app_by_identity)
            # must actually show it — a heading written back when that
            # version wasn't resolvable yet (e.g. openbao's own "###
            # openbao 0.28.4" — chart-only, add_missing_component_rows'
            # TODO-stub shape) never gets rewritten just because
            # actual_app_version later learns how to resolve it (fix-
            # doc-consistency never rewrites an EXISTING section's own
            # text), so this can silently go stale forever unless checked
            # for directly.
            for heading in changes_headings:
                idents = changes_heading_identities(heading, deps, canonical_names)
                if len(idents) != 1:
                    continue
                actual_app = resolved_app_by_identity.get(next(iter(idents)))
                if actual_app and not changes_heading_has_app_version(heading):
                    mismatches.append(
                        f'{doc_path.name}: "## Changes" section "### {heading}" is missing the '
                        f'primary-image app version in its own heading — values.yaml shows "{actual_app}"'
                    )

    images_path = chart_dir / "docs" / "images" / f"images-{podiumd_version}.yaml"

    # Whether the manifest's own entries are safe to interpret at all (valid
    # YAML, a list of dicts with the required keys — see
    # check_images_manifest_format) — False skips the entry-by-entry checks
    # below (they'd have nothing well-formed to read), but must NOT discard
    # mismatches already found above (e.g. a missing "Component versions"
    # table row) the way an early return here used to: those are completely
    # unrelated to this manifest's own formatting, and a human fixing a
    # header-comment typo shouldn't have to re-run this check a second time
    # just to learn about them.
    images_format_ok = True
    if is_bare_version:
        format_issues = check_images_manifest_format(
            images_path, upgrade_docs_baseline, podiumd_version, deps, values,
            baseline_values if baseline_ref else {}, chart_dir=chart_dir
        )
        if format_issues:
            images_format_ok = False
            checked.append(images_path.name)
            mismatches.extend(format_issues)

    if not images_path.is_file():
        print(f"WARNING: no images manifest at {images_path.name} — skipping images-manifest check")
    elif not images_format_ok:
        pass  # format issue(s) already recorded above; entries aren't safely interpretable until fixed
    else:
        checked.append(images_path.name)
        for entry in (load_yaml(images_path) or []):
            name = entry.get("name")
            if not name:
                continue
            path = resolve_entry_path(name, current_paths.keys())
            if not path:
                print(f'  (images-manifest entry "{name}" — no matching image in values.yaml, skipped)')
                continue

            expected_tag = f'{entry["version"]}@{entry["digest"]}'
            actual_tag = current_paths[path]
            if actual_tag != expected_tag:
                mismatches.append(
                    f'{name}: values.yaml tag is "{actual_tag}", '
                    f'{images_path.name} says "{expected_tag}"'
                )

            if baseline_ref and baseline_paths.get(path) == expected_tag:
                mismatches.append(
                    f'{name}: listed in {images_path.name} as new/changed, but {baseline_ref} '
                    f'already has this exact tag ("{expected_tag}") — did it actually change?'
                )

    if baseline_ref and is_bare_version and actual_changed_keys:
        values_deltas_path = doc_dir / f"{upgrade_docs_baseline}-to-{podiumd_version}-values-deltas.md"
        mentioned_keys = extract_mentioned_dependency_keys(
            values_deltas_path.read_text(encoding="utf-8"), deps)
        for key in sorted(actual_changed_keys - mentioned_keys):
            mismatches.append(
                f'{values_deltas_path.name}: component "{key}" changed vs {baseline_ref} but is '
                f'not mentioned anywhere in the doc'
            )
        mismatches.extend(check_values_deltas_content(
            values_deltas_path, actual_changed_keys, baseline_values, values))

    if not checked:
        return True, "no matching docs found — skipped"

    if mismatches:
        print(f"FOUND {len(mismatches)} mismatch(es) vs {', '.join(checked)}:")
        for m in sorted(mismatches):
            print(" ", m)
        return False, f"{len(mismatches)} mismatch(es)"
    print(f"OK: chart versions match {', '.join(checked)}")
    return True, f"matches {', '.join(checked)}"
