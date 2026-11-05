"""check_upgrade_doc_layout: the target version's upgrade docs against docs/_UPGRADE_DOCS_CHECKLIST.md."""

import subprocess

from pathlib import Path

import pytest

import lib.component_docs.changes_section as changes_section

from lib.checks.upgrade_doc_layout import check_upgrade_doc_layout
from lib.checks.upgrade_doc_layout import upgrade_guide_layout_issues
from lib.checks.upgrade_doc_layout import values_deltas_layout_issues
from lib.component_docs.baseline_doc_stubs import STUB_TEMPLATES
from lib.upgradedoc.sorting_and_ordering import OrderingContext

GUIDE = "4.9.5-to-4.10.0-upgrade.md"
DELTAS = "4.9.5-to-4.10.0-values-deltas.md"


def _stub(suffix: str) -> str:
    return STUB_TEMPLATES[suffix].format(upgrade_docs_baseline="4.9.5", target="4.10.0")


def _guide_issues(text: str) -> list[str]:
    return upgrade_guide_layout_issues(GUIDE, text, "4.9.5", "4.10.0")


# --- upgrade guide ---


def test_headings_may_add_to_the_section_name_and_reference_sections_follow_changes():
    text = (
        _stub("upgrade")
        .replace("## A. Once per cluster\n", "## A. Once per cluster: CRDs\n")
        .replace("(#a-once-per-cluster)", "(#a-once-per-cluster-crds)")
        .replace("## Reference\n", "## Reference: Objecten 4\n\nText.\n\n## Security headers at the edge (IN-3162)\n")
    )
    assert _guide_issues(text) == []


def test_missing_section_is_named_with_its_predecessor():
    text = _stub("upgrade").replace("## B. Once per values repository\n\nNothing for this hop.\n\n", "")
    assert _guide_issues(text) == [
        f'{GUIDE}: missing "## B. Once per values repository" after "## A. Once per cluster"'
    ]


def test_misordered_section_is_named():
    text = _stub("upgrade")
    f_section = "## F. Rollback\n\nNothing for this hop.\n\n"
    text = text.replace(f_section, "").replace("## E. After the deploy\n", f_section + "## E. After the deploy\n")
    issues = _guide_issues(text)
    assert len(issues) == 1
    assert issues[0].startswith(
        f'{GUIDE}: "## E. After the deploy" comes after "## F. Rollback"; the order is "## Checklist"'
    )


def test_unknown_section_before_changes_is_flagged_but_changes_that_need_no_action_is_not_changes():
    text = _stub("upgrade").replace(
        "## Changes that need no action\n", "## Notes\n\nText.\n\n## Changes that need no action\n"
    )
    assert _guide_issues(text) == [
        (
            f'{GUIDE}: "## Notes" is not a section of the layout; move it under one of A to F, '
            'or after "## Changes" as a reference section'
        )
    ]


def test_duplicate_section_is_flagged():
    text = _stub("upgrade").replace("## F. Rollback\n", "## E. After the deploy\n\nMore.\n\n## F. Rollback\n")
    assert _guide_issues(text) == [f'{GUIDE}: "## E. After the deploy" appears twice']


def test_deploy_run_needs_if_the_run_fails():
    text = _stub("upgrade").replace("### If the run fails\n", "### D2. Check\n")
    assert _guide_issues(text) == [f'{GUIDE}: "## D. The deploy run" has no "### If the run fails" section']


def test_if_the_run_fails_under_another_section_does_not_count():
    text = (
        _stub("upgrade")
        .replace("### If the run fails\n", "### D2. Check\n")
        .replace("## E. After the deploy\n\n", "## E. After the deploy\n\n### If the run fails\n\nText.\n\n")
    )
    assert _guide_issues(text) == [f'{GUIDE}: "## D. The deploy run" has no "### If the run fails" section']


def test_checklist_must_link_each_runbook_section():
    text = _stub("upgrade").replace("[F. Rollback](#f-rollback)", "F. Rollback")
    assert _guide_issues(text) == [f'{GUIDE}: the Checklist does not link "## F. Rollback" (#f-rollback)']


def test_opening_names_the_baseline_and_links_the_values_deltas():
    text = (
        _stub("upgrade")
        .replace("For environments already on **4.9.5**.", "For everyone.")
        .replace(f"]({DELTAS})", "](elsewhere.md)")
    )
    assert _guide_issues(text) == [
        f'{GUIDE}: the opening does not say which version it starts from ("For environments already on **4.9.5**."; doc-consistency checks the version)',
        f"{GUIDE}: the opening does not link the companion {DELTAS}",
    ]


