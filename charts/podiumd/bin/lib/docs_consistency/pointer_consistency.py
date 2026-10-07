"""Check an upgrade doc's references to sibling docs and images manifests."""

from pathlib import Path

from lib.upgradedoc.doc_names import IMAGES_MANIFEST_NAME_RE
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name_re
from lib.upgradedoc.string_and_parsing_basics import normalize_version


def check_pointer_consistency(doc_path: Path, podiumd_version: str, doc_dir: Path, images_dir: Path):
    """Every stale reference to a sibling <X>-to-<Y>-*.md doc or images-<Z>.yaml in this doc.

    A sibling-doc reference may point at an earlier hop; one targeting podiumd_version
    must exist. fix-doc-consistency already rewrote its baseline to upgrade_docs_baseline.
    Any images-<Z>.yaml with Z != podiumd_version is flagged: a release has only its own
    manifest.
    """
    text = doc_path.read_text(encoding="utf-8")
    issues = [
        f'{doc_path.name}: reference "{m.group(0)}" does not exist'
        for m in doc_name_re(podiumd_version, STANDARD_SUFFIXES).finditer(text)
        if not (doc_dir / m.group(0)).is_file()
    ]

    for m in IMAGES_MANIFEST_NAME_RE.finditer(text):
        version = m.group("target")
        if normalize_version(version) != normalize_version(podiumd_version):
            issues.append(
                f'{doc_path.name}: reference "{m.group(0)}" targets podiumd {version}, expected "{podiumd_version}"'
            )
        elif not (images_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    return issues
