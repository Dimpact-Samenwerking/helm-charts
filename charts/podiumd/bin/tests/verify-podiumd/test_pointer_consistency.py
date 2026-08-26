"""check_pointer_consistency — sibling-doc and images-manifest cross-reference
validation."""
import pytest


@pytest.fixture
def dirs(tmp_path):
    doc_dir = tmp_path / "_UPGRADE_PATHS"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    return doc_dir, images_dir


def test_no_references_is_clean(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("# Upgrade guide\n\nNothing to see here.\n")
    assert libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir) == []


def test_correct_sibling_reference_passes(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text("# Values deltas\n")
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n")
    assert libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir) == []


def test_reference_to_a_different_historical_hop_is_ignored(libdocsconsistency, dirs):
    """A link to an older hop's doc (e.g. 4.8.1-to-4.8.2) is not this
    release's concern and must not be flagged just because it doesn't match
    the current baseline."""
    doc_dir, images_dir = dirs
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        "See [`4.8.1-to-4.8.2-gemeente-specific.md`](4.8.1-to-4.8.2-gemeente-specific.md#anchor).\n"
    )
    assert libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir) == []


def test_stale_baseline_in_sibling_reference_is_flagged(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    (doc_dir / "4.8.2-to-4.9.0-values-deltas.md").write_text("# Values deltas\n")
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("See [`4.8.2-to-4.9.0-values-deltas.md`](4.8.2-to-4.9.0-values-deltas.md).\n")
    issues = libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir)
    assert issues
    assert all("expected \"4.8.5\"" in i for i in issues)


def test_reference_to_nonexistent_sibling_is_flagged(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n")
    issues = libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir)
    assert any("does not exist" in i for i in issues)


def test_correct_images_reference_passes(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    (images_dir / "images-4.9.0.yaml").write_text("[]\n")
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("See [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n")
    assert libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir) == []


def test_images_reference_wrong_version_is_flagged(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("See [`images-4.9.9.yaml`](../images/images-4.9.9.yaml).\n")
    issues = libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir)
    assert any("expected \"4.9.0\"" in i for i in issues)


def test_images_reference_to_nonexistent_file_is_flagged(libdocsconsistency, dirs):
    doc_dir, images_dir = dirs
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text("See [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n")
    issues = libdocsconsistency.check_pointer_consistency(doc, "4.8.5", "4.9.0", doc_dir, images_dir)
    assert any("does not exist" in i for i in issues)
