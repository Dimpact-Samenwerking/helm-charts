"""Upgrade-doc Changes sections: exact renderer output, shared version text and the pointer check.

Written against the output before they shared a skeleton, so a refactor
must keep it byte-identical, except for the blank line the component
section gained before the "- Image / digest" pointer."""

import pytest

from lib.component_docs.changes_section import ComponentIdentity
from lib.component_docs.changes_section import VersionChange
from lib.component_docs.changes_section import add_blank_line_before_pointers
from lib.component_docs.changes_section import make_changes_section
from lib.component_docs.changes_section import pointers_without_blank_line
from lib.component_docs.changes_section import render_changes_section
from lib.image.docs import make_image_changes_section
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


def test_pointers_without_blank_line_only_inside_changes_blocks():
    assert [heading for heading, _ in pointers_without_blank_line(DOC)] == ["zac 1 → 2", "curl 1 → 2"]


def test_add_blank_line_before_pointers_repairs_and_is_idempotent():
    text, headings = add_blank_line_before_pointers(DOC)
    assert headings == ["zac 1 → 2", "curl 1 → 2"]
    assert "  `charts/podiumd/values.yaml`.\n\n" + POINTER in text
    assert "- `global.images.curl.tag` `1` → `2`\n\n" + POINTER in text
    assert text.endswith("Text\n" + POINTER)
    assert not pointers_without_blank_line(text)
    assert add_blank_line_before_pointers(text) == (text, [])
