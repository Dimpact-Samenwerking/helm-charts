"""Checks that an upgrade doc's own references to sibling <X>-to-<Y>-*.md
docs and images-<Z>.yaml manifests are internally consistent — used by
lib.docs_consistency.check_docs_consistency."""

import re

from lib.upgradedoc.string_and_parsing_basics import normalize_version

SIBLING_DOC_RE = re.compile(r"(\d+\.\d+\.\d+)-to-(\d+\.\d+\.\d+)-(upgrade|gemeente-specific|values-deltas)\.md")
IMAGES_REF_RE = re.compile(r"images-(\d+\.\d+\.\d+)\.yaml")


def check_pointer_consistency(doc_path, upgrade_docs_baseline, podiumd_version, doc_dir, images_dir):
    """Every reference to a sibling <X>-to-<Y>-*.md doc or an images-<Z>.yaml
    manifest found anywhere in this doc — comment, prose, or markdown link.

    Sibling-doc references may legitimately point at an EARLIER hop (e.g.
    "see the 4.8.1-to-4.8.2 guide for the older Keycloak steps"), so one
    whose target Y isn't podiumd_version is left alone; a reference that
    DOES target the current release must name the current
    upgrade_docs_baseline as its source and must exist.

    An images-<Z>.yaml reference is different: this doc's own release only
    ever has one manifest (images-<podiumd_version>.yaml), and there's no
    reason to point at another release's — so any Z != podiumd_version is
    flagged (almost always a stale reference left after a rename)."""
    text = doc_path.read_text(encoding="utf-8")
    issues = []

    for m in SIBLING_DOC_RE.finditer(text):
        from_v, to_v, suffix = m.groups()
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
