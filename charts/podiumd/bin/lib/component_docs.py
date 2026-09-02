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

from lib.chart import image_paths_for, replace_scalar_value, version_paths_for
from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.upgradedoc import (
    _word_aligned_spans, actual_app_version, append_to_doc, canonical_version_cell, component_order_key,
    extract_mentioned_dependency_keys, extract_source_version, find_grouped_preceding_comment_line,
    insertion_index, match_dependency_excluding_sidecar_names, normalize_name, normalize_version,
    parse_upgrade_doc_changes_blocks, parse_upgrade_doc_rows, replace_version_pair, resolve_entry_path,
    values_key_order,
)

NUMBER_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen"]
CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)(?P<count_word>\w+)\s+changes?:\s*$", re.IGNORECASE)
CHANGES_ITEM_RE = re.compile(r"^#\s*(?P<num>\d+)\.\s+(?P<rest>.+)$")
NO_CHANGES_CLAIMED_RE = re.compile(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", re.IGNORECASE)


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
    own new row."""
    norm_friendly = normalize_name(friendly)
    for row in rows:
        if norm_friendly in _word_aligned_spans(row["name"]):
            return row
    return None


def update_component_table(text, friendly, old_app, new_app, old_chart, new_chart, deps, values):
    """Update this component's "Component versions" table row if it's
    already mentioned, or insert a new row if it isn't — in values.yaml's
    own top-level component order relative to the rows already there (see
    lib.upgradedoc.component_order_key/insertion_index), not always at
    the end. Returns (new_text, action) where action is "updated" or
    "added" (or None if the doc has no table at all to insert into)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)

    app_cell = canonical_version_cell(old_app, new_app) if old_app else new_app
    chart_cell = canonical_version_cell(old_chart, new_chart) if old_chart else new_chart

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
        new_key = component_order_key(friendly, deps, key_order)
        existing_keys = [component_order_key(r["name"], deps, key_order) for r in rows]
        idx = insertion_index(new_key, existing_keys)
        insert_at = rows[idx]["line_index"] if idx < len(rows) else rows[-1]["line_index"] + 1
    else:
        insert_at = None
        for i, line in enumerate(lines):
            if re.match(r"^\|\s*:?-+:?\s*\|", line.strip()):
                insert_at = i + 1
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
    paths_for's own registration to know which applies."""
    chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
    chart_suffix = f" (chart {old_chart} → {new_chart})" if chart_changed else f" (chart {new_chart}, unchanged)"
    lines = [f"### {friendly} {old_app} → {new_app}{chart_suffix}\n\n"]
    lines.append(f"PodiumD {target} upgrades **{friendly}** from app version {old_app}\n")
    lines.append(f"to {new_app}.\n\n")
    if chart_changed:
        lines.append(f"- Helm chart `{chart_name}` `{old_chart}` → `{new_chart}` in\n")
        lines.append("  `charts/podiumd/Chart.yaml`.\n")
    for path in image_paths:
        lines.append(f"- Image tag pin `{values_key}.{path}.tag` `{old_app}` → `{new_app}` in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    for path in version_paths:
        lines.append(f"- Version pin `{values_key}.{path}` `{old_app}` → `{new_app}` in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    lines.append(f"- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def insert_changes_section(text, section_text, friendly, deps, values):
    """Insert section_text as a new "### ..." block into the "## Changes"
    section, in values.yaml's own top-level component order relative to
    the blocks already there (see lib.upgradedoc.component_order_key/
    insertion_index) — not always at the end. Appends right before the
    next "## " heading (or EOF) if the section doesn't exist yet, or has
    no blocks of its own yet to compare against."""
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
        new_key = component_order_key(friendly, deps, key_order)
        existing_keys = [component_order_key(b["heading"], deps, key_order) for b in blocks]
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

    A key with no matching Chart.yaml dependency at all (e.g. an orphan
    values.yaml block like frankgateway) is skipped — there's no
    dep["version"] to read a Helm chart version from, so nothing here
    can be generated confidently; add that row by hand. A key whose app
    version can't be resolved via actual_app_version's own known shapes
    (<key>.image.tag, frontend/backend, COMPONENT_VERSION_PATHS' bare
    version fields, or a registered COMPONENT_IMAGE_PATHS component's
    vendored-chart appVersion fallback — see that function's own
    docstring) gets a "-" app-version placeholder and a short TODO-stub
    Changes section instead of guessing at prose. Returns (new_text, added_names)."""
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

    added_names = []
    for key in sorted(actual_changed_keys - matched_keys):
        dep = dep_for_values_key(target_deps, key)
        if dep is None:
            continue
        chart_name = dep["name"]
        baseline_dep = dep_for_values_key(baseline_deps, key) if baseline_deps else None
        old_chart = str(baseline_dep["version"]) if baseline_dep else None
        new_chart = str(dep["version"])
        old_app = actual_app_version(baseline_values, key, chart_name) if baseline_values else None
        new_app = actual_app_version(target_values, key, chart_name, chart_dir=chart_dir, dep=dep)

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
            section = make_changes_section(key, target, chart_name, key, old_app or new_app, new_app,
                                            old_chart or new_chart, new_chart, image_paths, version_paths)
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


def values_delta_bullet(friendly, old_app, new_app, old_chart, new_chart):
    app_changed = normalize_version(old_app) != normalize_version(new_app)
    chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
    app_bit = f"`{old_app} → {new_app}`" if app_changed else f"`{new_app}` (unchanged)"
    chart_bit = f"`{old_chart} → {new_chart}`" if chart_changed else f"`{new_chart}`, unchanged"
    note = "image tag only" if not chart_changed else "chart + image tag"
    return f"- **{friendly}** app {app_bit} (chart {chart_bit}) — {note}.\n"


def add_missing_values_delta_bullets(text, chart_dir, target_deps, target_values, baseline_deps, baseline_values,
                                      actual_changed_keys):
    """Append a "- **<name>** app ..." bullet (see values_delta_bullet) for
    every key in `actual_changed_keys` that isn't already mentioned via a
    bold "**Name**" span anywhere in `text` (see extract_mentioned_
    dependency_keys — the exact gap check_docs_consistency's own
    "component ... changed vs ... but is not mentioned anywhere in the
    doc" finding reports). Resolves each bullet's own old/new app+chart
    versions the same way add_missing_component_rows does for the
    "Component versions" table row, so a component's bullet here and its
    table row always agree.

    A key with no matching Chart.yaml dependency at all is skipped (see
    dep_for_values_key) — nothing here can be generated confidently
    without a real Chart.yaml version to read. A key whose app version
    can't be resolved via actual_app_version's own known shapes (see
    that function's own docstring) gets a short TODO bullet instead of
    a value-less "app `None`" line.
    Returns (new_text, added_names)."""
    mentioned_keys = extract_mentioned_dependency_keys(text, target_deps)
    new_lines = []
    added_names = []
    for key in sorted(actual_changed_keys - mentioned_keys):
        dep = dep_for_values_key(target_deps, key)
        if dep is None:
            continue
        baseline_dep = dep_for_values_key(baseline_deps, key) if baseline_deps else None
        old_chart = str(baseline_dep["version"]) if baseline_dep else None
        new_chart = str(dep["version"])
        old_app = actual_app_version(baseline_values, key, dep["name"]) if baseline_values else None
        new_app = actual_app_version(target_values, key, dep["name"], chart_dir=chart_dir, dep=dep)

        if new_app is not None:
            new_lines.append(values_delta_bullet(key, old_app or new_app, new_app,
                                                  old_chart or new_chart, new_chart))
        else:
            chart_bit = (f"`{old_chart} → {new_chart}`"
                         if old_chart and normalize_version(old_chart) != normalize_version(new_chart)
                         else f"`{new_chart}`, unchanged")
            new_lines.append(f"- **{key}** chart {chart_bit} — TODO: describe this component's "
                              f"changes; its app version could not be resolved automatically.\n")
        added_names.append(key)

    return append_to_doc(text, new_lines), added_names


def remove_component_values_delta(text, friendly):
    """Delete this component's version-bullet block from values-deltas.md
    entirely: the "- **<friendly>** app ..." (values_delta_bullet) or
    "- **<basename>** image ..." (lib.image_docs.image_delta_bullet)
    bullet line, plus any immediately-following describe_key_changes
    lines appended alongside it (a bullet's own caller always appends
    them together as one contiguous block — see append_to_doc). Used both
    to collapse more than one bump within a release into a single
    up-to-date bullet (remove the stale one before appending the fresh
    one) and to remove it outright when a bump nets out to no change from
    upgrade_docs_baseline at all. Returns (new_text, removed)."""
    lines = text.splitlines(keepends=True)
    norm_friendly = normalize_name(friendly)
    bullet_re = re.compile(r"^-\s+\*\*([^*]+)\*\*\s+\w+\b")
    start = None
    for i, line in enumerate(lines):
        m = bullet_re.match(line)
        if m and norm_friendly in normalize_name(m.group(1)):
            start = i
            break
    if start is None:
        return text, False
    end = start + 1
    while end < len(lines) and lines[end].startswith("- ") and not bullet_re.match(lines[end]):
        end += 1
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


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
                            paths_to_update, repos, new_tags_by_path):
    """Update the "# <N> changes:" header list and any existing entries'
    version/digest/comment for this component. Returns (changes_action,
    entry_names_updated, missing_entries) where missing_entries is
    [(image_path, repo, new_tag), ...] for components with no existing
    entry — never invented here. "name:" is mechanically derivable now
    (strip_registry(repo), see docs/images/acr-mirror-naming.md) but this
    function doesn't compute it — a full manifest entry still needs a
    human-authored comment/heading, so callers print a placeholder and
    leave the whole entry for manual review rather than a script writing
    part of it and a human the rest."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    header_idx = None
    for i, line in enumerate(lines):
        if CHANGES_HEADER_RE.match(line):
            header_idx = i
            break

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

        norm_friendly = normalize_name(friendly)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_friendly in normalize_name(m.group("rest")):
                match_idx = idx
                break

        chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
        chart_bit = f"{old_chart} -> {new_chart}" if chart_changed else f"{new_chart}, unchanged"
        item_text = f"{friendly} {old_app} -> {new_app} (chart {chart_bit})."

        if match_idx is not None:
            m = CHANGES_ITEM_RE.match(lines[match_idx])
            lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
            changes_action = "updated"
        else:
            new_num = len(item_indices) + 1
            insert_at = block_end if item_indices else header_idx + 1
            lines.insert(insert_at, f"#   {new_num}. {item_text}\n")
            count_word = NUMBER_WORDS[new_num] if new_num < len(NUMBER_WORDS) else str(new_num)
            noun = "change" if new_num == 1 else "changes"
            header_m = CHANGES_HEADER_RE.match(lines[header_idx])
            lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
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

    header_idx = None
    for i, line in enumerate(lines):
        if CHANGES_HEADER_RE.match(line):
            header_idx = i
            break

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
            count_word = NUMBER_WORDS[remaining] if remaining < len(NUMBER_WORDS) else str(remaining)
            noun = "change" if remaining == 1 else "changes"
            header_m = CHANGES_HEADER_RE.match(lines[header_idx])
            lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
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
