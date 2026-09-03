"""lib.docs_consistency — match_changes_item_to_entry: matches a plain
(non-component) "# Changes:" item to its images-manifest entry by
basename, used when match_dependency_excluding_sidecar_names already
ruled out a real Chart.yaml dependency."""


# --- match_changes_item_to_entry ---

def test_match_changes_item_to_entry_canonical_sidecar_name_matches_own_basename(libdocsconsistency):
    """A canonical "<key> - <basename>" sidecar name (see
    lib.chart.canonical_sidecar_row_names) is matched on its OWN
    basename only, not the whole string — real collision: "keycloak-
    operator - postgres" (the postgres image bundled with the keycloak-
    operator dependency) must match the "postgres" entry, not the
    unrelated "keycloak" entry its leading word happens to fuzzy-match
    equally well on a same-length word."""
    keycloak_entry = {"name": "keycloak/keycloak", "version": "26.7.2"}
    postgres_entry = {"name": "postgres", "version": "16.15"}

    match = libdocsconsistency.match_changes_item_to_entry(
        "keycloak-operator - postgres", [keycloak_entry, postgres_entry])

    assert match is postgres_entry


def test_match_changes_item_to_entry_plain_name_matches_by_basename(libdocsconsistency):
    """No " - " delimiter: falls back to matching the whole item name
    against entry basenames, unchanged from before the fix above."""
    entry = {"name": "library/python", "version": "3.14.7-slim"}

    match = libdocsconsistency.match_changes_item_to_entry("python", [entry])

    assert match is entry


def test_match_changes_item_to_entry_no_match_returns_none(libdocsconsistency):
    entries = [{"name": "postgres", "version": "16.15"}]

    match = libdocsconsistency.match_changes_item_to_entry("gotenberg", entries)

    assert match is None
