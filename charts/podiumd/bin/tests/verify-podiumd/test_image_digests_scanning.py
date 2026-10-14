"""scan_digest_pins, scan_version_pins, scan_image_pins, find_inconsistent_version_pins: pin records and drift/duplicate detection."""

from pathlib import Path
from types import ModuleType

import yaml

# --- scan_digest_pins ---


def test_scan_digest_pins_quoted_and_bare(libimagedigests: ModuleType):
    lines = [
        "  a:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    repository: org/repo-b",
        "    tag: 2.0.0@sha256:" + "b" * 64,
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.0.0", "a" * 64, "org/repo-a"),
        ("2.0.0", "b" * 64, "org/repo-b"),
    ]
    assert pins[0]["line"] == 3
    assert pins[1]["line"] == 6


def test_scan_digest_pins_ignores_non_digest_tags(libimagedigests: ModuleType):
    lines = ["  image:", "    tag: latest"]
    assert libimagedigests.scan_digest_pins(lines) == []


def test_scan_digest_pins_resolves_split_registry_style(libimagedigests: ModuleType):
    """A split "registry:"/"repository:" pin resolves to the same host/path as a single-key pin."""
    lines = [
        "    image:",
        "      registry: quay.io",
        "      repository: opstree/redis",
        '      tag: "v8.6.6@sha256:' + "a" * 64 + '"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert pins[0]["repository"] == "quay.io/opstree/redis"


def test_scan_digest_pins_combined_style(libimagedigests: ModuleType):
    lines = ["  image:", "    repository: org/repo", '    tag: "1.0.0@sha256:' + "a" * 64 + '"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert pins[0]["repository"] == "org/repo"


def test_scan_digest_pins_tolerates_anchor_tag_on_digest_pinned_line(libimagedigests: ModuleType):
    """A "&anchor"-decorated repository/tag pair resolves like an un-anchored one.

    Keeps DIGEST_PIN_RE in sync with VERSION_PIN_RE's anchor tolerance.
    """
    lines = ["  image:", "    repository: &repoAnchor org/repo", '    tag: &tagAnchor "1.0.0@sha256:' + "a" * 64 + '"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [("1.0.0", "a" * 64, "org/repo")]


# --- scan_version_pins ---
# Separate from scan_digest_pins: release-table.csv has no digests, so tag-only pins count.


def test_scan_version_pins_finds_bare_tag_with_no_digest(libimagedigests: ModuleType):
    """Plain tag pins (e.g. podiumd-4.8.5 zaakbrug/pabc/ita), invisible to scan_digest_pins, are found."""
    lines = ["  image:", "    repository: wearefrank/zaakbrug", '    tag: "1.26.15"']
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.26.15", None, "wearefrank/zaakbrug"),
    ]


def test_scan_version_pins_still_finds_digest_pinned_tags(libimagedigests: ModuleType):
    """Digest pins still match: VERSION_PIN_RE is a superset of DIGEST_PIN_RE."""
    lines = [
        "  a:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    repository: org/repo-b",
        "    tag: 2.0.0@sha256:" + "b" * 64,
    ]
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.0.0", "a" * 64, "org/repo-a"),
        ("2.0.0", "b" * 64, "org/repo-b"),
    ]


def test_scan_version_pins_unquoted_bare_tag(libimagedigests: ModuleType):
    lines = ["  image:", "    repository: org/repo", "    tag: 1.26.15"]
    pins = libimagedigests.scan_version_pins(lines)
    assert (pins[0]["version"], pins[0]["digest"]) == ("1.26.15", None)


def test_scan_version_pins_tolerates_anchor_tag(libimagedigests: ModuleType):
    """Per-scalar anchors ("repository: &keycloakImageRepo ...") must not hide a pin.

    Regression: keycloak-operator's operator.config.keycloakImage was invisible to
    VERSION_PIN_RE/ACTIVE_REPO_RE because of the "&anchorName " token.
    """
    lines = [
        "keycloak-operator:",
        "  operator:",
        "    config:",
        "      keycloakImage:",
        "        repository: &keycloakImageRepo quay.io/keycloak/keycloak",
        '        tag: &keycloakImageVersion "26.7.3"',
        '        sha: &keycloakImageDigest "' + "a" * 64 + '"',
    ]
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("26.7.3", None, "quay.io/keycloak/keycloak"),
    ]


