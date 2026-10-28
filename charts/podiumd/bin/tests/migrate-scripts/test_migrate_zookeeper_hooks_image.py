"""charts/podiumd/scripts/migrate-zookeeper-hooks-image-4.10.0.py: the hook image override moves to alpine/k8s."""

from types import ModuleType

import pytest

PREFIX = "zac:\n  solr-operator:\n    zookeeper-operator:\n      hooks:\n        image:\n"


def hooks_image(*lines: str) -> str:
    """A podiumd.yml whose zookeeper-operator hooks.image block holds `lines`."""
    return PREFIX + "".join(f"          {line}\n" for line in lines)


@pytest.mark.parametrize(
    ("repository", "expected"),
    [
        ("acrprodmgmt.azurecr.io/lachlanevenson/k8s-kubectl", "acrprodmgmt.azurecr.io/alpine/k8s"),
        ("acrprodmgmt.azurecr.io/k8s-kubectl", "acrprodmgmt.azurecr.io/alpine/k8s"),
        ("acrtestmgmt.azurecr.io/lachlanevenson/k8s-kubectl", "acrtestmgmt.azurecr.io/alpine/k8s"),
        ("lachlanevenson/k8s-kubectl", "docker.io/alpine/k8s"),
        ("docker.io/lachlanevenson/k8s-kubectl", "docker.io/alpine/k8s"),
        ("acrprodmgmt.azurecr.io/alpine/k8s", None),
        ("acrprodmgmt.azurecr.io/bitnami/kubectl", None),
    ],
)
def test_new_repository(zookeeper: ModuleType, repository: str, expected: str | None):
    assert zookeeper.new_repository(repository) == expected


def test_only_the_repository_value_changes(zookeeper: ModuleType):
    text = hooks_image(
        "# the ACR mirror",
        'repository: "acrprodmgmt.azurecr.io/lachlanevenson/k8s-kubectl"  # mirror',
        "pullPolicy: IfNotPresent",
    )

    new, notes = zookeeper.migrate_text(text)

    assert new == hooks_image(
        "# the ACR mirror",
        'repository: "acrprodmgmt.azurecr.io/alpine/k8s"  # mirror',
        "pullPolicy: IfNotPresent",
    )
    assert notes == [
        (
            "zac.solr-operator.zookeeper-operator.hooks.image.repository: "
            "acrprodmgmt.azurecr.io/lachlanevenson/k8s-kubectl -> acrprodmgmt.azurecr.io/alpine/k8s"
        )
    ]


def test_a_second_run_changes_nothing(zookeeper: ModuleType):
    new, _ = zookeeper.migrate_text(hooks_image("repository: acrprodmgmt.azurecr.io/k8s-kubectl"))
    assert zookeeper.migrate_text(new) == (new, [])


@pytest.mark.parametrize("repository", ["acrprodmgmt.azurecr.io/k8s-kubectl", "acrprodmgmt.azurecr.io/alpine/k8s"])
def test_a_k8s_kubectl_tag_is_an_error(zookeeper: ModuleType, repository: str):
    """alpine/k8s has no v-prefixed tags: neither repository works with v1.25.4."""
    with pytest.raises(zookeeper.MigrationError, match=r"hooks\.image\.tag is 'v1\.25\.4', a k8s-kubectl tag"):
        zookeeper.migrate_text(hooks_image(f"repository: {repository}", "tag: v1.25.4"))


def test_another_tag_than_the_charts_is_reported(zookeeper: ModuleType):
    _, notes = zookeeper.migrate_text(hooks_image("repository: acrprodmgmt.azurecr.io/k8s-kubectl", "tag: 1.36.0"))
    assert notes[0] == (
        "CHECK zac.solr-operator.zookeeper-operator.hooks.image.tag is set ('1.36.0'): "
        "it must be the chart's 1.37.1 pin, or be removed"
    )


@pytest.mark.parametrize(
    "tag", ["1.37.1", '"1.37.1@sha256:712dc5385d1c1a3f83b747fa9e40f64d433a97f72ff42f9755ff7dd1f62846e4"']
)
def test_the_charts_tag_gets_no_note(zookeeper: ModuleType, tag: str):
    _, notes = zookeeper.migrate_text(hooks_image("repository: acrprodmgmt.azurecr.io/k8s-kubectl", f"tag: {tag}"))
    assert notes == [
        (
            "zac.solr-operator.zookeeper-operator.hooks.image.repository: "
            "acrprodmgmt.azurecr.io/k8s-kubectl -> acrprodmgmt.azurecr.io/alpine/k8s"
        )
    ]


@pytest.mark.parametrize(
    "text",
    [
        "zac:\n  enabled: false\n",
        hooks_image("tag: 1.37.1"),
        hooks_image("repository: acrprodmgmt.azurecr.io/alpine/k8s"),
    ],
)
def test_nothing_to_migrate(zookeeper: ModuleType, text: str):
    assert zookeeper.migrate_text(text) == (text, [])
