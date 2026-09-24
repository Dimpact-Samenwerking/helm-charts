"""lib.upgradedoc.consistency_checks -- find_wrong_or_duplicate_dependency_claims
and find_changes_duplicate_identities."""

from types import ModuleType

from lib.chart.chart_yaml import ChartDependency
from lib.upgradedoc.string_and_parsing_basics import VersionRow

KISS_DEPS: list[ChartDependency] = [{"name": "kiss", "version": "1.0.0"}, {"name": "zac", "version": "2.0.0"}]


def test_fuzzy_name_of_exactly_claimed_dependency_is_wrong(libupgradedocconsistency: ModuleType):
    duplicates, wrong_fuzzy = libupgradedocconsistency.find_wrong_or_duplicate_dependency_claims(
        ["KISS", "Kiss Elasticsearch", "ZAC"], KISS_DEPS
    )
    assert duplicates == set()
    assert wrong_fuzzy == {"Kiss Elasticsearch"}


def test_two_exact_names_for_one_dependency_are_both_exact(libupgradedocconsistency: ModuleType):
    """Regression: "KISS" and "Kiss" both exactly claim kiss. A {key: name}
    dict kept only the last one, so "KISS" was wrongly reported as a fuzzy
    claim."""
    duplicates, wrong_fuzzy = libupgradedocconsistency.find_wrong_or_duplicate_dependency_claims(
        ["KISS", "Kiss", "Kiss Elasticsearch"], KISS_DEPS
    )
    assert duplicates == set()
    assert wrong_fuzzy == {"Kiss Elasticsearch"}


def test_duplicate_exact_name_still_claims_its_dependency(libupgradedocconsistency: ModuleType):
    """Regression: a duplicated exact name was skipped when collecting exact
    claims, so a fuzzy name for the same dependency was not reported."""
    duplicates, wrong_fuzzy = libupgradedocconsistency.find_wrong_or_duplicate_dependency_claims(
        ["KISS", "KISS", "Kiss Elasticsearch"], KISS_DEPS
    )
    assert duplicates == {"KISS"}
    assert wrong_fuzzy == {"Kiss Elasticsearch"}


def test_fuzzy_name_without_exact_claim_is_not_wrong(libupgradedocconsistency: ModuleType):
    duplicates, wrong_fuzzy = libupgradedocconsistency.find_wrong_or_duplicate_dependency_claims(
        ["Kiss Elasticsearch"], KISS_DEPS
    )
    assert duplicates == set()
    assert wrong_fuzzy == set()


def _row(name: str) -> VersionRow:
    return {"name": name, "app_source": None, "app": None, "chart_source": None, "chart": None}


def test_two_differently_worded_rows_for_one_component_are_duplicates(libupgradedocconsistency: ModuleType):
    rows, headings = libupgradedocconsistency.find_changes_duplicate_identities(
        [_row("KISS"), _row("ZAC"), _row("Kiss")], ["KISS 3.0.0 → 3.1.0", "ZAC 2.0.0"], KISS_DEPS, {}
    )
    assert rows == [("KISS", "Kiss")]
    assert headings == []


def test_two_differently_worded_headings_for_one_component_are_duplicates(libupgradedocconsistency: ModuleType):
    rows, headings = libupgradedocconsistency.find_changes_duplicate_identities(
        [_row("KISS")],
        ["KISS 3.0.0 → 3.1.0", "kiss 3.0.0 → 3.1.0 (chart 1 → 2)"],
        KISS_DEPS,
        {},
    )
    assert rows == []
    assert headings == [("KISS 3.0.0 → 3.1.0", "kiss 3.0.0 → 3.1.0 (chart 1 → 2)")]


def test_one_row_and_one_heading_per_component_are_not_duplicates(libupgradedocconsistency: ModuleType):
    rows, headings = libupgradedocconsistency.find_changes_duplicate_identities(
        [_row("KISS"), _row("ZAC")], ["KISS 3.0.0 → 3.1.0", "ZAC 2.0.0"], KISS_DEPS, {}
    )
    assert rows == []
    assert headings == []


def test_multi_component_heading_is_not_counted_as_a_duplicate(libupgradedocconsistency: ModuleType):
    """A heading naming two components credits neither (already reported
    by find_changes_row_correspondence_gaps), so it never makes the
    single-component heading beside it a duplicate."""
    _, headings = libupgradedocconsistency.find_changes_duplicate_identities(
        [_row("KISS"), _row("ZAC")], ["KISS 3.1.0", "KISS 3.1.0 + ZAC 2.0.0"], KISS_DEPS, {}
    )
    assert headings == []
