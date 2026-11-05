"""charts/podiumd/scripts/migrate-objecten-openarchiefbeheer-permissions-4.10.1.py: OAB's token gets read_and_write."""

from collections.abc import Callable
from types import ModuleType

import pytest

OBJECTTYPES = '      objecttypes:\n        items:\n          - uuid: "REP_ZAC_PRODUCTAANVRAAG_UUID_REP"\n'
PREFIX = "objecten:\n  configuration:\n    data: |\n" + OBJECTTYPES + "      tokenauth:\n        items:\n"
OAB = ["- identifier: openarchiefbeheer", '  token: "REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"']
PERMISSION = ["  permissions:", '    - object_type: "REP_ZAC_PRODUCTAANVRAAG_UUID_REP"', "      mode: read_and_write"]
ADDED = "tokenauth.items[0] (openarchiefbeheer): added read_and_write on REP_ZAC_PRODUCTAANVRAAG_UUID_REP"


@pytest.fixture(scope="module")
def oab(script: Callable[[str], ModuleType]) -> ModuleType:
    return script("migrate-objecten-openarchiefbeheer-permissions-4.10.1.py")


def items(*lines: str) -> str:
    """A podiumd.yml whose objecten tokenauth items hold `lines`."""
    return PREFIX + "".join(f"          {line}\n" for line in lines)


def test_an_item_without_permissions_gets_the_permission(oab: ModuleType):
    new, notes = oab.migrate_text(items(*OAB, "- identifier: zac", "  token: zac-token"))

    assert new == items(*OAB, *PERMISSION, "- identifier: zac", "  token: zac-token")
    assert notes == [ADDED]


def test_a_second_run_changes_nothing(oab: ModuleType):
    new, _ = oab.migrate_text(items(*OAB))
    assert oab.migrate_text(new) == (new, [])


@pytest.mark.parametrize("extra", [PERMISSION, ["  is_superuser: true"]])
def test_an_item_with_permissions_or_superuser_stays_unchanged(oab: ModuleType, extra: list[str]):
    text = items(*OAB, *extra)
    assert oab.migrate_text(text) == (text, [])


def test_permissions_without_productaanvraag_read_and_write_get_a_check_note(oab: ModuleType):
    text = items(*OAB, "  permissions:", "    - object_type: other-type", "      mode: read_only")

    new, notes = oab.migrate_text(text)

    assert new == text
    assert len(notes) == 1
    assert notes[0].startswith("CHECK tokenauth.items[0] (openarchiefbeheer) has permissions without read_and_write")


def test_a_file_without_the_item_changes_nothing(oab: ModuleType):
    text = items("- identifier: zac", "  token: zac-token")
    assert oab.migrate_text(text) == (text, [])


@pytest.mark.parametrize(
    "objecttype",
    [
        "{value_from: {env: zac_productaanvraag_uuid}}\n            name: Productaanvraag-Dimpact",
        '"REP_ZAC_PRODUCTAANVRAAG_UUID_REP"',
    ],
)
def test_the_object_type_is_found_by_name_or_uuid(oab: ModuleType, objecttype: str):
    text = items(*OAB).replace('"REP_ZAC_PRODUCTAANVRAAG_UUID_REP"\n', objecttype + "\n", 1)
    assert oab.migrate_text(text)[1] == [ADDED]


def test_without_the_object_type_in_objecttypes_nothing_changes(oab: ModuleType):
    text = items(*OAB).replace(OBJECTTYPES, "")

    new, notes = oab.migrate_text(text)

    assert new == text
    assert len(notes) == 1
    assert notes[0].startswith("CHECK objecttypes.items does not create Productaanvraag-Dimpact")
