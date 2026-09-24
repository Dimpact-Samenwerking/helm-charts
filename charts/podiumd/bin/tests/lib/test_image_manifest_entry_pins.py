"""lib.image.manifest_entry_pins — the version/digest an images-manifest
entry must state, shared by check_docs_consistency and
fix-doc-consistency."""

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.image import manifest_entry_pins

OLD = "a" * 64
NEW = "b" * 64

VALUES = {"clamav": {"image": {"repository": "docker.io/clamav/clamav", "tag": f"1.5.4@sha256:{NEW}"}}}
DEPS: list[ChartDependency] = [{"name": "clamav", "version": "3.7.2"}]


def manifest(digest: str) -> str:
    return (
        "# Changes:\n"
        "#   1. clamav 1.5.4 (digest changed).\n\n"
        "# clamav 1.5.4 (digest changed)\n"
        "- name: clamav/clamav\n"
        "  url: docker.io/clamav/clamav\n"
        '  version: "1.5.4"\n'
        f'  digest: "sha256:{digest}"\n'
    )


def test_sync_entry_pins_rewrites_a_stale_digest(tmp_path: Path) -> None:
    new_text, synced = manifest_entry_pins.sync_entry_pins(manifest(OLD), tmp_path, DEPS, VALUES, {})

    assert synced == ["clamav/clamav"]
    assert new_text == manifest(NEW)


def test_sync_entry_pins_leaves_a_matching_entry_alone(tmp_path: Path) -> None:
    new_text, synced = manifest_entry_pins.sync_entry_pins(manifest(NEW), tmp_path, DEPS, VALUES, {})

    assert not synced
    assert new_text == manifest(NEW)


def test_entry_pin_is_the_tag_check_docs_consistency_compares() -> None:
    paths = manifest_entry_pins.current_image_paths(VALUES)
    entry = {"name": "clamav/clamav", "url": "docker.io/clamav/clamav"}

    path, tag = manifest_entry_pins.entry_pin(entry, VALUES, paths, {}, {})

    assert path == ("clamav", "image")
    assert tag == f"1.5.4@sha256:{NEW}"
