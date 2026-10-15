"""images-<target>.yaml entries for a digest-pinning exception without a digest field (omc.image)."""

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import cast

import pytest

import lib.docs_consistency as dc

from lib.docs_consistency.check_context import Findings
from lib.docs_consistency.check_context import ManifestEntryScan

if TYPE_CHECKING:
    from lib.docs_consistency.check_context import DocsCheckContext
    from lib.images_manifest import ManifestEntry

OMC = ("omc", "image")
DIGEST = "sha256:" + "e" * 64


def _check(monkeypatch: pytest.MonkeyPatch, values_tag: str, sibling_fields) -> list[str]:
    monkeypatch.setattr(dc, "entry_pin", lambda *_args: (OMC, values_tag))
    # Only the fields the entry check reads; a full DocsCheckContext needs a chart on disk.
    ctx = cast(
        "DocsCheckContext",
        SimpleNamespace(
            current=SimpleNamespace(values={}),
            images=SimpleNamespace(current=SimpleNamespace(paths={OMC: values_tag})),
            baseline_ref=None,
        ),
    )
    scan = ManifestEntryScan(Path("images-4.10.0.yaml"), {}, sibling_fields)
    findings = Findings(checked=[], mismatches=[])
    entry: ManifestEntry = {"name": "worthnl/notifynl-omc", "version": "2.3.1", "digest": DIGEST}
    # The per-entry check has no public entry point without a full manifest run.
    dc._check_images_manifest_entry(ctx, scan, entry, findings)  # pylint: disable=protected-access  # pyright: ignore[reportPrivateUsage]
    return findings.mismatches


def test_tag_only_exception_accepts_the_bare_tag(monkeypatch: pytest.MonkeyPatch):
    """omc.image cannot carry a digest: its "2.3.1" matches an entry "2.3.1" with the registry digest."""
    assert not _check(monkeypatch, "2.3.1", {OMC: {"sibling_field": None, "writable": False}})


def test_tag_only_exception_still_flags_another_version(monkeypatch: pytest.MonkeyPatch):
    """Tag-only still means the same version: a different values.yaml tag is a mismatch."""
    mismatches = _check(monkeypatch, "2.3.0", {OMC: {"sibling_field": None, "writable": False}})
    assert mismatches and 'values.yaml tag is "2.3.0"' in mismatches[0]


def test_bare_tag_without_exception_is_still_a_mismatch(monkeypatch: pytest.MonkeyPatch):
    """Every other image must be digest-pinned in values.yaml."""
    assert _check(monkeypatch, "2.3.1", {})
