"""Check an upgrade doc's references to sibling docs and images manifests."""

import re

from pathlib import Path

from lib.upgradedoc.string_and_parsing_basics import normalize_version

SIBLING_DOC_RE = re.compile(r"(\d+\.\d+\.\d+)-to-(\d+\.\d+\.\d+)-(upgrade|gemeente-specific|values-deltas)\.md")
IMAGES_REF_RE = re.compile(r"images-(\d+\.\d+\.\d+)\.yaml")


def check_pointer_consistency(
    doc_path: Path, upgrade_docs_baseline: str, podiumd_version: str, doc_dir: Path, images_dir: Path
):
    """Every stale reference to a sibling <X>-to-<Y>-*.md doc or images-<Z>.yaml in this doc.

    A sibling-doc reference may point at an earlier hop; one targeting podiumd_version
    must name the current upgrade_docs_baseline and exist. Any images-<Z>.yaml with
    Z != podiumd_version is flagged: a release has only its own manifest.
    """
    text = doc_path.read_text(encoding="utf-8")
    issues: list[str] = []

    for m in SIBLING_DOC_RE.finditer(text):
        from_v, to_v, _suffix = m.groups()
        if normalize_version(to_v) != normalize_version(podiumd_version):
            continue
        if normalize_version(from_v) != normalize_version(upgrade_docs_baseline):
            issues.append(
                f'{doc_path.name}: reference "{m.group(0)}" targets podiumd '
                f'{podiumd_version} but its upgrade_docs_baseline is "{from_v}", expected "{upgrade_docs_baseline}"'
            )
        elif not (doc_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    for m in IMAGES_REF_RE.finditer(text):
        version = m.group(1)
        if normalize_version(version) != normalize_version(podiumd_version):
            issues.append(
                f'{doc_path.name}: reference "{m.group(0)}" targets podiumd {version}, expected "{podiumd_version}"'
            )
        elif not (images_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    return issues
