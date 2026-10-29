"""The standard per-target doc set (upgrade/gemeente-specific/values-deltas
+ images manifest): stub scaffolding, scanning existing docs, and loading
values.yaml/Chart.yaml at the upgrade_docs_baseline. Shared by
create-doc-version and fix-doc-consistency."""

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.release_baseline import resolve_baseline_chart_state
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.doc_names import doc_name_re
from lib.upgradedoc.doc_names import images_manifest_path
from lib.upgradedoc.sorting_and_ordering import CHANGES_HEADING
from lib.upgradedoc.string_and_parsing_basics import heading_slug
from lib.yaml_types import YamlMapping

# Bare placeholder lines the stubs write; shared with the "is this just the
# stub" checks so they can't drift. Both upgrade-doc placeholders are cleared
# together by strip_stale_upgrade_placeholders once "## Changes" gets a
# real "### ..." block.
UPGRADE_INTRO_STUB_TODO_LINE = "TODO: describe this hop's changes.\n"
UPGRADE_CHANGES_STUB_TODO_LINE = "TODO\n"
VALUES_DELTAS_STUB_TODO_LINE = "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
# Nothing writes gemeente-specific sections automatically, so this placeholder
# is never stripped; has_stale_gemeente_specific_placeholder flags it instead.
GEMEENTE_SPECIFIC_STUB_LINE = "_None recorded yet._\n"

# The upgrade guide's runbook sections, in the order of
# docs/_UPGRADE_DOCS_CHECKLIST.md.
RUNBOOK_SECTIONS = (
    "A. Once per cluster",
    "B. Once per values repository",
    "C. Per environment, before the deploy day",
    "D. The deploy run",
    "E. After the deploy",
    "F. Rollback",
)
DEPLOY_RUN_SECTION = RUNBOOK_SECTIONS[3]
IF_THE_RUN_FAILS_SECTION = "If the run fails"
# All its "##" sections up to "## Changes", in that order, as the
# upgrade-doc-layout check expects them; a heading may add to the name
# ("A. Once per cluster: CRDs").
UPGRADE_GUIDE_SECTIONS = (
    "Checklist",
    *RUNBOOK_SECTIONS,
    "Changes that need no action",
    "Component versions",
    CHANGES_HEADING.removeprefix("## "),
)
# What an empty section says; an author keeps it when it is true for the hop.
EMPTY_SECTION_LINE = "Nothing for this hop.\n"

# (Checklist half-line, section body) per runbook section. Every section
# starts empty, but D always runs `helm upgrade`.
_EMPTY_RUNBOOK_STUB = ("nothing for this hop.", EMPTY_SECTION_LINE)
_RUNBOOK_STUBS = {
    DEPLOY_RUN_SECTION: (
        "`helm upgrade`.",
        f"### D1. `helm upgrade`\n\nRun the deploy as usual.\n\n### {IF_THE_RUN_FAILS_SECTION}\n\n{EMPTY_SECTION_LINE}",
    ),
}


