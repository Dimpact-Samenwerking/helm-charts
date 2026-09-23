"""How update-*-version and fix-doc-consistency find the table row,
"### ..." Changes block and "# Changes:" item they rewrite: text_names,
find_changes_item and remove_changes_section, which resolve names the
same way check_docs_consistency does (match_canonical_sidecar_name)."""

from lib.component_docs.changes_section import OrderingContext
from lib.component_docs.changes_section import remove_changes_section
from lib.component_docs.images_manifest_changes_header import find_changes_item
from lib.upgradedoc.string_and_parsing_basics import match_canonical_sidecar_name
from lib.upgradedoc.string_and_parsing_basics import text_names

DEPS = [{"name": "openbao", "version": "0.20.0"}]
SIDECAR_PATH = ("openbao", "csi", "image")
ORDERING = OrderingContext(DEPS, {"openbao": {}}, {"openbao - openbao-csi-provider": SIDECAR_PATH})
POSTGRES_PATH = ("zac", "postgres", "image")
EXPORTER_PATH = ("zac", "postgres", "exporter", "image")
CURL_PATH = ("global", "images", "curl")
CANONICAL_NAMES = {
    "zac - postgres": POSTGRES_PATH,
    "zac - postgres-exporter": EXPORTER_PATH,
    "curl": CURL_PATH,
    "busybox": ("global", "images", "busybox"),
}


def test_text_names_matches_whole_words_only() -> None:
    assert text_names("ZAC (Zaakafhandelcomponent) 4.1 → 4.2", "zac")
    assert not text_names("Python (ensurePodiumdAdminUser init image)", "mi")


def test_text_names_keeps_sidecar_and_plain_names_apart() -> None:
    assert text_names("openbao - openbao-csi-provider 1.5.0 → 1.6.0.", "openbao - openbao-csi-provider")
    assert not text_names("openbao - openbao-csi-provider 1.5.0 → 1.6.0.", "openbao")
    assert not text_names("OpenBao 2.5.5 → 2.5.6", "openbao - openbao-csi-provider")


def test_text_names_sidecar_name_is_not_a_prefix_of_another_sidecar() -> None:
    assert not text_names("zac - postgres-exporter 0.17 → 0.18.", "zac - postgres")
    assert text_names("zac - postgres v17.1 → v17.2.", "zac - postgres")


def test_find_changes_item_skips_a_mid_word_match() -> None:
    lines = [
        "# Changes:\n",
        "#   1. Python (ensurePodiumdAdminUser init image) 3.12 → 3.13.\n",
        "#   2. mi 1.0 → 1.1.\n",
    ]

    assert find_changes_item(lines, [1, 2], "mi") == 2


def test_remove_changes_section_leaves_the_sidecar_block_alone() -> None:
    doc = (
        "## Changes\n\n"
        "### openbao - openbao-csi-provider 1.5.0 → 1.6.0\n\nsidecar text\n\n"
        "### OpenBao 2.5.5 → 2.5.6\n\nparent text\n"
    )

    new_text, removed = remove_changes_section(doc, "openbao", ORDERING)

    assert removed
    assert new_text == "## Changes\n\n### openbao - openbao-csi-provider 1.5.0 → 1.6.0\n\nsidecar text\n\n"


def test_remove_changes_section_without_the_parent_block_removes_nothing() -> None:
    doc = "## Changes\n\n### openbao - openbao-csi-provider 1.5.0 → 1.6.0\n\nsidecar text\n"

    assert remove_changes_section(doc, "openbao", ORDERING) == (doc, False)


def test_match_canonical_sidecar_name_heading_with_version() -> None:
    assert match_canonical_sidecar_name("zac - postgres v17.1 → v17.2", CANONICAL_NAMES) == POSTGRES_PATH
    assert match_canonical_sidecar_name("zac - postgres-exporter 0.17 → 0.18", CANONICAL_NAMES) == EXPORTER_PATH
    assert match_canonical_sidecar_name("curl 8.21.0 → 8.22.0", CANONICAL_NAMES) == CURL_PATH


def test_match_canonical_sidecar_name_needs_the_exact_sidecar_name_first() -> None:
    assert match_canonical_sidecar_name("ZAC - postgres image (metrics) 17.2", CANONICAL_NAMES) is None
    assert match_canonical_sidecar_name("`zac.postgres.image.tag`", CANONICAL_NAMES) is None


def test_match_canonical_sidecar_name_two_names_match_nothing() -> None:
    assert match_canonical_sidecar_name("Shared images: curl, busybox", CANONICAL_NAMES) is None
