"""lib.component_docs — existing_doc_baselines, create_missing_docs,
baseline_doc_paths, images_manifest_path: the standard-doc-set scan/
create/path helpers shared by create-doc-version and fix-doc-consistency.
The per-component doc-rewrite helpers (fix_component_version_table and
friends) are exercised through update-component-version/update-image-
version's own test suites instead, against realistic doc fixtures."""


# --- images_manifest_path ---

def test_images_manifest_path(libcomponentdocs, tmp_path):
    assert libcomponentdocs.images_manifest_path(tmp_path, "4.9.0") == tmp_path / "images-4.9.0.yaml"


# --- baseline_doc_paths ---

def test_baseline_doc_paths_none_baseline_returns_none_none(libcomponentdocs, tmp_path):
    assert libcomponentdocs.baseline_doc_paths(tmp_path, None, "4.9.0") == (None, None)


def test_baseline_doc_paths_missing_upgrade_doc_returns_none_none(libcomponentdocs, tmp_path):
    assert libcomponentdocs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0") == (None, None)


def test_baseline_doc_paths_finds_both(libcomponentdocs, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text("x", encoding="utf-8")
    upgrade_path, values_deltas_path = libcomponentdocs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path == tmp_path / "4.8.5-to-4.9.0-values-deltas.md"


def test_baseline_doc_paths_missing_values_deltas_is_none(libcomponentdocs, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    upgrade_path, values_deltas_path = libcomponentdocs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path is None


# --- existing_doc_baselines ---

def test_existing_doc_baselines_groups_by_suffix(libcomponentdocs, tmp_path):
    (tmp_path / "4.8.2-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.2-to-4.9.0-values-deltas.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.7.8-to-4.8.0-upgrade.md").write_text("x", encoding="utf-8")  # different target, ignored

    by_suffix = libcomponentdocs.existing_doc_baselines(tmp_path, "4.9.0")

    assert set(by_suffix.keys()) == {"upgrade", "values-deltas"}
    assert by_suffix["upgrade"] == [("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md")]


def test_existing_doc_baselines_empty_when_no_match(libcomponentdocs, tmp_path):
    (tmp_path / "4.7.8-to-4.8.0-upgrade.md").write_text("x", encoding="utf-8")
    assert libcomponentdocs.existing_doc_baselines(tmp_path, "4.9.0") == {}


def test_existing_doc_baselines_multiple_sources_for_one_suffix(libcomponentdocs, tmp_path):
    """Two different baselines both claiming the same suffix for this
    target — the exact shape create-doc-version's mismatch refusal and
    fix-doc-consistency's collision refusal both key off."""
    (tmp_path / "4.8.2-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.3-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    by_suffix = libcomponentdocs.existing_doc_baselines(tmp_path, "4.9.0")
    assert sorted(by_suffix["upgrade"]) == [
        ("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md"),
        ("4.8.3", tmp_path / "4.8.3-to-4.9.0-upgrade.md"),
    ]


# --- create_missing_docs ---

def test_create_missing_docs_creates_all_when_none_exist(libcomponentdocs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()

    created = libcomponentdocs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0")

    assert set(created) == {
        "4.8.5-to-4.9.0-upgrade.md", "4.8.5-to-4.9.0-gemeente-specific.md",
        "4.8.5-to-4.9.0-values-deltas.md", "images-4.9.0.yaml",
    }
    upgrade_text = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "PodiumD 4.8.5 → 4.9.0" in upgrade_text
    images_text = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.5." in images_text


def test_create_missing_docs_never_overwrites_existing(libcomponentdocs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    existing = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    existing.write_text("hand-written content\n", encoding="utf-8")

    created = libcomponentdocs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0")

    assert "4.8.5-to-4.9.0-upgrade.md" not in created
    assert existing.read_text(encoding="utf-8") == "hand-written content\n"
    assert "4.8.5-to-4.9.0-gemeente-specific.md" in created  # the other two still get created


def test_create_missing_docs_nothing_to_do_when_all_exist(libcomponentdocs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    for suffix in libcomponentdocs.STANDARD_SUFFIXES:
        (doc_dir / f"4.8.5-to-4.9.0-{suffix}.md").write_text("x", encoding="utf-8")
    (images_dir / "images-4.9.0.yaml").write_text("x", encoding="utf-8")

    assert libcomponentdocs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0") == []
