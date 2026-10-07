"""covered_display_names: which entries the "# Changes:" list covers, for the writer and the checker alike."""

from lib.component_docs.images_manifest_changes_header import covered_display_names

LINES = [
    "# Changes:\n",
    "#   1. zac 5.4.4 -> 5.4.5.\n",
    "#   2. Renovate-integrated bumps: curl 8.21.0 -> 8.22.0.\n",
    "#   3. keycloak-operator - postgres 16 -> 16.15.\n",
    "\n",
]


def test_an_item_covers_the_display_name_it_starts_with():
    names = ["zac", "curl", "keycloak-operator", "keycloak-operator - postgres"]

    assert covered_display_names(LINES, names) == {"zac", "keycloak-operator - postgres"}


def test_a_name_mentioned_mid_item_is_not_covered():
    """The writer then adds a "curl ..." item, and the checker reports it as missing until then."""
    assert "curl" not in covered_display_names(LINES, ["curl"])


def test_no_header_covers_nothing():
    assert covered_display_names(["- name: infonl/zac\n"], ["zac"]) == set()
