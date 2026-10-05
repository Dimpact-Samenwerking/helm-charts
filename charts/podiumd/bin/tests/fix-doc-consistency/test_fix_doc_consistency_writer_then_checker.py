"""fix-doc-consistency then check_docs_consistency, per scenario: the checker accepts what the writer wrote.

writer_then_checker (conftest.py) also runs the writer a second time and
requires that it changes nothing.
"""

UPGRADE = "_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md"
DELTAS = "_UPGRADE_PATHS/4.8.5-to-4.9.0-values-deltas.md"
MANIFEST = "images/images-4.9.0.yaml"
ZAC = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"}
KISS = {"name": "kiss", "version": "3.1.1", "repository": "@kiss"}


def image(repository: str, tag: str, digest: str = "a") -> dict[str, str]:
    return {"repository": repository, "tag": f"{tag}@sha256:{digest * 64}"}


def zac(tag: str, digest: str = "a", **sidecars: dict[str, str]) -> dict[str, object]:
    return {
        "image": image("ghcr.io/infonl/zaakafhandelcomponent", tag, digest),
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


def test_a_manifest_without_its_vs_line(writer_then_checker):
    manifest = "# Baseline: podiumd 4.8.5. Re-verify before release.\n#\n# Changes:\n#\n\n"
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5")}, "files": {f"docs/{MANIFEST}": manifest}},
    )

    assert "# Images new or changed in podiumd 4.9.0 vs 4.8.5." in docs[MANIFEST]


def test_a_digest_only_re_pin_corrects_the_item_of_an_earlier_bump(writer_then_checker):
    """Back at the baseline version with a new digest: the entry stays, its row goes, its item says so."""
    earlier_manifest = (
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n#   1. zac 5.4.4 -> 5.4.5.\n#\n\n"
        "# zac 5.4.4 -> 5.4.5\n"
        "- name: infonl/zaakafhandelcomponent\n  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'  version: "5.4.5"\n  digest: "sha256:{"c" * 64}"\n'
    )
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {
            "version": "4.9.0",
            "deps": [ZAC],
            "values": {"zac": zac("5.4.4", digest="b")},
            "files": {f"docs/{MANIFEST}": earlier_manifest},
        },
    )

    assert "#   1. zac 5.4.4 (digest changed)." in docs[MANIFEST]
    assert f'version: "5.4.4"\n  digest: "sha256:{"b" * 64}"' in docs[MANIFEST]
    assert "| zac |" not in docs[UPGRADE]


def test_a_second_sidecar_bump_rewrites_the_generated_lines_of_its_section(writer_then_checker):
    note = "Check the OPA policies after the upgrade.\n"
    earlier_doc = (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac - opa | 1.4.1 → 1.4.2 | - | - |\n\n"
        "## Changes\n\n"
        "### zac - opa 1.4.1 → 1.4.2\n\n"
        f"{note}\n"
        "PodiumD 4.9.0 upgrades the **zac - opa** image to 1.4.2,\npinned at:\n\n"
        "- `zac.opa.image.tag` `1.4.1` → `1.4.2`\n\n"
        "- Image / digest: see [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n"
    )
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4", opa=image("openpolicyagent/opa", "1.4.1"))}},
        {
            "version": "4.9.0",
            "deps": [ZAC],
            "values": {"zac": zac("5.4.4", opa=image("openpolicyagent/opa", "1.4.3"))},
            "files": {f"docs/{UPGRADE}": earlier_doc},
        },
    )

    assert "upgrades the **zac - opa** image to 1.4.3," in docs[UPGRADE]
    assert "- `zac.opa.image.tag` `1.4.1` → `1.4.3`" in docs[UPGRADE]
    assert "1.4.2" not in docs[UPGRADE]
    assert note in docs[UPGRADE]


def with_curl(values: dict[str, object], curl: str) -> dict[str, object]:
    return {"global": {"images": {"curl": image("curlimages/curl", curl)}}, **values}


def test_a_component_bumped_and_reset_to_its_baseline_leaves_no_docs(writer_then_checker):
    baseline = {"zac": {**zac("5.4.4"), "oldFeature": {"enabled": True}}}
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": baseline},
        {"version": "4.9.0", "deps": [ZAC], "values": baseline},
        earlier={"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5")}},
    )

    assert "zac" not in docs[UPGRADE]
    assert "zac" not in docs[DELTAS]
    assert "zac" not in docs[MANIFEST]
    assert "- name:" not in docs[MANIFEST]


