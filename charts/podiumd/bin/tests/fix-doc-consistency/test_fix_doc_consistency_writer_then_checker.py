"""fix-doc-consistency then check_docs_consistency, per scenario: the checker accepts what the writer wrote.

writer_then_checker (conftest.py) also runs the writer a second time and
requires that it changes nothing.
"""

import pytest

UPGRADE = "_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md"
DELTAS = "_UPGRADE_PATHS/4.8.5-to-4.9.0-values-deltas.md"
MANIFEST = "images/images-4.9.0.yaml"
ZAC = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"}
KISS = {"name": "kiss", "version": "3.1.1", "repository": "@kiss"}


def image(repository: str, tag: str) -> dict[str, str]:
    return {"repository": repository, "tag": f"{tag}@sha256:{'a' * 64}"}


def zac(tag: str, **sidecars: dict[str, str]) -> dict[str, object]:
    return {
        "image": image("ghcr.io/infonl/zaakafhandelcomponent", tag),
        **{k: {"image": v} for k, v in sidecars.items()},
    }


def kiss(tag: str) -> dict[str, object]:
    return {"image": image("ghcr.io/kiss/kiss-frontend", tag)}


def test_a_version_bump(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5")}},
    )

    assert "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |" in docs[UPGRADE]
    assert "### zac 5.4.4 → 5.4.5 (chart 1.0.297, unchanged)" in docs[UPGRADE]
    assert "#   1. zac 5.4.4 -> 5.4.5." in docs[MANIFEST]


def test_a_second_bump_keeps_the_user_text_of_the_section(writer_then_checker):
    note = "Restart the zaakbrug after ZAC.\n"
    earlier_doc = (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### zac 5.4.4 → 5.4.5 (chart 1.0.297, unchanged)\n\n"
        "PodiumD 4.9.0 upgrades **zac** from app version 5.4.4\nto 5.4.5.\n\n"
        f"{note}\n"
        "- Image tag pin `zac.image.tag` `5.4.4` → `5.4.5` in\n  `charts/podiumd/values.yaml`.\n\n"
        "- Image / digest: see [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n"
    )
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.6")}, "files": {f"docs/{UPGRADE}": earlier_doc}},
    )

    assert "### zac 5.4.4 → 5.4.6 (chart 1.0.297, unchanged)" in docs[UPGRADE]
    assert "5.4.5" not in docs[UPGRADE]
    assert note in docs[UPGRADE]


def test_a_new_component(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC, KISS], "values": {"zac": zac("5.4.4"), "kiss": kiss("3.1.1")}},
    )

    assert "| kiss | 3.1.1 (new) | 3.1.1 (new) | - |" in docs[UPGRADE]
    assert "PodiumD 4.9.0 introduces **kiss** at app version 3.1.1." in docs[UPGRADE]


def test_a_new_component_whose_image_is_in_an_older_manifest(writer_then_checker):
    """The old app version comes from images-4.8.0.yaml: writer and checker must agree on it."""
    older_manifest = (
        "- name: kiss/kiss-frontend\n  url: ghcr.io/kiss/kiss-frontend\n"
        f'  version: "3.0.0"\n  digest: "sha256:{"b" * 64}"\n'
    )
    docs = writer_then_checker(
        {
            "version": "4.8.5",
            "deps": [ZAC],
            "values": {"zac": zac("5.4.4")},
            "files": {"docs/images/images-4.8.0.yaml": older_manifest},
        },
        {"version": "4.9.0", "deps": [ZAC, KISS], "values": {"zac": zac("5.4.4"), "kiss": kiss("3.1.1")}},
    )

    assert "| kiss | 3.0.0 → 3.1.1 | 3.1.1 (new) | - |" in docs[UPGRADE]
    assert "### kiss 3.0.0 → 3.1.1 (chart 3.1.1, new)" in docs[UPGRADE]


def test_a_sidecar_only_bump_gets_no_row_for_its_parent(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4", opa=image("openpolicyagent/opa", "1.4.1"))}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.4", opa=image("openpolicyagent/opa", "1.4.2"))}},
    )

    assert "| zac - opa | 1.4.1 → 1.4.2 | - | - |" in docs[UPGRADE]
    assert "| zac |" not in docs[UPGRADE]


def test_a_values_key_added_and_one_removed(writer_then_checker):
    baseline = {"zac": {**zac("5.4.4"), "oldFeature": {"enabled": True}}}
    # Other content than oldFeature, or describe_key_changes reports a rename.
    target = {"zac": {**zac("5.4.5"), "newFeature": {"replicas": 2}}}
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": baseline},
        {"version": "4.9.0", "deps": [ZAC], "values": target},
    )

    assert "- Key `zac.newFeature` was added." in docs[DELTAS]
    assert "- Key `zac.oldFeature` was removed." in docs[DELTAS]


def test_a_removed_component_and_image(writer_then_checker):
    docs = writer_then_checker(
        {
            "version": "4.8.5",
            "deps": [ZAC, KISS],
            "values": {"zac": zac("5.4.4", opa=image("openpolicyagent/opa", "1.4.2")), "kiss": kiss("3.1.1")},
        },
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5")}},
    )

    assert (
        "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n"
        "| zac - opa | 1.4.2 (removed) | - | - |\n"
        "| kiss | 3.1.1 (removed) | 3.1.1 (removed) | - |\n"
    ) in docs[UPGRADE]
    assert "PodiumD 4.9.0 removes **kiss** (was 3.1.1)." in docs[UPGRADE]
    assert "kiss" not in docs[MANIFEST]
    assert "kiss" not in docs[DELTAS]


def test_a_shared_image_and_two_sidecars_of_one_parent_follow_values_yaml(writer_then_checker):
    def values(curl: str, solr: str, opa: str) -> dict[str, object]:
        return {
            "global": {"images": {"curl": image("curlimages/curl", curl)}},
            "zac": zac("5.4.4", solr=image("library/solr", solr), opa=image("openpolicyagent/opa", opa)),
        }

    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": values("8.21.0", "9.10.0", "1.4.1")},
        {"version": "4.9.0", "deps": [ZAC], "values": values("8.22.0", "9.10.1", "1.4.2")},
    )

    rows = [line.split(" | ")[0] for line in docs[UPGRADE].splitlines() if line.startswith("| ") and "→" in line]
    assert rows == ["| curl", "| zac - solr", "| zac - opa"]
    items = [line for line in docs[MANIFEST].splitlines() if line.startswith("#   ")]
    assert [item.split(". ", 1)[1].split(" ")[0] for item in items[:3]] == ["curl", "zac", "zac"]


@pytest.mark.xfail(strict=True, reason='known gap: the writer never adds a missing "podiumd X vs Y" line')
def test_a_manifest_without_its_vs_line(writer_then_checker):
    manifest = "# Baseline: podiumd 4.8.5. Re-verify before release.\n#\n# Changes:\n#\n\n"
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5")}, "files": {f"docs/{MANIFEST}": manifest}},
    )

    assert "# Images new or changed in podiumd 4.9.0 vs 4.8.5." in docs[MANIFEST]
