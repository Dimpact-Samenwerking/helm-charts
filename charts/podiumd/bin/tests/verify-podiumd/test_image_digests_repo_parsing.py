"""parse_repo, resolve_pin_repo, find_sibling_registry — pure line-parsing
logic for resolving an image's repository string from the YAML lines
surrounding its pinned tag. No network access needed."""

from types import ModuleType

# --- parse_repo ---


def test_parse_repo_bare_docker_hub_official_image(libimagedigests: ModuleType):
    assert libimagedigests.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_bare_docker_hub_namespaced(libimagedigests: ModuleType):
    assert libimagedigests.parse_repo("nginxinc/nginx-unprivileged") == ("docker.io", "nginxinc/nginx-unprivileged")


def test_parse_repo_explicit_host(libimagedigests: ModuleType):
    assert libimagedigests.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == (
        "ghcr.io",
        "infonl/zaakafhandelcomponent",
    )


def test_parse_repo_explicit_docker_io_host(libimagedigests: ModuleType):
    assert libimagedigests.parse_repo("docker.io/alpine/k8s") == ("docker.io", "alpine/k8s")


def test_parse_repo_localhost(libimagedigests: ModuleType):
    assert libimagedigests.parse_repo("localhost/foo") == ("localhost", "foo")


# --- resolve_pin_repo ---


def test_resolve_pin_repo_active_sibling_key(libimagedigests: ModuleType):
    lines = [
        "    nginx:",
        "      repository: nginxinc/nginx-unprivileged",
        '      tag: "1.31.3@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 2, 6) == "nginxinc/nginx-unprivileged"


def test_resolve_pin_repo_tolerates_anchor_tag_on_repository_line(libimagedigests: ModuleType):
    """The real keycloak-operator shape: a sibling "repository:" key
    decorated with its own "&anchor" (aliased elsewhere) -- ACTIVE_REPO_RE
    must skip the anchor token, not treat it as part of the repository
    string itself."""
    lines = [
        "    keycloakImage:",
        "      repository: &keycloakImageRepo quay.io/keycloak/keycloak",
        '      tag: &keycloakImageVersion "26.7.3"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 2, 6) == "quay.io/keycloak/keycloak"


def test_resolve_pin_repo_active_sibling_key_with_comment_between(libimagedigests: ModuleType):
    lines = [
        "      initImage:",
        "        repository: python",
        "        # Digest-pinned to match docs/images/images-4.8.0.yaml",
        '        tag: "3.14-slim@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 8) == "python"


def test_resolve_pin_repo_ref_comment_fallback(libimagedigests: ModuleType):
    lines = [
        "  opa:",
        "    # openpolicyagent/opa:1.17.1-static@sha256:aaaa",
        "    image:",
        "      #repository: openpolicyagent/opa",
        '      tag: "1.17.1-static@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 4, 6) == "openpolicyagent/opa"


def test_resolve_pin_repo_ref_comment_tolerates_stray_at(libimagedigests: ModuleType):
    lines = [
        "        # lachlanevenson/k8s-kubectl:@v1.25.4",
        "        image:",
        "          #repository:",
        "          tag: v1.25.4@sha256:aaaa",
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 10) == "lachlanevenson/k8s-kubectl"


def test_resolve_pin_repo_commented_repository_key_fallback(libimagedigests: ModuleType):
    lines = [
        "    image:",
        "      #repository: maykinmedia/open-archiefbeheer",
        '      tag: "2.0.0@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 2, 6) == "maykinmedia/open-archiefbeheer"


def test_resolve_pin_repo_unresolved_returns_none(libimagedigests: ModuleType):
    lines = [
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 1, 4) is None


def test_resolve_pin_repo_stops_at_dedent_does_not_leak_across_blocks(libimagedigests: ModuleType):
    lines = [
        "otherBlock:",
        "  repository: should/not-be-used",
        "unrelated:",
        "  image:",
        '    tag: "1.0.0@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 4, 4) is None


def test_resolve_pin_repo_combines_split_registry_and_repository(libimagedigests: ModuleType):
    """redis-ha's actual style: registry: quay.io / repository: opstree/redis
    as two sibling keys, rather than one combined "repository:
    quay.io/opstree/redis" — must resolve to the same host/path a combined
    pin would, or the live lookup asks the wrong registry entirely."""
    lines = [
        "    image:",
        "      registry: quay.io",
        "      repository: opstree/redis",
        '      tag: "v8.6.6@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 6) == "quay.io/opstree/redis"


def test_resolve_pin_repo_registry_key_order_does_not_matter(libimagedigests: ModuleType):
    lines = [
        "    image:",
        "      repository: opstree/redis",
        "      registry: quay.io",
        '      tag: "v8.6.6@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 6) == "quay.io/opstree/redis"


# --- find_sibling_registry ---


def test_find_sibling_registry_found_at_same_indent(libimagedigests: ModuleType):
    lines = ["    image:", "      registry: quay.io", "      repository: opstree/redis"]
    assert libimagedigests.find_sibling_registry(lines, 2, 6) == "quay.io"


def test_find_sibling_registry_none_when_absent(libimagedigests: ModuleType):
    lines = ["    image:", "      repository: org/repo"]
    assert libimagedigests.find_sibling_registry(lines, 1, 6) is None


def test_find_sibling_registry_stops_at_dedent(libimagedigests: ModuleType):
    lines = ["registry: should/not-be-used", "image:", "  repository: org/repo"]
    assert libimagedigests.find_sibling_registry(lines, 2, 2) is None