def test_a_shared_image_bumped_twice_is_documented_from_its_baseline(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.1.0")},
        {"version": "4.9.0", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.3.0")},
        earlier={"version": "4.9.0", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.2.0")},
    )

    assert "| curl | 8.1.0 → 8.3.0 | - | - |" in docs[UPGRADE]
    assert "- `global.images.curl.tag` `8.1.0` → `8.3.0`" in docs[UPGRADE]
    assert "8.2.0" not in docs[UPGRADE] + docs[MANIFEST]
    assert "#   1. curl 8.1.0 -> 8.3.0." in docs[MANIFEST]


def test_a_shared_image_reset_to_its_baseline_leaves_no_docs(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.1.0")},
        {"version": "4.9.0", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.1.0")},
        earlier={"version": "4.9.0", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.2.0")},
    )

    assert "curl" not in docs[UPGRADE] + docs[MANIFEST]


def test_a_shared_image_absent_at_the_baseline_is_new(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC], "values": with_curl({"zac": zac("5.4.4")}, "8.2.0")},
    )

    assert "| curl | 8.2.0 (new) | - | - |" in docs[UPGRADE]
    assert "#   1. curl 8.2.0 (new)." in docs[MANIFEST]


def test_a_sidecar_bump_keeps_its_parents_own_row(writer_then_checker):
    opa = image("openpolicyagent/opa", "1.4.1")
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4", opa=opa)}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5", opa=image("openpolicyagent/opa", "1.4.2"))}},
        earlier={"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5", opa=opa)}},
    )

    assert ("| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n| zac - opa | 1.4.1 → 1.4.2 | - | - |\n") in docs[
        UPGRADE
    ]


def test_a_sidecar_reset_to_its_baseline_keeps_its_parents_docs(writer_then_checker):
    opa = image("openpolicyagent/opa", "1.4.1")
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4", opa=opa)}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5", opa=opa)}},
        earlier={
            "version": "4.9.0",
            "deps": [ZAC],
            "values": {"zac": zac("5.4.5", opa=image("openpolicyagent/opa", "1.4.2"))},
        },
    )

    assert "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |" in docs[UPGRADE]
    assert "opa" not in docs[UPGRADE] + docs[MANIFEST]


NATIVE_SETTINGS = {"etc/settings.yaml": 'component_resolution:\n  native_components: ["frankgateway"]\n'}


def frankgateway(tag: str) -> dict[str, object]:
    return {"image": image("frankframework/frankframework", tag)}


def test_a_native_component_bump(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4"), "frankgateway": frankgateway("100")}},
        {
            "version": "4.9.0",
            "deps": [ZAC],
            "values": {"zac": zac("5.4.4"), "frankgateway": frankgateway("104")},
            "files": NATIVE_SETTINGS,
        },
    )

    assert "| frankgateway | 100 → 104 | - | - |" in docs[UPGRADE]
    assert "### frankgateway 100 → 104\n" in docs[UPGRADE]


def test_a_native_components_heading_without_its_app_version_is_rewritten(writer_then_checker):
    note = "Restart every gateway instance.\n"
    earlier_doc = (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| frankgateway | 100 → 104 | - | - |\n\n"
        "## Changes\n\n"
        "### frankgateway\n\n"
        f"{note}\n"
        "- Image / digest: see [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n"
    )
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4"), "frankgateway": frankgateway("100")}},
        {
            "version": "4.9.0",
            "deps": [ZAC],
            "values": {"zac": zac("5.4.4"), "frankgateway": frankgateway("104")},
            "files": {**NATIVE_SETTINGS, f"docs/{UPGRADE}": earlier_doc},
        },
    )

    assert "### frankgateway 100 → 104\n" in docs[UPGRADE]
    assert note in docs[UPGRADE]


def test_a_stale_intro_baseline_is_rewritten_in_a_doc_already_at_the_baseline(writer_then_checker):
    earlier_doc = (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "This is the upgrade guide for environments already on **4.8.4**.\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### zac 5.4.4 → 5.4.5 (chart 1.0.297, unchanged)\n\n"
        "PodiumD 4.9.0 upgrades **zac** from app version 5.4.4\nto 5.4.5.\n\n"
        "- Image tag pin `zac.image.tag` `5.4.4` → `5.4.5` in\n  `charts/podiumd/values.yaml`.\n\n"
        "- Image / digest: see [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n"
    )
    docs = writer_then_checker(
        {"version": "4.8.5", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.5")}, "files": {f"docs/{UPGRADE}": earlier_doc}},
    )

    assert "environments already on **4.8.5**." in docs[UPGRADE]
