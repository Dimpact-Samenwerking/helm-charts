"""charts/podiumd/scripts/migrate-objecten-kiss-logboek-permission-4.10.1.py: KISS's logboek token reads the Activiteitenlog."""

from collections.abc import Callable
from types import ModuleType

import pytest

LOG_TYPE = "REP_ITA_ACTIVITEITENLOG_UUID_REP"
CONTACT_PLACEHOLDER = "REP_OBJECTEN_CREDENTIALS_CONTACT_TOKEN_REP"
KISS = (
    "kiss:\n  settings:\n    logboek:\n"
    f"      objectTypeUrl: https://objecten.example.nl/api/v2/objecttypes/{LOG_TYPE}\n"
    f'      token: "{CONTACT_PLACEHOLDER}"\n'
)
OBJECTTYPES = f'      objecttypes:\n        items:\n          - uuid: "{LOG_TYPE}"\n'
PREFIX = "objecten:\n  configuration:\n    data: |\n" + OBJECTTYPES + "      tokenauth:\n        items:\n"
CONTACT = [
    "- identifier: contact",
    f'  token: "{CONTACT_PLACEHOLDER}"',
    "  permissions:",
    '    - object_type: "REP_CONTACT_AFDELING_UUID_REP"',
    "      mode: read_and_write",
]
PERMISSION = [f'    - object_type: "{LOG_TYPE}"', "      mode: read_only"]
ADDED = f"tokenauth.items[0] (contact): added read_only on {LOG_TYPE}"


@pytest.fixture(scope="module")
def kiss(script: Callable[[str], ModuleType]) -> ModuleType:
    return script("migrate-objecten-kiss-logboek-permission-4.10.1.py")


def values(*lines: str, kiss_block: str = KISS) -> str:
    """A podiumd.yml with `kiss_block` and objecten tokenauth items holding `lines`."""
    return kiss_block + PREFIX + "".join(f"          {line}\n" for line in lines)


def test_the_item_with_the_logboek_token_gets_read_only(kiss: ModuleType):
    new, notes = kiss.migrate_text(values(*CONTACT, "  # trailing comment", "- identifier: ita", "  token: ita-token"))

    # The comment is left of the permission keys, so it belongs to what follows.
    assert new == values(*CONTACT, *PERMISSION, "  # trailing comment", "- identifier: ita", "  token: ita-token")
    assert notes == [ADDED]


def test_a_second_run_changes_nothing(kiss: ModuleType):
    new, _ = kiss.migrate_text(values(*CONTACT))
    assert kiss.migrate_text(new) == (new, [])


@pytest.mark.parametrize(
    "extra",
    [[f'    - object_type: "{LOG_TYPE}"', "      mode: read_and_write"], ["  is_superuser: true"]],
)
def test_an_item_with_the_permission_or_superuser_stays_unchanged(kiss: ModuleType, extra: list[str]):
    text = values(*CONTACT, *extra)
    assert kiss.migrate_text(text) == (text, [])


def test_an_item_without_permissions_gets_a_check_note(kiss: ModuleType):
    text = values(*CONTACT[:2])

    new, notes = kiss.migrate_text(text)

    assert new == text
    assert notes == ["CHECK tokenauth.items[0] (contact) has KISS's logboek token but no permissions: left unchanged"]


def test_a_token_that_matches_no_item_gets_a_check_note(kiss: ModuleType):
    text = values(*CONTACT, kiss_block=KISS.replace(CONTACT_PLACEHOLDER, "REP_OTHER_TOKEN_REP"))

    new, notes = kiss.migrate_text(text)

    assert new == text
    assert len(notes) == 1
    assert notes[0].startswith("CHECK no tokenauth item has kiss.settings.logboek.token")


@pytest.mark.parametrize(
    "kiss_block", ["kiss:\n  settings:\n    logboek:\n      token: ''\n", "kiss:\n  enabled: true\n"]
)
def test_an_empty_logboek_setting_gets_a_check_note(kiss: ModuleType, kiss_block: str):
    text = values(*CONTACT, kiss_block=kiss_block)

    new, notes = kiss.migrate_text(text)

    assert new == text
    assert len(notes) == 1
    assert notes[0].startswith("CHECK kiss.settings.logboek.token or .objectTypeUrl is empty")


@pytest.mark.parametrize("kiss_block", ["", "kiss:\n  enabled: false\n"])
def test_without_kiss_nothing_is_reported(kiss: ModuleType, kiss_block: str):
    text = values(*CONTACT, kiss_block=kiss_block)
    assert kiss.migrate_text(text) == (text, [])


DISABLED = KISS.replace("kiss:\n", "kiss:\n  enabled: false\n", 1)


def test_kiss_disabled_reports_a_missing_permission_without_editing(kiss: ModuleType):
    text = values(*CONTACT, kiss_block=DISABLED)

    new, notes = kiss.migrate_text(text)

    assert new == text
    note = (
        "CHECK kiss.enabled is false in this file, but tokenauth.items[0] (contact) has KISS's logboek token "
        f"without read_only on {LOG_TYPE}: where KISS is enabled (an overlay), add it there or by hand; "
        "left unchanged"
    )
    assert notes == [note]


@pytest.mark.parametrize(
    "lines",
    [
        [*CONTACT, *PERMISSION],
        [*CONTACT[:2], "  is_superuser: true"],
        [CONTACT[0], '  token: "REP_OTHER_TOKEN_REP"', *CONTACT[2:]],
    ],
)
def test_kiss_disabled_is_silent_when_no_matching_item_lacks_the_permission(kiss: ModuleType, lines: list[str]):
    text = values(*lines, kiss_block=DISABLED)
    assert kiss.migrate_text(text) == (text, [])


def test_without_the_object_type_in_objecttypes_nothing_changes(kiss: ModuleType):
    text = values(*CONTACT).replace(OBJECTTYPES, "")

    new, notes = kiss.migrate_text(text)

    assert new == text
    assert len(notes) == 1
    assert notes[0].startswith("CHECK objecttypes.items does not create Activiteitenlog")


def test_a_flow_sequence_of_permissions_is_an_error(kiss: ModuleType, common: ModuleType):
    text = values(*CONTACT[:2], "  permissions: [{object_type: other, mode: read_only}]")

    with pytest.raises(common.MigrationError, match="flow sequence"):
        kiss.migrate_text(text)