def test_headings_inside_fenced_blocks_are_not_sections():
    text = _stub("upgrade").replace("Run the deploy as usual.\n", "```bash\n## not a heading\n```\n")
    assert _guide_issues(text) == []


def test_old_layout_guide_lists_every_missing_section():
    text = (
        "# Upgrade guide: PodiumD 4.9.5 → 4.10.0\n\nFor environments already on **4.9.5**. "
        f"See [`{DELTAS}`]({DELTAS}).\n\n## Component versions (4.10.0 vs 4.9.5)\n\n## Changes\n"
    )
    issues = _guide_issues(text)
    assert len(issues) == 8
    assert issues[0] == f'{GUIDE}: missing "## Checklist"'
    # "after" names a section that is there, never one that is missing too.
    assert issues[1] == f'{GUIDE}: missing "## A. Once per cluster"'
    assert issues[-1] == f'{GUIDE}: missing "## Changes that need no action"'


def test_changes_with_a_suffix_is_not_the_changes_section_for_the_writer_or_the_check():
    """Regression (#670 review): "## Changes: notes" made insert_changes_section add a second "## Changes"."""
    text = _stub("upgrade").replace("## Changes\n", "## Changes: notes\n")

    def unknown(heading: str) -> str:
        return (
            f'{GUIDE}: "## {heading}" is not a section of the layout; move it under one of A to F, '
            'or after "## Changes" as a reference section'
        )

    assert _guide_issues(text) == [
        unknown("Changes: notes"),
        unknown("Reference"),
        f'{GUIDE}: missing "## Changes" after "## Component versions (4.10.0 vs 4.9.5)"',
    ]
    # The writer appends its own "## Changes" at the end; the check still reports both headings.
    section = changes_section.render_changes_section("zac 5.0.2 → 5.4.3", [], [], "4.10.0")
    written = changes_section.insert_changes_section(text, section, "zac", OrderingContext([], {}))
    assert written.count("\n## Changes\n") == 1
    assert _guide_issues(written) == [unknown("Changes: notes"), unknown("Reference")]


def test_a_layout_section_after_changes_is_flagged():
    text = _stub("upgrade") + "\n## Changes\n\nAgain.\n\n## F. Rollback: more\n\nText.\n"
    assert _guide_issues(text) == [
        f'{GUIDE}: "## Changes" appears twice',
        f'{GUIDE}: "## F. Rollback: more" appears twice',
    ]


def test_checklist_out_of_order_gives_only_the_order_finding():
    stub = _stub("upgrade")
    checklist = stub[stub.index("## Checklist\n") : stub.index("## A. Once per cluster\n")]
    text = stub.replace(checklist, "").replace("## F. Rollback\n", checklist + "## F. Rollback\n")
    issues = _guide_issues(text)
    assert len(issues) == 1
    assert issues[0].startswith(f'{GUIDE}: "## Checklist" comes after "## E. After the deploy"')


def test_closing_marks_and_exact_if_the_run_fails():
    assert _guide_issues(_stub("upgrade").replace("## Checklist\n", "## Checklist ##\n")) == []
    text = _stub("upgrade").replace("### If the run fails\n", "### If the run fails, read this\n")
    assert _guide_issues(text) == [f'{GUIDE}: "## D. The deploy run" has no "### If the run fails" section']


# --- values-deltas ---


def test_values_deltas_component_and_gateway_sections_pass():
    text = (
        _stub("values-deltas") + "\n## keycloak 26.7.3 → 26.8.1\n\nOnly where ...:\n\n```yaml\nk: v  # new\n```\n\n"
        "## openinwoner 2.4.7 (unchanged) (chart 2.4.0 → 2.6.0)\n\n### Admin OIDC\n\nText.\n\n"
        "## `ssl-gateway.yml`\n\nEvery environment:\n"
    )
    assert values_deltas_layout_issues(DELTAS, text) == []


def test_values_deltas_hand_written_section_is_flagged():
    text = _stub("values-deltas") + "\n## Background\n\nWhy this changed.\n"
    issues = values_deltas_layout_issues(DELTAS, text)
    assert len(issues) == 1
    assert issues[0].startswith(f'{DELTAS}: "## Background" is neither a component section')


