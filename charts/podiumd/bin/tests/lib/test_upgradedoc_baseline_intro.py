"""lib.upgradedoc.baseline_intro -- the "environments already on **<version>**" intro sentence."""

from lib.upgradedoc.baseline_intro import baseline_intro_mismatches
from lib.upgradedoc.baseline_intro import fix_baseline_intro

INTRO = "This is the upgrade guide for environments already on **4.9.1**.\n"


def test_fix_points_a_stale_intro_at_the_baseline():
    assert fix_baseline_intro(INTRO, "4.9.3") == (
        "This is the upgrade guide for environments already on **4.9.3**.\n",
        True,
    )


def test_fix_keeps_text_after_the_version():
    text = "environments already on **4.8.1** (the current\nrelease).\n"
    assert fix_baseline_intro(text, "4.8.2") == ("environments already on **4.8.2** (the current\nrelease).\n", True)


def test_fix_leaves_a_current_intro_unchanged():
    assert fix_baseline_intro(INTRO, "4.9.1") == (INTRO, False)


def test_fix_rewrites_only_the_first_match():
    later = "Gemeente X was environments already on **4.8.0** before.\n"
    new_text, changed = fix_baseline_intro(INTRO + later, "4.9.3")
    assert changed
    assert new_text.endswith(later)


def test_fix_leaves_a_doc_without_intro_unchanged():
    assert fix_baseline_intro("# Title\n\nTODO\n", "4.9.3") == ("# Title\n\nTODO\n", False)


def test_mismatch_names_both_versions():
    assert baseline_intro_mismatches("x-upgrade.md", INTRO, "4.9.3") == [
        "x-upgrade.md intro names baseline **4.9.1**, not **4.9.3**"
    ]


def test_no_mismatch_for_a_current_or_missing_intro():
    assert baseline_intro_mismatches("x-upgrade.md", INTRO, "4.9.1") == []
    assert baseline_intro_mismatches("x-upgrade.md", "# Title\n", "4.9.3") == []
