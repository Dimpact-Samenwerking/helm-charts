"""lib.upgradedoc.consistency_checks -- find_wrong_or_duplicate_dependency_claims."""

from types import ModuleType

from lib.chart.chart_yaml import ChartDependency

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
