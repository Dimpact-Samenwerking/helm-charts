"""check_upgrade_doc_layout: the target version's upgrade docs against docs/_UPGRADE_DOCS_CHECKLIST.md."""

from pathlib import Path

import pytest

from lib.checks.upgrade_doc_layout import check_upgrade_doc_layout
from lib.checks.upgrade_doc_layout import upgrade_guide_layout_issues
from lib.checks.upgrade_doc_layout import values_deltas_layout_issues
from lib.component_docs.baseline_doc_stubs import STUB_TEMPLATES

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
        f'{GUIDE}: the opening does not say which version it starts from ("For environments already on **4.9.5**.")',
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


def test_check_passes_on_the_stubs_and_ignores_released_guides(chart_dir: Path, capsys: pytest.CaptureFixture[str]):
    _write(chart_dir, GUIDE, _stub("upgrade"))
    _write(chart_dir, DELTAS, _stub("values-deltas"))
    _write(chart_dir, "4.9.4-to-4.9.5-upgrade.md", "# Upgrade guide: PodiumD 4.9.4 → 4.9.5\n\n## Changes\n")
    assert check_upgrade_doc_layout(chart_dir) == (True, f"layout of {GUIDE}, {DELTAS} OK")
    assert "4.9.4-to-4.9.5" not in capsys.readouterr().out


def test_check_fails_and_prints_each_issue(chart_dir: Path, capsys: pytest.CaptureFixture[str]):
    _write(chart_dir, GUIDE, _stub("upgrade").replace("## F. Rollback\n\nNothing for this hop.\n\n", ""))
    _write(chart_dir, DELTAS, _stub("values-deltas") + "\n## Background\n\nText.\n")
    assert check_upgrade_doc_layout(chart_dir) == (False, "2 layout issue(s)")
    out = capsys.readouterr().out
    assert "2 layout issue(s); the layout is in docs/_UPGRADE_DOCS_CHECKLIST.md:" in out
    assert f'{GUIDE}: missing "## F. Rollback" after "## E. After the deploy"' in out
    assert f'{DELTAS}: "## Background" is neither' in out


def test_check_skips_without_docs_or_bare_baseline(chart_dir: Path):
    assert check_upgrade_doc_layout(chart_dir) == (True, "no matching docs found — skipped")
    (chart_dir / "etc" / "release-baseline.yaml").write_text('upgrade_docs: "main"\n', encoding="utf-8")
    assert check_upgrade_doc_layout(chart_dir) == (True, "no bare upgrade_docs baseline — skipped")