def test_scan_version_pins_finds_registered_split_field_pins(libimagedigests: ModuleType):
    """redis-operator pins "imageTag:"/"initContainerImageTag:" next to "imageName:"; both are pins."""
    digest = "a" * 64
    lines = [
        "  redisOperator:",
        "    imageName: quay.io/opstree/redis-operator",
        f'    imageTag: "v0.26.0@sha256:{digest}"',
        f'    initContainerImageTag: "v0.26.0@sha256:{digest}"',
        '    otherTag: "v1.0.0"',
    ]
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["line"], p["repository"], p["version"]) for p in pins] == [
        (3, "quay.io/opstree/redis-operator", "v0.26.0"),
        (4, "quay.io/opstree/redis-operator", "v0.26.0"),
    ]


def test_scan_version_pins_reads_an_anchored_split_field_and_skips_its_alias(libimagedigests: ModuleType):
    lines = [
        "  redisOperator:",
        "    imageName: quay.io/opstree/redis-operator",
        f'    imageTag: &redisOperatorImageTag "v0.26.0@sha256:{"a" * 64}"',
        "    initContainerImageTag: *redisOperatorImageTag",
    ]
    assert [p["line"] for p in libimagedigests.scan_digest_pins(lines)] == [3]


def test_scan_version_pins_skips_a_split_field_without_its_repository_field(libimagedigests: ModuleType):
    assert libimagedigests.scan_version_pins(["  redisOperator:", '    imageTag: "v0.26.0"']) == []


def test_scan_version_pins_ignores_non_tag_lines(libimagedigests: ModuleType):
    assert libimagedigests.scan_version_pins(["  repository: org/repo", "  enabled: true"]) == []


# --- find_inconsistent_version_pins ---


