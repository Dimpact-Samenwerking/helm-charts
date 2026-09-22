"""The standard per-target doc set (upgrade/gemeente-specific/values-deltas
+ images manifest) and the baseline state a component's own version-bump
docs are written against: scaffolding missing stub docs
(create_missing_docs, STANDARD_SUFFIXES, STUB_TEMPLATES,
IMAGES_STUB_TEMPLATE), scanning what already exists (existing_doc_
baselines, DOC_FILENAME_RE_TMPL), and reading values.yaml/Chart.yaml as
they were at a resolved upgrade_docs_baseline (load_baseline_values,
load_baseline_state). Shared by create-doc-version, fix-doc-consistency,
update-component-version, and update-image-version. Split out of the
former flat lib/component_docs.py, now the lib.component_docs package
(see lib.component_docs itself, plus its still-to-come sibling modules
for images-manifest changes headers, the changes section, values-delta
sections, and images-manifest entries)."""

import re

from lib.gitutil import baseline_ref_candidates
from lib.gitutil import find_repo_root
from lib.gitutil import git_show_yaml
from lib.gitutil import resolve_git_ref
from lib.release_baseline import resolve_baseline_chart_state


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

# The exact bare placeholder line each stub below writes for a section
# that has no real content yet — shared with insert_changes_section/
# insert_values_delta_section's own "is this JUST the stub, nothing else"
# check (_is_bare_placeholder_span/_is_bare_values_deltas_todo_stub) so
# these can never independently drift out of sync with what's actually
# written. UPGRADE_INTRO_STUB_TODO_LINE and UPGRADE_CHANGES_STUB_TODO_
# LINE are two SEPARATE placeholders in two different spots of the same
# "upgrade" doc, but treated as ONE event by strip_stale_upgrade_
# placeholders below: both clear together the moment "## Changes" gets
# its first real "### ..." block, since both equally mean "this hop now
# has real recorded changes" — see that function's own docstring.
UPGRADE_INTRO_STUB_TODO_LINE = "TODO: describe this hop's changes.\n"
UPGRADE_CHANGES_STUB_TODO_LINE = "TODO\n"
VALUES_DELTAS_STUB_TODO_LINE = "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
# gemeente-specific.md's own placeholder is worded differently (an
# ongoing "nothing to report" fact, not a TODO instruction) and,
# structurally, NOTHING ever writes a new "## <gemeente> (<env>)"
# section into this file automatically — its content is entirely
# human-authored findings, so there's no insertion-time or retroactive
# STRIP for this one, only a checker (see has_stale_gemeente_specific_
# placeholder) that flags it as a finding for a human to clear by hand.
GEMEENTE_SPECIFIC_STUB_LINE = "_None recorded yet._\n"

STUB_TEMPLATES = {
    "upgrade": (
        "# Upgrade guide: PodiumD {upgrade_docs_baseline} → {target}\n\n"
        "> See the Confluence Releases page for the agreed application\n"
        "> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.\n\n"
        + UPGRADE_INTRO_STUB_TODO_LINE
        + "\n"
        "## Component versions ({target} vs {upgrade_docs_baseline})\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n" + UPGRADE_CHANGES_STUB_TODO_LINE
    ),
    "gemeente-specific": (
        "# Gemeente-specific notes — PodiumD {upgrade_docs_baseline} → {target}\n\n"
        "Findings for this hop that apply to a **specific gemeente or environment** —\n"
        "not to the release in general — are collected here: data quirks, local\n"
        "overrides, hosting particulars, incident follow-ups.\n\n" + GEMEENTE_SPECIFIC_STUB_LINE + "\n"
        "<!-- Add entries per gemeente/environment:\n\n"
        "## <gemeente> (<env>)\n\n"
        "- What was hit, why it is specific to this environment, and the\n"
        "  fix/workaround applied.\n"
        "-->\n"
    ),
    "values-deltas": (
        "# Values deltas — PodiumD {upgrade_docs_baseline} → {target}\n\n" + VALUES_DELTAS_STUB_TODO_LINE
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
            path.write_text(
                STUB_TEMPLATES[suffix].format(upgrade_docs_baseline=upgrade_docs_baseline, target=target),
                encoding="utf-8",
            )
            created.append(path.name)
    images_path = images_manifest_path(images_dir, target)
    if not images_path.is_file():
        images_path.write_text(
            IMAGES_STUB_TEMPLATE.format(upgrade_docs_baseline=upgrade_docs_baseline, target=target), encoding="utf-8"
        )
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
    meaningful.

    Deliberately NOT built on lib.release_baseline.resolve_baseline_chart_
    state (unlike load_baseline_state just below, which shares its own
    exact "also needs Chart.yaml" shape with it) — that function treats an
    unreadable Chart.yaml at the resolved ref as a hard failure (matching
    lib.docs_consistency's own convention), but THIS function has always
    been values.yaml-only and never required Chart.yaml to exist at all
    (real test fixture, tests/update-component-version's own load_
    baseline_values tests: a repo with values.yaml committed but no
    Chart.yaml at all still resolves here). Wrapping it around the shared
    function anyway would silently start requiring Chart.yaml too — a real
    behavior regression this docstring exists to head off, not an
    oversight."""
    repo_root = find_repo_root(values_path.parent)
    if repo_root is None:
        return None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(upgrade_docs_baseline))
    if ref is None:
        return None
    rel_values_path = values_path.relative_to(repo_root)
    return git_show_yaml(repo_root, ref, str(rel_values_path))


def load_baseline_state(
    # kept for signature compat, see docstring below
    chart_yaml_path,  # pylint: disable=unused-argument
    values_path,
    upgrade_docs_baseline,
):
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
    resolved (e.g. that release hasn't been tagged yet), OR if Chart.yaml
    can't be read at the ref that WAS resolved — callers then fall back to
    their own before-this-run comparison instead.

    A thin wrapper around lib.release_baseline.resolve_baseline_chart_state
    (see its own docstring) — chart_yaml_path is accepted only to keep this
    function's own existing signature (and its callers) unchanged; the
    shared function derives Chart.yaml's own path from chart_dir (=
    values_path.parent) directly, since the two always sit side by side in
    the same directory. Translates that function's own "always []/{}/[]
    on failure" convention into this function's own pre-existing
    "(None, None) on failure" one, so update-component-version/update-
    image-version (this function's own callers, which check `is None`)
    need no changes of their own."""
    _ref, baseline_deps, baseline_values, _lines, error = resolve_baseline_chart_state(
        values_path.parent, upgrade_docs_baseline
    )
    return (None, None) if error else (baseline_deps, baseline_values)
