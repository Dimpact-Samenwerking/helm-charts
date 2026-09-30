"""scan_digest_pins, scan_version_pins, find_inconsistent_version_pins: pin records and drift/duplicate detection."""

from types import ModuleType

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