def test_find_inconsistent_version_pins_flags_same_repo_different_versions(libimagedigests: ModuleType):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.20.0@sha256:{"b" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    drift = libimagedigests.find_inconsistent_version_pins(pins)
    assert drift == {
        "curlimages/curl": {
            "kind": "drift",
            "pins": [(("8.21.0", "a" * 64), [4]), (("8.20.0", "b" * 64), [8])],
        }
    }


def test_find_inconsistent_version_pins_flags_same_version_different_digest(libimagedigests: ModuleType):
    """Same version, diverged digest (sliding tag refreshed in one spot) is "drift", not "duplicate"."""
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"b" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    drift = libimagedigests.find_inconsistent_version_pins(pins)
    assert drift == {
        "curlimages/curl": {
            "kind": "drift",
            "pins": [(("8.21.0", "a" * 64), [4]), (("8.21.0", "b" * 64), [8])],
        }
    }


def test_find_inconsistent_version_pins_flags_matching_pins_as_duplicate(libimagedigests: ModuleType):
    """Identical version and digest in two places is a "duplicate": should be a shared YAML anchor."""
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    drift = libimagedigests.find_inconsistent_version_pins(pins)
    assert drift == {"curlimages/curl": {"kind": "duplicate", "pins": [(("8.21.0", "a" * 64), [4, 8])]}}


def test_find_inconsistent_version_pins_ignores_different_repositories(libimagedigests: ModuleType):
    """Same basename under different orgs is a different image; only exact repository matches count."""
    lines = [
        "a:",
        "  image:",
        "    repository: orgone/tool",
        f'    tag: "1.0.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: orgtwo/tool",
        f'    tag: "2.0.0@sha256:{"b" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert libimagedigests.find_inconsistent_version_pins(pins) == {}


def test_find_inconsistent_version_pins_ignores_unresolved_repository(libimagedigests: ModuleType):
    lines = ["a:", "  image:", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert libimagedigests.find_inconsistent_version_pins(pins) == {}


# --- scan_image_pins / image targets ---

KEYCLOAK_VALUES = f"""\
keycloak:
  image:
    repository: &kcRepo quay.io/keycloak/keycloak
    tag: &kcVersion "26.7.3"
    sha: &kcDigest "{"a" * 64}"
keycloak-operator:
  operator:
    config:
      keycloakImage:
        repository: *kcRepo
        tag: *kcVersion
        sha: *kcDigest
"""


def test_scan_image_pins_reads_a_registered_sibling_digest(libimagedigests: ModuleType, tmp_path: Path):
    """keycloak's digest is in "sha:", not in the tag, and the pin reports that line; the aliased
    operator copy reports the anchor's line."""
    (tmp_path / "values.yaml").write_text(KEYCLOAK_VALUES, encoding="utf-8")
    pins = libimagedigests.scan_image_pins(tmp_path)
    assert [(p["path"], p["line"], p["version"], p["digest"], p["repository"]) for p in pins] == [
        (("keycloak", "image"), 5, "26.7.3", "a" * 64, "quay.io/keycloak/keycloak"),
        (
            ("keycloak-operator", "operator", "config", "keycloakImage"),
            5,
            "26.7.3",
            "a" * 64,
            "quay.io/keycloak/keycloak",
        ),
    ]


def test_digest_pin_targets_include_sibling_digest_pins(libimagedigests: ModuleType, tmp_path: Path):
    (tmp_path / "values.yaml").write_text(KEYCLOAK_VALUES, encoding="utf-8")
    pins, targets = libimagedigests.digest_pin_targets(tmp_path)
    assert len(pins) == 2
    assert targets == {("quay.io/keycloak/keycloak", "26.7.3"): ("a" * 64, [5])}


def test_find_inconsistent_version_pins_reports_drift_between_literal_sibling_digests(
    libimagedigests: ModuleType, tmp_path: Path
):
    """One aliased tag, two literal "sha:" values: drift, though both pins share the tag's line."""
    values = KEYCLOAK_VALUES.replace("sha: *kcDigest", f'sha: "{"b" * 64}"')
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    findings = libimagedigests.find_inconsistent_version_pins(libimagedigests.scan_image_pins(tmp_path))
    assert findings["quay.io/keycloak/keycloak"]["kind"] == "drift"
    assert sorted(line for _pair, lines in findings["quay.io/keycloak/keycloak"]["pins"] for line in lines) == [5, 12]


def test_find_inconsistent_version_pins_ignores_aliases_of_one_anchor(libimagedigests: ModuleType, tmp_path: Path):
    """Two paths aliasing one anchor are one literal pin, not a [DUPLICATE-PIN]."""
    (tmp_path / "values.yaml").write_text(KEYCLOAK_VALUES, encoding="utf-8")
    assert libimagedigests.find_inconsistent_version_pins(libimagedigests.scan_image_pins(tmp_path)) == {}


def test_unique_image_targets_include_a_digest_less_version_field(libimagedigests: ModuleType, tmp_path: Path):
    """A registered version field without a digest (redis-operator imageTag) is still an image to check."""
    (tmp_path / "Chart.yaml").write_text(
        yaml.safe_dump({"dependencies": [{"name": "redis-operator", "version": "0.26.1"}]}), encoding="utf-8"
    )
    (tmp_path / "values.yaml").write_text(
        'redis-operator:\n  redisOperator:\n    imageName: quay.io/opstree/redis-operator\n    imageTag: "v0.26.0"\n',
        encoding="utf-8",
    )
    targets = libimagedigests.unique_image_targets(tmp_path)
    assert targets[("quay.io/opstree/redis-operator", "v0.26.0")] == (None, 4)
