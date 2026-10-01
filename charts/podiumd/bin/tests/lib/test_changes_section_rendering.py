"""Upgrade-doc Changes sections: exact renderer output, shared version text and the pointer check.

Written against the output before they shared a skeleton, so a refactor
must keep it byte-identical, except for the blank line the component
section gained before the "- Image / digest" pointer."""

import pytest

from lib.component_docs.changes_section import ComponentIdentity
from lib.component_docs.changes_section import VersionChange
from lib.component_docs.changes_section import changes_body_kinds
from lib.component_docs.changes_section import edited_changes_lines
from lib.component_docs.changes_section import fix_pointer_issues
from lib.component_docs.changes_section import make_changes_section
from lib.component_docs.changes_section import pointer_issues
from lib.component_docs.changes_section import render_changes_section
from lib.component_docs.changes_section import replace_changes_section
from lib.image.docs import make_image_changes_section
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.version_cells_and_key_changes import pin_version_text
from lib.upgradedoc.version_cells_and_key_changes import version_transition

ZAC = ComponentIdentity("zac", "zaakafhandelcomponent", "zac")
ECK = ComponentIdentity("eck-stack", "eck-stack", "eck-stack")

IMAGE_CASES = [
    pytest.param(
        ("curl", "4.9.3", "8.20.0", "8.22.0", [("global.images.curl.tag", "8.20.0"), ("zac.curl.image.tag", None)]),
        (
            "### curl 8.20.0 → 8.22.0\n"
            "\n"
            "PodiumD 4.9.3 upgrades the **curl** image to 8.22.0,\n"
            "pinned at:\n"
            "\n"
            "- `global.images.curl.tag` `8.20.0` → `8.22.0`\n"
            "- `zac.curl.image.tag` `8.22.0` (new)\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="upgrade",
    ),
    pytest.param(
        ("k8s", "4.9.3", None, "1.37.1", [("redis-operator.redis-ha.cron.image.tag", None)]),
        (
            "### k8s 1.37.1 (new)\n"
            "\n"
            "PodiumD 4.9.3 introduces the **k8s** image at 1.37.1,\n"
            "pinned at:\n"
            "\n"
            "- `redis-operator.redis-ha.cron.image.tag` `1.37.1` (new)\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="new",
    ),
    pytest.param(
        ("nginx", "4.9.3", "1.29", "v1.29", [("openzaak.nginx.image.tag", "1.29")]),
        (
            "### nginx v1.29 (unchanged)\n"
            "\n"
            "PodiumD 4.9.3 keeps the **nginx** image at v1.29,\n"
            "pinned at:\n"
            "\n"
            "- `openzaak.nginx.image.tag` `v1.29` (unchanged)\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="unchanged",
    ),
]

COMPONENT_CASES = [
    pytest.param(
        ZAC,
        VersionChange("5.4.4", "5.4.5", "1.0.297", "1.0.297"),
        ["image"],
        [],
        (
            "### zac 5.4.4 → 5.4.5 (chart 1.0.297, unchanged)\n"
            "\n"
            "PodiumD 4.9.3 upgrades **zac** from app version 5.4.4\n"
            "to 5.4.5.\n"
            "\n"
            "- Image tag pin `zac.image.tag` `5.4.4` → `5.4.5` in\n"
            "  `charts/podiumd/values.yaml`.\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="upgrade",
    ),
    pytest.param(
        ZAC,
        VersionChange(None, "5.4.5", None, "1.0.297"),
        ["image"],
        [],
        (
            "### zac 5.4.5 (new) (chart 1.0.297, new)\n"
            "\n"
            "PodiumD 4.9.3 introduces **zac** at app version 5.4.5.\n"
            "\n"
            "- Image tag pin `zac.image.tag` `5.4.5` (new) in\n"
            "  `charts/podiumd/values.yaml`.\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="new",
    ),
    pytest.param(
        ZAC,
        VersionChange("5.4.5", "5.4.5", "1.0.297", "1.0.310"),
        ["image", "nginx.image"],
        [],
        (
            "### zac 5.4.5 (unchanged) (chart 1.0.297 → 1.0.310)\n"
            "\n"
            "**zac**'s own app version (5.4.5) is unchanged this hop.\n"
            "\n"
            "- Helm chart `zaakafhandelcomponent` `1.0.297` → `1.0.310` in\n"
            "  `charts/podiumd/Chart.yaml`.\n"
            "- Image tag pin `zac.image.tag` `5.4.5` (unchanged) in\n"
            "  `charts/podiumd/values.yaml`.\n"
            "- Image tag pin `zac.nginx.image.tag` `5.4.5` (unchanged) in\n"
            "  `charts/podiumd/values.yaml`.\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="unchanged-app-chart-change",
    ),
    pytest.param(
        ECK,
        VersionChange("8.19.0", "8.19.4", "0.15.0", "-"),
        [],
        ["eck-elasticsearch.version"],
        (
            "### eck-stack 8.19.0 → 8.19.4\n"
            "\n"
            "PodiumD 4.9.3 upgrades **eck-stack** from app version 8.19.0\n"
            "to 8.19.4.\n"
            "\n"
            "- Version pin `eck-stack.eck-elasticsearch.version` `8.19.0` → `8.19.4` in\n"
            "  `charts/podiumd/values.yaml`.\n"
            "\n"
            "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
            "\n"
        ),
        id="native-version-path",
    ),
]


@pytest.mark.parametrize(("args", "expected"), IMAGE_CASES)
def test_make_image_changes_section_output(args, expected: str):
    assert make_image_changes_section(*args) == expected


@pytest.mark.parametrize(("identity", "change", "image_paths", "version_paths", "expected"), COMPONENT_CASES)
def test_make_changes_section_output(
    identity: ComponentIdentity,
    change: VersionChange,
    image_paths: list[str],
    version_paths: list[str],
    expected: str,
):
    assert make_changes_section(identity, "4.9.3", change, image_paths, version_paths) == expected


POINTER = "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"


def test_render_changes_section_separates_parts_with_one_blank_line():
    bullets = ["- Image tag pin `a.image.tag` `1` → `2` in\n", "  `charts/podiumd/values.yaml`.\n"]
    assert render_changes_section("a 1 → 2", ["Intro\n", "more.\n"], bullets, "4.9.3") == (
        "### a 1 → 2\n\nIntro\nmore.\n\n" + "".join(bullets) + "\n" + POINTER + "\n"
    )
    assert render_changes_section("a 2", [], ["- `a.tag` `2` (new)\n"], "4.9.3") == (
        "### a 2\n\n- `a.tag` `2` (new)\n\n" + POINTER + "\n"
    )


@pytest.mark.parametrize(
    ("old", "new", "heading", "pin"),
    [
        ("1.2", "1.3", "1.2 → 1.3", "`1.2` → `1.3`"),
        (None, "1.3", "1.3 (new)", "`1.3` (new)"),
        ("v1.3", "1.3", "1.3 (unchanged)", "`1.3` (unchanged)"),
    ],
)
def test_version_transition_and_pin_version_text(old: str | None, new: str, heading: str, pin: str):
    assert version_transition(old, new) == heading
    assert pin_version_text(old, new) == pin


DOC = (
    "# Upgrade guide\n\n## Changes\n\n"
    "### zac 1 → 2\n\n"
    "- Image tag pin `zac.image.tag` `1` → `2` in\n  `charts/podiumd/values.yaml`.\n" + POINTER + "\n"
    "### curl 1 → 2\n\npinned at:\n\n- `global.images.curl.tag` `1` → `2`\n" + POINTER + "\n"
    "### ok 1 → 2\n\n- `ok.tag` `1` → `2`\n\n" + POINTER + "\n"
    "## Notes\n\nText\n" + POINTER
)


def _issues(text: str) -> list[tuple[str, str]]:
    return [(i.heading, i.kind) for i in pointer_issues(text)]


def test_pointer_without_blank_line_is_reported_only_inside_changes_blocks():
    assert _issues(DOC) == [("zac 1 → 2", "no-blank-line-before"), ("curl 1 → 2", "no-blank-line-before")]


def test_fix_pointer_issues_adds_blank_lines_and_is_idempotent():
    text, fixed = fix_pointer_issues(DOC, "4.9.3")
    assert [i.heading for i in fixed] == ["zac 1 → 2", "curl 1 → 2"]
    assert "  `charts/podiumd/values.yaml`.\n\n" + POINTER in text
    assert "- `global.images.curl.tag` `1` → `2`\n\n" + POINTER in text
    assert text.endswith("Text\n" + POINTER)
    assert not pointer_issues(text)
    assert fix_pointer_issues(text, "4.9.3") == (text, [])


MISSING = (
    "## Changes\n\n"
    "### keycloak - keycloak-config-cli 6.5.1-26 → 6.5.1-26.5.5\n\n"
    "pinned at:\n\n- `keycloak.keycloakConfigCli.image.tag` `6.5.1-26` → `6.5.1-26.5.5`\n\n"
    "### zac 1 → 2\n\n- `zac.image.tag` `1` → `2`\n\n" + POINTER
)


def test_missing_pointer_is_reported_and_appended_after_a_blank_line():
    """The keycloak-config-cli section lost its pointer in a merge resolution."""
    assert _issues(MISSING) == [("keycloak - keycloak-config-cli 6.5.1-26 → 6.5.1-26.5.5", "missing")]

    text, fixed = fix_pointer_issues(MISSING, "4.9.3")

    assert len(fixed) == 1
    assert "- `keycloak.keycloakConfigCli.image.tag` `6.5.1-26` → `6.5.1-26.5.5`\n\n" + POINTER + "\n### zac" in text
    assert not pointer_issues(text)


def test_duplicate_pointer_is_reported_but_not_fixed():
    doc = "## Changes\n\n### zac 1 → 2\n\n- `zac.image.tag` `1` → `2`\n\n" + POINTER + "\n" + POINTER
    assert [(i.heading, i.kind, i.count) for i in pointer_issues(doc)] == [("zac 1 → 2", "duplicate", 2)]
    assert fix_pointer_issues(doc, "4.9.3") == (doc, [])


@pytest.mark.parametrize(
    "section",
    [
        "### zac 1 → 2\n\n- `zac.image.tag` `1` → `2`\n\n" + POINTER + "\nNote after the pointer.\n",
        (
            "### widget 2.0.0\n\nTODO: describe this component's changes — its app version could not be resolved "
            "from the table row.\n"
        ),
    ],
    ids=["text-after-pointer", "todo-stub"],
)
def test_sections_that_need_no_pointer_fix_are_not_reported(section: str):
    assert not pointer_issues("## Changes\n\n" + section)


@pytest.mark.parametrize("section", [p.values[1] for p in IMAGE_CASES] + [p.values[4] for p in COMPONENT_CASES])
def test_every_line_the_renderers_write_is_owned(section: str):
    """The recogniser is built from the renderers' templates: nothing they write may count as user text."""
    body = section.splitlines(keepends=True)[1:]
    assert None not in changes_body_kinds(body)


@pytest.mark.parametrize(
    "line",
    [
        "to be safe, restart the pods.\n",
        "**Note**: restart the pods.\n",
        "PodiumD 4.9.3 needs a manual step.\n",
        "- restart the pods\n",
        "- `zac.image.tag` must be set per gemeente\n",
        "pinned at: see below\n",
    ],
)
def test_user_lines_are_not_owned(line: str):
    assert changes_body_kinds([line]) == [None]


def test_continuation_lines_are_owned_only_after_their_opening_line():
    body = ["Restart first.\n", "to 5.4.5.\n", "  `charts/podiumd/values.yaml`.\n", "pinned at:\n"]
    assert changes_body_kinds(body) == [None, None, None, None]


def test_replace_changes_section_keeps_user_text_in_place():
    """A second bump in one cycle rewrites the generated parts; the user's paragraph and bullets stay."""
    ordering = OrderingContext([{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}], {"zac": {}})
    first = make_changes_section(ZAC, "4.9.3", VersionChange("5.4.4", "5.4.5", "1.0.297", "1.0.297"), ["image"])
    user_para, user_bullet = "Restart ZAC after the upgrade.\n", "- check the zaakbrug logs\n"
    doc_lines = ["# Upgrade\n", "\n", "## Changes\n", "\n", *first.splitlines(keepends=True)]
    pointer_at = next(i for i, line in enumerate(doc_lines) if line.startswith("- Image / digest"))
    doc_lines[pointer_at:pointer_at] = [user_para, "\n"]
    doc = "".join(doc_lines).rstrip("\n") + "\n" + user_bullet

    second = make_changes_section(ZAC, "4.9.3", VersionChange("5.4.4", "5.4.6", "1.0.297", "1.0.297"), ["image"])
    new_doc = replace_changes_section(doc, second, "zac", ordering)

    assert "### zac 5.4.4 → 5.4.6 (chart 1.0.297, unchanged)\n" in new_doc
    assert "- Image tag pin `zac.image.tag` `5.4.4` → `5.4.6` in\n" in new_doc
    assert "5.4.5" not in new_doc
    assert user_para in new_doc and user_bullet in new_doc
    assert new_doc.index(user_para) < new_doc.index("- Image / digest") < new_doc.index(user_bullet)


def test_edited_changes_lines_finds_hand_edited_generated_lines():
    section = make_changes_section(ZAC, "4.9.3", VersionChange("5.4.4", "5.4.5", "1.0.297", "1.0.297"), ["image"])
    edited = section.replace("to 5.4.5.\n", "to 5.4.5 (fixes CVE-X).\n").replace(
        "`5.4.5` in\n", "`5.4.5` in values.yaml, see below\n"
    )
    doc = "# Upgrade\n\n## Changes\n\n" + edited

    assert [line for _heading, line in edited_changes_lines(doc)] == [
        "to 5.4.5 (fixes CVE-X).",
        "- Image tag pin `zac.image.tag` `5.4.4` → `5.4.5` in values.yaml, see below",
    ]


def test_edited_changes_lines_ignores_user_lines_and_untouched_sections():
    section = make_changes_section(ZAC, "4.9.3", VersionChange("5.4.4", "5.4.5", "1.0.297", "1.0.297"), ["image"])
    doc = "# Upgrade\n\n## Changes\n\n" + section + "\nto be safe, restart the pods.\n\npinned at: see below\n"

    assert edited_changes_lines(doc) == []
