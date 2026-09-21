"""Checks that component versions in Chart.yaml + values.yaml match the
matching docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and
docs/images/images-<version>.yaml — and, given upgrade_docs_baseline
(see lib.chart.upgrade_docs_baseline), that every component that
actually changed vs. that baseline has a row/mention/entry in the right
doc, even if no doc mentions it yet. Only ever this one baseline —
lib.chart.release_table_baseline never flows into this file; see that
function's own docstring for why podiumd needs two baselines now."""

import re

from lib.chart_pull_and_subchart_resolution import global_image_paths, resolved_digest_pin
from lib.chart_release_baseline_basics import load_yaml
from lib.chart_repo_and_path_resolution import (
    canonical_sidecar_row_names,
    paths_by_repository,
    repo_group_representative,
)
from lib.chart_values_tree_primitives import version_of
from lib.component_docs.changes_section import (
    resolve_component_own_version_change,
    strip_stale_upgrade_placeholders,
)
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.values_delta_sections import (
    has_stale_gemeente_specific_placeholder,
    strip_stale_values_deltas_todo_stub,
)
from lib.docs_consistency.images_manifest_format import check_images_manifest_format
from lib.docs_consistency.markdown_format import check_baseline_doc_set, check_companion_doc, check_doc_title
from lib.docs_consistency.pointer_consistency import check_pointer_consistency
from lib.docs_consistency.values_diff import check_values_deltas_content
from lib.release_baseline import resolve_baseline_chart_state
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc_app_version_and_image_paths import find_image_tag_paths, resolve_entry_image_path
from lib.upgradedoc_consistency_checks import (
    find_changes_row_correspondence_gaps,
    find_wrong_or_duplicate_dependency_claims,
)
from lib.upgradedoc_images_manifest_list_diff import compute_changed_components
from lib.upgradedoc_resolve_component_row import (
    changes_heading_has_app_version,
    resolve_component_row,
)
from lib.upgradedoc_sorting_and_ordering import (
    find_out_of_order_names,
    parse_upgrade_doc_changes_blocks,
    parse_values_delta_sections,
    values_key_order,
)
from lib.upgradedoc_string_and_parsing_basics import changes_heading_identities, normalize_version
from lib.upgradedoc_string_and_parsing_basics import (
    parse_upgrade_doc_rows as _parse_upgrade_doc_rows,
)
from lib.upgradedoc_version_cells_and_key_changes import component_version_cell


def parse_upgrade_doc_rows(doc_path):
    return _parse_upgrade_doc_rows(doc_path.read_text(encoding="utf-8"))


