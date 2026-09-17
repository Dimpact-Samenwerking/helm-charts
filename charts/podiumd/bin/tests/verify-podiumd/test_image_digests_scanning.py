"""scan_digest_pins, scan_version_pins, find_inconsistent_version_pins —
turn resolved repository/tag YAML lines into pin records, and flag
inconsistent (drift/duplicate) pins for the same repository. No network
access needed."""


# --- scan_digest_pins ---


def test_scan_digest_pins_quoted_and_bare(libimagedigests):
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


def test_scan_digest_pins_ignores_non_digest_tags(libimagedigests):
    lines = ["  image:", "    tag: latest"]
    assert libimagedigests.scan_digest_pins(lines) == []


def test_scan_digest_pins_resolves_split_registry_style(libimagedigests):
    """scan_digest_pins itself only cares about the resolved repository,
    used for the live lookup (see resolve_pin_repo/find_sibling_registry) —
    a split "registry:"/"repository:" pin must resolve to the same
    combined host/path a single-key pin would."""
    lines = [
        "    image:",
        "      registry: quay.io",
        "      repository: opstree/redis",
        '      tag: "v8.6.6@sha256:' + "a" * 64 + '"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert pins[0]["repository"] == "quay.io/opstree/redis"


def test_scan_digest_pins_combined_style(libimagedigests):
    lines = ["  image:", "    repository: org/repo", '    tag: "1.0.0@sha256:' + "a" * 64 + '"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert pins[0]["repository"] == "org/repo"


def test_scan_digest_pins_tolerates_anchor_tag_on_digest_pinned_line(libimagedigests):
    """A "&anchor"-decorated repository/tag pair (e.g. keycloak-operator's
    own operator.config.keycloakImage, aliased elsewhere by a sibling
    "keycloak.image" block) must resolve exactly like an un-anchored one —
    the anchor token is invisible YAML plumbing, never part of the actual
    value. No real digest-pinned anchor exists in this chart today (the
    one real anchor case — keycloak-operator's own — pins tag/sha as
    SEPARATE fields, never an embedded "@sha256:", so DIGEST_PIN_RE still
    correctly never matches it), but DIGEST_PIN_RE/VERSION_PIN_RE are
    explicitly kept in sync (see VERSION_PIN_RE's own docstring) — this
    proves that invariant holds for the anchor case too."""
    lines = ["  image:", "    repository: &repoAnchor org/repo", '    tag: &tagAnchor "1.0.0@sha256:' + "a" * 64 + '"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [("1.0.0", "a" * 64, "org/repo")]


# --- scan_version_pins ---
# Deliberately a SEPARATE scanner from scan_digest_pins (see VERSION_PIN_RE's
# own docstring) — verify-release-table-with-podiumd's own comparisons need
# it (release-table.csv never records digests at all), every other caller
# (update-image-version/verify-image-version/show-image-baseline-version)
# stays on scan_digest_pins, digest-required, completely untouched — see the
# "still digest-required" tests just above this section, all still passing
# unchanged.


def test_scan_version_pins_finds_bare_tag_with_no_digest(libimagedigests):
    """The exact real-world case that motivated this: podiumd-4.8.5 (this
    chart's own real, historical release_table baseline as of this
    writing) pinned zaakbrug/pabc/ita with plain, non-digest-pinned tags
    — scan_digest_pins is structurally blind to these (see
    test_scan_digest_pins_ignores_non_digest_tags just above), but a
    real, comparable version string is genuinely there."""
    lines = ["  image:", "    repository: wearefrank/zaakbrug", '    tag: "1.26.15"']
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.26.15", None, "wearefrank/zaakbrug"),
    ]


def test_scan_version_pins_still_finds_digest_pinned_tags(libimagedigests):
    """A real digest pin still works exactly as before — VERSION_PIN_RE is
    a strict superset of DIGEST_PIN_RE, never a replacement that could
    accidentally stop matching the digest-pinned case."""
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


def test_scan_version_pins_unquoted_bare_tag(libimagedigests):
    lines = ["  image:", "    repository: org/repo", "    tag: 1.26.15"]
    pins = libimagedigests.scan_version_pins(lines)
    assert (pins[0]["version"], pins[0]["digest"]) == ("1.26.15", None)


def test_scan_version_pins_tolerates_anchor_tag(libimagedigests):
    """Regression test (real bug, real chart): keycloak-operator's own
    operator.config.keycloakImage pins repository/tag/sha as three
    SEPARATE per-scalar YAML anchors ("repository: &keycloakImageRepo
    quay.io/keycloak/keycloak", "tag: &keycloakImageVersion \"26.7.3\"")
    -- aliased by a sibling "keycloak.image" block elsewhere in the same
    file. Before this fix, neither VERSION_PIN_RE nor ACTIVE_REPO_RE
    tolerated the leading "&anchorName " token, so this pin was
    completely invisible to basenames_under_scope_any_tag/
    resolve_image_basenames regardless of scope -- the real root cause
    behind verify-release-table-with-podiumd's own former
    special_case_tag_path workaround for basename "keycloak"."""
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


def test_scan_version_pins_ignores_non_tag_lines(libimagedigests):
    assert libimagedigests.scan_version_pins(["  repository: org/repo", "  enabled: true"]) == []


# --- find_inconsistent_version_pins ---


def test_find_inconsistent_version_pins_flags_same_repo_different_versions(libimagedigests):
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


def test_find_inconsistent_version_pins_flags_same_version_different_digest(libimagedigests):
    """The subtler case: both pins agree on the version string, but the
    digest has diverged — e.g. a sliding tag re-published upstream and
    refreshed at one spot but not the other. Invisible to a version-only
    comparison, since neither pin's version string changed at all. Still
    classified "drift" (not "duplicate") — the pins disagree, even though
    only the digest half of the pair differs."""
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


def test_find_inconsistent_version_pins_flags_matching_pins_as_duplicate(libimagedigests):
    """The same repository pinned at the same version AND digest in two
    places — every pin agrees, so this is a "duplicate" (not "drift")
    finding: there's no legitimate reason not to use a shared YAML anchor
    here instead of hand-typing the same pin twice."""
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


def test_find_inconsistent_version_pins_ignores_different_repositories(libimagedigests):
    """A shared basename across different orgs/paths is not the same
    image — must never be conflated, only an exact repository match
    counts."""
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


def test_find_inconsistent_version_pins_ignores_unresolved_repository(libimagedigests):
    lines = ["a:", "  image:", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert libimagedigests.find_inconsistent_version_pins(pins) == {}