def _upgrade_stub_template() -> str:
    """The upgrade-guide stub in the checklist layout, with {upgrade_docs_baseline} and {target} fields."""
    stubs = [(name, *_RUNBOOK_STUBS.get(name, _EMPTY_RUNBOOK_STUB)) for name in RUNBOOK_SECTIONS]
    checklist = "".join(f"- [ ] **[{name}](#{heading_slug(name)})**: {line}\n" for name, line, _body in stubs)
    runbook = "".join(f"## {name}\n\n{body}\n" for name, _line, body in stubs)
    companion = "{upgrade_docs_baseline}-to-{target}"
    return (
        "# Upgrade guide: PodiumD {upgrade_docs_baseline} → {target}\n\n"
        "> See the Confluence Releases page for the agreed application\n"
        "> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.\n\n"
        "For environments already on **{upgrade_docs_baseline}**. The guide has three parts:\n\n"
        "1. **The runbook** (sections A to F): what to run, in which order, and what\n"
        "   to check. Written for the deploy pipeline.\n"
        "2. **Component versions and changes**: the record of what moved in the chart.\n"
        "3. **Reference**: the detail per topic, for when a step fails or a choice has\n"
        "   to be made.\n\n" + UPGRADE_INTRO_STUB_TODO_LINE + "\n"
        "Companion documents:\n\n"
        f"- [`{companion}-values-deltas.md`]({companion}-values-deltas.md):\n"
        "  the exact changes in a gemeente `podiumd.yml`, `services-gateway.yml` and\n"
        "  `ssl-gateway.yml`.\n"
        f"- [`{companion}-gemeente-specific.md`]({companion}-gemeente-specific.md):\n"
        "  findings per environment.\n\n"
        "## Checklist\n\n"
        "A and B are done once; C, D and E per environment.\n\n"
        f"{checklist}\n"
        f"{runbook}"
        f"## Changes that need no action\n\n{EMPTY_SECTION_LINE}\n"
        "## Component versions ({target} vs {upgrade_docs_baseline})\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        f"{CHANGES_HEADING}\n\n{UPGRADE_CHANGES_STUB_TODO_LINE}\n"
        f"## Reference\n\n{EMPTY_SECTION_LINE}"
    )


STUB_TEMPLATES = {
    "upgrade": _upgrade_stub_template(),
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
    # Config only: the opening, then one "##" section per component or
    # gateway file, which the tooling and the author add.
    "values-deltas": (
        "# Values deltas — PodiumD {upgrade_docs_baseline} → {target}\n\n"
        "What changes in a gemeente `podiumd.yml`, `services-gateway.yml` and\n"
        "`ssl-gateway.yml` for this hop, and nothing else. Why, the pre- and\n"
        "post-deploy steps and the rollback are in\n"
        "[`{upgrade_docs_baseline}-to-{target}-upgrade.md`]({upgrade_docs_baseline}-to-{target}-upgrade.md).\n\n"
        + VALUES_DELTAS_STUB_TODO_LINE
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


def existing_doc_baselines(doc_dir: Path, target: str) -> dict[str, list[tuple[str, Path]]]:
    """{suffix: [(upgrade_docs_baseline, path), ...]} for every *-to-<target>-<suffix>.md in doc_dir."""
    pattern = doc_name_re(target)
    by_suffix: dict[str, list[tuple[str, Path]]] = {}
    for path in doc_dir.glob(f"*-to-{target}-*.md"):
        m = pattern.fullmatch(path.name)
        if not m:
            continue
        by_suffix.setdefault(m.group("suffix"), []).append((m.group("baseline"), path))
    return by_suffix


def create_missing_docs(doc_dir: Path, images_dir: Path, upgrade_docs_baseline: str, target: str) -> list[str]:
    """Create missing standard docs and images-<target>.yaml as TODO stubs; never overwrites.

    Returns the created filenames (doc suffix order, images manifest last)."""
    created: list[str] = []
    for suffix in STANDARD_SUFFIXES:
        path = doc_dir / doc_name(upgrade_docs_baseline, target, suffix)
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


def load_baseline_state(
    # kept for signature compat
    chart_yaml_path: Path,  # pylint: disable=unused-argument  # noqa: ARG001
    values_path: Path,
    upgrade_docs_baseline: str,
) -> tuple[list[ChartDependency], YamlMapping] | tuple[None, None]:
    """(baseline_deps, baseline_values) at the upgrade_docs_baseline's git ref.

    Includes Chart.yaml so callers can detect chart version moves, letting a
    component bumped twice in one cycle still document baseline -> final.
    Returns (None, None) if the ref or Chart.yaml can't be resolved; callers
    then fall back to their own before/after comparison. chart_yaml_path is
    unused (derived from values_path.parent)."""
    _ref, baseline_deps, baseline_values, _lines, error = resolve_baseline_chart_state(
        values_path.parent, upgrade_docs_baseline
    )
    return (None, None) if error else (baseline_deps, baseline_values)