def check_docs_consistency(chart_dir, upgrade_docs_baseline=None):
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    podiumd_version = str(chart_yaml["version"])
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}
    sibling_fields = digest_pinning_exceptions(chart_dir)

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
    # Same identity keying as resolved_app_by_identity, holding the
    # BASELINE side instead (None when the component is genuinely new at
    # the baseline, or when no baseline_ref was even given) — populated
    # alongside it below. Used, together with resolved_app_by_identity,
    # to catch a Changes heading whose own "(new)"/"(unchanged)"/"X -> Y"
    # wording DISAGREES with what the row itself would render there (see
    # "app-version wording disagrees with its own row" below) — a real,
    # observed bug: a heading can show the CORRECT current version yet
    # the WRONG transition wording (e.g. "(unchanged)" for a component
    # that's actually new), which changes_heading_has_app_version's own
    # "is some version shown at all" check can never catch.
    baseline_app_by_identity = {}

    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    is_bare_version = bool(upgrade_docs_baseline and re.match(r"^\d+\.\d+\.\d+", upgrade_docs_baseline))

    if is_bare_version:
        precheck_issues = check_baseline_doc_set(doc_dir, upgrade_docs_baseline, podiumd_version)
        if precheck_issues:
            print(
                f"FOUND {len(precheck_issues)} issue(s) with the upgrade_docs_baseline doc set "
                f"(checked before any other check on these documents):"
            )
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
        pointer_docs = [
            doc_dir / f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
            for suffix in ("upgrade", "gemeente-specific", "values-deltas")
        ]
        images_path_for_pointers = images_dir / f"images-{podiumd_version}.yaml"
        if images_path_for_pointers.is_file():
            pointer_docs.append(images_path_for_pointers)
        pointer_issues = [
            issue
            for doc in pointer_docs
            for issue in check_pointer_consistency(doc, upgrade_docs_baseline, podiumd_version, doc_dir, images_dir)
        ]
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

                # Stale-placeholder findings (see lib.component_docs'
                # own strip_stale_values_deltas_todo_stub/has_stale_
                # gemeente_specific_placeholder) — reported here even
                # for a doc fix-doc-consistency's own retroactive pass
                # would already auto-fix (values-deltas), since a doc
                # can carry this between being written and that script
                # next running; gemeente-specific has no fixer at all,
                # only ever this finding.
                companion_path = doc_dir / doc_name
                if companion_path.is_file():
                    companion_text = companion_path.read_text(encoding="utf-8")
                    if suffix == "values-deltas" and strip_stale_values_deltas_todo_stub(companion_text)[1]:
                        mismatches.append(
                            f"{doc_name}: still has its own stale TODO placeholder stranded alongside a "
                            f'real "## ..." section — run fix-doc-consistency to clear it'
                        )
                    elif suffix == "gemeente-specific" and has_stale_gemeente_specific_placeholder(companion_text):
                        mismatches.append(
                            f'{doc_name}: still has its own stale "_None recorded yet._" placeholder '
                            f'stranded alongside a real "## <gemeente> (<env>)" section — clear it by hand '
                            f"(nothing auto-fixes this one)"
                        )
        else:
            print(
                f'WARNING: upgrade_docs_baseline "{upgrade_docs_baseline}" is not a bare version — cannot check '
                f"for matching gemeente-specific / values-deltas docs"
            )

    baseline_ref, baseline_deps, baseline_values = None, [], {}
    if upgrade_docs_baseline:
        # resolve_baseline_chart_state is shared with lib.component_docs'
        # own load_baseline_state/load_baseline_values (and, new,
        # verify-release-table-with-podiumd's own release_table_baseline
        # lookup) — see its own docstring for why (a real bug in this
        # exact resolution used to need fixing in three places at once).
        baseline_ref, baseline_deps, baseline_values, _baseline_lines, baseline_error = resolve_baseline_chart_state(
            chart_dir, upgrade_docs_baseline
        )
        if baseline_error:
            mismatches.append(f'upgrade_docs_baseline "{upgrade_docs_baseline}": {baseline_error}')

    # Ground truth for "did this component actually change" — independent of
    # what the docs currently say, so it also catches a component that
    # changed but was never added to any doc at all.
    actual_changed_keys = (
        compute_changed_components(deps, baseline_deps, values, baseline_values) if baseline_ref else set()
    )
    current_paths = dict(find_image_tag_paths(values))
    current_paths.update(global_image_paths(values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_ref else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_ref else [])
    repo_groups = paths_by_repository(chart_dir, deps, values, current_paths.keys()) if chart_dir is not None else {}
    repo_map = {repo: repo_group_representative(paths, deps) for repo, paths in repo_groups.items()}

    if not doc_matches:
        print(f"WARNING: no upgrade doc matches {doc_glob} — skipping doc check")
    else:
        if len(doc_matches) > 1:
            print(
                f"WARNING: multiple upgrade docs match {doc_glob}: "
                f"{', '.join(p.name for p in doc_matches)} — using {doc_matches[-1].name}"
            )
        doc_path = doc_matches[-1]
        checked.append(doc_path.name)
        if is_bare_version:
            mismatches.extend(check_doc_title(doc_path, upgrade_docs_baseline, podiumd_version))

        # Stale-placeholder finding, same reasoning as the values-deltas/
        # gemeente-specific ones above — reported even when fix-doc-
        # consistency's own retroactive pass would already auto-fix it,
        # since it can be stranded between a doc being written and that
        # script next running (see lib.component_docs.strip_stale_
        # upgrade_placeholders, reused here unapplied — its own `changed`
        # flag doubles as this finding, no separate detector to drift).
        if strip_stale_upgrade_placeholders(doc_path.read_text(encoding="utf-8"))[1]:
            mismatches.append(
                f'{doc_path.name}: still has a stale "TODO" placeholder stranded alongside real content '
                f"— run fix-doc-consistency to clear it"
            )

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
            [row["name"] for row in rows], deps
        )

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
                row["name"],
                chart_dir,
                canonical_names,
                deps,
                values,
                baseline_deps=baseline_deps if baseline_ref else None,
                baseline_values=baseline_values,
                upgrade_docs_baseline=upgrade_docs_baseline if baseline_ref else None,
            )
            if resolved["kind"] == "unmatched":
                mismatches.append(
                    f'{doc_path.name}: doc row "{row["name"]}" does not match a Chart.yaml '
                    f'dependency or a canonical sidecar/shared-image name ("<component> - '
                    f'<basename>" or "<basename>", the exact form update-image-version writes) '
                    f"— wrong phrasing, or a stale row"
                )
                continue

            sidecar_path = resolved["sidecar_path"]
            values_key, top_level_key = resolved["values_key"], resolved["top_level_key"]
            actual_chart, actual_app = resolved["target_chart"], resolved["target_app"]

            if resolved["kind"] == "sidecar":
                matched_sidecar_paths.add(sidecar_path)
            elif actual_app:
                # "dependency" and "native" (see lib.chart.native_components)
                # share this identity shape — resolve_component_identity/
                # changes_heading_identities both resolve a native
                # component to ("dep", values_key) too, so this dict's own
                # keys must match theirs.
                resolved_app_by_identity[("dep", values_key)] = actual_app

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
                    f"be verified against {baseline_ref} — the component didn't exist there yet, "
                    f"or its version isn't resolvable there; source cells left unchecked"
                )
                if resolved["kind"] != "sidecar" and actual_app:
                    baseline_app_by_identity[("dep", values_key)] = None
                continue

            baseline_chart_actual, baseline_app_actual = resolved["baseline_chart"], resolved["baseline_app"]
            if resolved["kind"] != "sidecar" and actual_app:
                baseline_app_by_identity[("dep", values_key)] = baseline_app_actual

            if (
                row["chart_source"]
                and baseline_chart_actual
                and normalize_version(row["chart_source"]) != normalize_version(baseline_chart_actual)
            ):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") source chart: {baseline_ref} has '
                    f'"{baseline_chart_actual}", {doc_path.name} says "{row["chart_source"]}"'
                )
            if baseline_app_actual and normalize_version(row["app_source"]) != normalize_version(baseline_app_actual):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") source app: {baseline_ref} has '
                    f'"{baseline_app_actual}", {doc_path.name} says "{row["app_source"] or "-"}"'
                )

        if baseline_ref:
            for key in sorted(actual_changed_keys - changed_component_keys):
                # A key whose OWN chart+app both resolve unchanged never
                # needed a row of its own in the first place — see
                # resolve_component_own_version_change (shared with fix-
                # doc-consistency's own add_missing_component_rows, so
                # the two can never drift on which keys actually need
                # one); whatever else made `key` register as changed
                # (almost always a brand-new/changed sidecar nested
                # under it) already gets its own separate row.
                resolved = resolve_component_own_version_change(
                    key, deps, baseline_deps, values, baseline_values, chart_dir, upgrade_docs_baseline
                )
                if resolved is not None and resolved[-1]:
                    continue
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
                baseline_tag, current_tag = baseline_paths.get(path), current_paths.get(path)
                # Compared by VERSION (lib.chart.version_of — the tag with
                # any "@sha256:..." digest suffix stripped), never the raw
                # tag string — a digest-only re-pin (same version, e.g. a
                # chart-wide digest-pinning sweep) is not a "changed vs
                # baseline" case -upgrade.md needs a row for. Real bug:
                # this comparison used to be raw-tag equality, so nginx-
                # unprivileged (version unchanged, only its digest moved)
                # was flagged forever — the exact same class of bug already
                # fixed in lib.upgradedoc.compute_changed_components and
                # lib.image_docs.add_missing_sidecar_rows, just never
                # ported to this one, independent copy of the same check.
                if (version_of(baseline_tag) if baseline_tag is not None else None) != (
                    version_of(current_tag) if current_tag is not None else None
                ):
                    mismatches.append(
                        f'{doc_path.name}: sidecar/shared image "{name}" changed vs {baseline_ref} '
                        f'but has no row in the "Component versions" table'
                    )

        key_order = values_key_order(values)
        row_names = [row["name"] for row in parse_upgrade_doc_rows(doc_path)]
        for name_a, name_b in find_out_of_order_names(row_names, deps, key_order, canonical_names, values):
            mismatches.append(
                f'{doc_path.name}: "Component versions" table lists "{name_b}" right after "{name_a}", '
                f"but values.yaml lists {name_b} before {name_a} — rows should follow values.yaml's "
                f"own component order"
            )

        doc_text = doc_path.read_text(encoding="utf-8")
        changes_headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(doc_text)]
        for name_a, name_b in find_out_of_order_names(changes_headings, deps, key_order, canonical_names, values):
            mismatches.append(
                f'{doc_path.name}: "## Changes" section has "### {name_b}" right after "### {name_a}", '
                f"but values.yaml lists the {name_b} component before {name_a} — Changes blocks should "
                f"follow values.yaml's own component order"
            )

        # Only checked when the doc actually has a "## Changes" heading at
        # all — a fixture/stub doc that never got that far yet (no section
        # to compare against) would otherwise have EVERY row reported as
        # missing its heading, which isn't the gap this check exists to
        # catch.
        has_changes_section = any(line.strip() == "## Changes" for line in doc_text.splitlines())
        if has_changes_section:
            rows_without_heading, headings_without_row = find_changes_row_correspondence_gaps(
                rows, changes_headings, deps, canonical_names
            )
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
                identity = next(iter(idents))
                actual_app = resolved_app_by_identity.get(identity)
                if actual_app and not changes_heading_has_app_version(heading):
                    mismatches.append(
                        f'{doc_path.name}: "## Changes" section "### {heading}" is missing the '
                        f'primary-image app version in its own heading — values.yaml shows "{actual_app}"'
                    )
                    continue

                # A heading can ALREADY show the correct current app
                # version yet still get the transition wording wrong (real
                # bug: "openbao v2.5.5 (unchanged)" when openbao's own
                # baseline app version was actually unresolvable — the
                # component is really "(new)" to this doc, per component_
                # version_cell's own convention). changes_heading_has_app_
                # version only ever checks "is SOME version shown at all",
                # never whether the shown wording is the CORRECT one for
                # baseline_app -> actual_app — this reuses component_
                # version_cell directly (the exact function that decides
                # this for the table row's own cell — see fix_component_
                # version_table/update_component_table) so the row and its
                # own Changes heading can never independently drift on
                # what "correct" wording even means, the same "shared
                # resolution" principle resolve_component_row's own
                # docstring already applies to the row side.
                if baseline_ref and identity in baseline_app_by_identity:
                    expected_app_heading = component_version_cell(baseline_app_by_identity[identity], actual_app)
                    without_chart_clause = re.sub(r"\(chart[^)]*\)", "", heading)
                    if expected_app_heading not in without_chart_clause:
                        mismatches.append(
                            f'{doc_path.name}: "## Changes" section "### {heading}" shows the wrong '
                            f'app-version transition in its own heading — expected "{expected_app_heading}" '
                            f"(values.yaml/{baseline_ref} show {baseline_app_by_identity[identity]!r} -> "
                            f"{actual_app!r})"
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
            images_path,
            upgrade_docs_baseline,
            podiumd_version,
            deps,
            values,
            baseline_values if baseline_ref else {},
            chart_dir=chart_dir,
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
        entries_list = load_yaml(images_path) or []

        # Simple, always-reliable complement to the per-entry "has an
        # entry but no mention in the '# Changes:' list" check further
        # below: that one resolves each entry to its own display name
        # first and silently skips one it can't resolve, so it isn't a
        # guaranteed catch-all for the header being gone entirely. Real
        # bug this fixes: images-4.9.1.yaml gained 5 real entries this
        # session with no "# Changes:" header ever created for them to
        # be listed in (see lib.component_docs.ensure_images_manifest_
        # changes_header's own docstring) — a real manifest with real
        # entries but literally no header line anywhere should never
        # pass silently.
        if entries_list:
            manifest_lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
            header_idx, _has_count = find_images_manifest_changes_header(manifest_lines)
            if header_idx is None:
                noun = "entry" if len(entries_list) == 1 else "entries"
                mismatches.append(
                    f'{images_path.name}: has {len(entries_list)} {noun} but no "# Changes:" header '
                    f"at all — every real change is undocumented in the summary list"
                )

        for entry in entries_list:
            name = entry.get("name")
            if not name:
                continue
            path = resolve_entry_image_path(entry, current_paths.keys(), repo_map)
            if not path:
                print(f'  ({images_path.name}: entry "{name}" — no matching image in values.yaml, skipped)')
                continue

            version, digest = entry.get("version"), entry.get("digest")
            if not version or not digest:
                mismatches.append(f'{name}: entry in {images_path.name} is missing "version" or "digest"')
                continue
            expected_tag = f"{version}@{digest}"
            actual_tag = resolved_digest_pin(values, path, current_paths[path], sibling_fields) or current_paths[path]
            if actual_tag != expected_tag:
                mismatches.append(
                    f'{name}: values.yaml tag is "{actual_tag}", {images_path.name} says "{expected_tag}"'
                )

            if baseline_ref and baseline_paths.get(path) == expected_tag:
                mismatches.append(
                    f"{name}: listed in {images_path.name} as new/changed, but {baseline_ref} "
                    f'already has this exact tag ("{expected_tag}") — did it actually change?'
                )

    if baseline_ref and is_bare_version and actual_changed_keys:
        values_deltas_path = doc_dir / f"{upgrade_docs_baseline}-to-{podiumd_version}-values-deltas.md"
        canonical_names_for_deltas = canonical_sidecar_row_names(chart_dir, deps, values, current_paths.keys())
        mismatches.extend(
            check_values_deltas_content(
                values_deltas_path, actual_changed_keys, baseline_values, values, deps, canonical_names_for_deltas
            )
        )

        deltas_key_order = values_key_order(values)
        deltas_headings = [
            s["heading"] for s in parse_values_delta_sections(values_deltas_path.read_text(encoding="utf-8"))
        ]
        for name_a, name_b in find_out_of_order_names(
            deltas_headings, deps, deltas_key_order, canonical_names_for_deltas, values
        ):
            mismatches.append(
                f'{values_deltas_path.name}: "## {name_b}" section comes right after "## {name_a}", '
                f"but values.yaml lists the {name_b} component before {name_a} — sections should follow "
                f"values.yaml's own component order"
            )

    if not checked:
        return True, "no matching docs found — skipped"

    if mismatches:
        print(f"FOUND {len(mismatches)} mismatch(es) vs {', '.join(checked)}:")
        for m in sorted(mismatches):
            print(" ", m)
        return False, f"{len(mismatches)} mismatch(es)"
    print(f"OK: chart versions match {', '.join(checked)}")
    return True, f"matches {', '.join(checked)}"