def test_values_deltas_needs_an_opening():
    text = "# Values deltas — PodiumD 4.9.5 → 4.10.0\n\n## zac 5.4.5 → 5.9.1\n\nText.\n"
    assert values_deltas_layout_issues(DELTAS, text) == [
        f"{DELTAS}: no opening before the first section (what the doc covers, a link to the guide)"
    ]


# --- check_upgrade_doc_layout ---


@pytest.fixture
def chart_dir(tmp_path: Path) -> Path:
    (tmp_path / "Chart.yaml").write_text("version: 4.10.0\n", encoding="utf-8")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "4.9.5"\n', encoding="utf-8")
    (tmp_path / "docs" / "_UPGRADE_PATHS").mkdir(parents=True)
    return tmp_path


def _write(chart_dir: Path, name: str, text: str):
    (chart_dir / "docs" / "_UPGRADE_PATHS" / name).write_text(text, encoding="utf-8")


def test_check_covers_a_declared_side_path(chart_dir: Path, capsys: pytest.CaptureFixture[str]):
    (chart_dir / "etc" / "release-baseline.yaml").write_text(
        'upgrade_docs: "4.9.5"\nside_paths: ["4.9.4"]\n', encoding="utf-8"
    )
    _write(chart_dir, GUIDE, _stub("upgrade"))
    _write(chart_dir, "4.9.4-to-4.10.0-upgrade.md", "# Upgrade guide: PodiumD 4.9.4 → 4.10.0\n\n## Changes\n")

    ok, detail = check_upgrade_doc_layout(chart_dir)

    assert ok
    assert "layout issue(s)" in detail
    assert "4.9.4-to-4.10.0-upgrade.md: missing" in capsys.readouterr().out


def test_check_passes_on_the_stubs_and_ignores_released_guides(chart_dir: Path, capsys: pytest.CaptureFixture[str]):
    _write(chart_dir, GUIDE, _stub("upgrade"))
    _write(chart_dir, DELTAS, _stub("values-deltas"))
    _write(chart_dir, "4.9.4-to-4.9.5-upgrade.md", "# Upgrade guide: PodiumD 4.9.4 → 4.9.5\n\n## Changes\n")
    assert check_upgrade_doc_layout(chart_dir) == (True, f"layout of {GUIDE}, {DELTAS} OK")
    assert "4.9.4-to-4.9.5" not in capsys.readouterr().out


def test_check_reports_each_issue_but_never_fails(chart_dir: Path, capsys: pytest.CaptureFixture[str]):
    _write(chart_dir, GUIDE, _stub("upgrade").replace("## F. Rollback\n\nNothing for this hop.\n\n", ""))
    _write(chart_dir, DELTAS, _stub("values-deltas") + "\n## Background\n\nText.\n")
    assert check_upgrade_doc_layout(chart_dir) == (True, "2 layout issue(s) (report-only, not a failure)")
    out = capsys.readouterr().out
    assert "WARNING: no git repository, so whether 4.10.0 is released is unknown — checking its docs anyway" in out
    assert "WARNING: 2 layout issue(s) (report only); the layout is in docs/_UPGRADE_DOCS_CHECKLIST.md:" in out
    assert f'{GUIDE}: missing "## F. Rollback" after "## E. After the deploy"' in out
    assert f'{DELTAS}: "## Background" is neither' in out


def _git(chart_dir: Path, *args: str):
    subprocess.run(["git", "-C", str(chart_dir), *args], check=True, capture_output=True)


def test_check_skips_a_released_target_and_checks_an_unreleased_one(
    chart_dir: Path, capsys: pytest.CaptureFixture[str]
):
    _write(chart_dir, GUIDE, "# Upgrade guide: PodiumD 4.9.5 → 4.10.0\n\n## Changes\n")
    _git(chart_dir, "init", "-q")
    _git(chart_dir, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "x")
    ok, detail = check_upgrade_doc_layout(chart_dir)
    assert ok
    assert detail.endswith("layout issue(s) (report-only, not a failure)")
    assert "no git repository" not in capsys.readouterr().out

    _git(chart_dir, "tag", "podiumd-4.10.0")
    assert check_upgrade_doc_layout(chart_dir) == (True, "4.10.0 is released — skipped")
    assert "podiumd-4.10.0 is tagged" in capsys.readouterr().out


def test_check_skips_without_docs_or_bare_baseline(chart_dir: Path):
    assert check_upgrade_doc_layout(chart_dir) == (True, "no matching docs found — skipped")
    (chart_dir / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "main"\n', encoding="utf-8")
    assert check_upgrade_doc_layout(chart_dir) == (True, "no bare upgrade_docs baseline — skipped")
