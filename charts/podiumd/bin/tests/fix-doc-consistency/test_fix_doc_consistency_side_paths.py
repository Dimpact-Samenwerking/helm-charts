"""A side path: a second upgrade path to the same target, declared in release-baseline.yaml's side_paths."""

from pathlib import Path

import pytest

from lib.checks.upgrade_doc_layout import upgrade_guide_layout_issues
from lib.component_docs.baseline_doc_stubs import STUB_TEMPLATES
from lib.docs_consistency import check_docs_consistency
from lib.docs_consistency.pointer_consistency import check_pointer_consistency
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import update_sibling_doc_refs
from lib.fix_doc_consistency.run import FixDocPaths
from lib.fix_doc_consistency.run import fix_docs
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name

ZAC = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"}
MAIN_UPGRADE = "_UPGRADE_PATHS/4.9.0-to-4.9.1-upgrade.md"
SIDE_UPGRADE = "_UPGRADE_PATHS/4.8.6-to-4.9.1-upgrade.md"
MANIFEST = "images/images-4.9.1.yaml"


def zac(tag: str) -> dict[str, object]:
    return {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": f"{tag}@sha256:{'a' * 64}"}}


def side_docs(side: str, target: str) -> dict[str, str]:
    """The side path's docs as a writer starts them: the stubs, with a link to the main path."""
    docs = {
        f"docs/_UPGRADE_PATHS/{doc_name(side, target, suffix)}": STUB_TEMPLATES[suffix].format(
            upgrade_docs_baseline=side, target=target
        )
        for suffix in STANDARD_SUFFIXES
    }
    upgrade = f"docs/_UPGRADE_PATHS/{doc_name(side, target, 'upgrade')}"
    docs[upgrade] = docs[upgrade].replace(
        "## Checklist", "Background: [the main path](4.9.0-to-4.9.1-upgrade.md).\n\n## Checklist", 1
    )
    return docs


def test_a_side_path_is_maintained_against_its_own_baseline(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.1", "deps": [ZAC], "values": {"zac": zac("5.4.5")}, "files": side_docs("4.8.6", "4.9.1")},
        side={"version": "4.8.6", "deps": [ZAC], "values": {"zac": zac("5.4.2")}},
    )

    assert "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |" in docs[MAIN_UPGRADE]
    assert "| zac | 5.4.2 → 5.4.5 | 1.0.297 (unchanged) | - |" in docs[SIDE_UPGRADE]
    assert "### zac 5.4.2 → 5.4.5 (chart 1.0.297, unchanged)" in docs[SIDE_UPGRADE]
    # The link to the main path is kept, and the manifest stays the main path's.
    assert "[the main path](4.9.0-to-4.9.1-upgrade.md)" in docs[SIDE_UPGRADE]
    assert "zac 5.4.4 -> 5.4.5" in docs[MANIFEST]
    assert "5.4.2" not in docs[MANIFEST]
    assert "TODO" not in docs[SIDE_UPGRADE]
    assert upgrade_guide_layout_issues(SIDE_UPGRADE, docs[SIDE_UPGRADE], "4.8.6", "4.9.1") == []


def test_a_side_path_without_docs_gets_no_stubs(writer_then_checker):
    docs = writer_then_checker(
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.1", "deps": [ZAC], "values": {"zac": zac("5.4.5")}},
        side={"version": "4.8.6", "deps": [ZAC], "values": {"zac": zac("5.4.2")}},
    )

    assert not any(name.startswith("_UPGRADE_PATHS/4.8.6-") for name in docs)


def _two_doc_sets(tmp_path: Path) -> FixDocPaths:
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir()
    for baseline in ("4.9.0", "4.8.6"):
        (doc_dir / doc_name(baseline, "4.9.1", "upgrade")).write_text(
            f"# Upgrade guide: PodiumD {baseline} → 4.9.1\n", encoding="utf-8"
        )
    return FixDocPaths(tmp_path, doc_dir, tmp_path / "docs" / "images")


@pytest.mark.parametrize("side_paths", [(), ("4.8.7",)])
def test_an_undeclared_second_baseline_still_refuses(
    tmp_path: Path, side_paths: tuple[str, ...], capsys: pytest.CaptureFixture[str]
):
    with pytest.raises(SystemExit):
        fix_docs(_two_doc_sets(tmp_path), "4.9.1", "4.9.0", side_paths)

    out = capsys.readouterr().out
    assert "4.8.6-to-4.9.1-upgrade.md  (baseline 4.8.6)" in out
    assert "Refusing to rename anything" in out


def test_main_doc_links_to_a_side_path_are_kept():
    text = "See [`4.8.6-to-4.9.1-upgrade.md`](4.8.6-to-4.9.1-upgrade.md) and 4.8.5-to-4.9.1-values-deltas.md."

    new_text, changed = update_sibling_doc_refs(text, "4.9.1", "4.9.0", ["4.8.6"])

    assert changed
    assert new_text == (
        "See [`4.8.6-to-4.9.1-upgrade.md`](4.8.6-to-4.9.1-upgrade.md) and 4.9.0-to-4.9.1-values-deltas.md."
    )


def test_each_path_is_reported_on_its_own(writer_then_checker, tmp_path: Path):
    docs = writer_then_checker(
        {"version": "4.9.0", "deps": [ZAC], "values": {"zac": zac("5.4.4")}},
        {"version": "4.9.1", "deps": [ZAC], "values": {"zac": zac("5.4.5")}, "files": side_docs("4.8.6", "4.9.1")},
        side={"version": "4.8.6", "deps": [ZAC], "values": {"zac": zac("5.4.2")}},
    )

    ok, detail = check_docs_consistency(tmp_path, "4.9.0", ["4.8.6"])
    assert ok, detail
    assert detail.startswith("4.9.0 → 4.9.1: matches 4.9.0-to-4.9.1-")
    assert "; 4.8.6 → 4.9.1: matches 4.8.6-to-4.9.1-" in detail

    pointer = "- Image / digest: see [`images-4.9.1.yaml`](../images/images-4.9.1.yaml)."
    side_upgrade = tmp_path / "docs" / SIDE_UPGRADE
    side_upgrade.write_text(docs[SIDE_UPGRADE].replace(pointer, f"{pointer}\n\n{pointer}"), encoding="utf-8")
    ok, detail = check_docs_consistency(tmp_path, "4.9.0", ["4.8.6"])
    assert not ok
    assert "4.9.0 → 4.9.1: matches" in detail
    assert "4.8.6 → 4.9.1: 1 to fix by hand" in detail

    side_upgrade.write_text(
        docs[SIDE_UPGRADE].replace("PodiumD 4.8.6 → 4.9.1", "PodiumD 4.8.5 → 4.9.1"), encoding="utf-8"
    )
    ok, detail = check_docs_consistency(tmp_path, "4.9.0", ["4.8.6"])
    assert not ok
    assert detail.startswith("1 doc(s) fix-doc-consistency would change; 4.9.0 → 4.9.1: matches")


@pytest.mark.parametrize(
    ("side_path", "manifest", "flagged"),
    [
        (None, "images-4.9.0.yaml", True),
        ("4.8.6", "images-4.9.0.yaml", False),
        ("4.8.6", "images-4.8.6.yaml", True),
    ],
)
def test_a_side_path_doc_may_name_the_manifests_it_spans(
    tmp_path: Path, side_path: str | None, manifest: str, *, flagged: bool
):
    (tmp_path / manifest).write_text("[]\n", encoding="utf-8")
    doc = tmp_path / "4.8.6-to-4.9.1-upgrade.md"
    doc.write_text(f"Mirror [`{manifest}`](../images/{manifest}).\n", encoding="utf-8")

    issues = check_pointer_consistency(doc, "4.9.1", tmp_path, tmp_path, side_path)

    assert bool(issues) == flagged
