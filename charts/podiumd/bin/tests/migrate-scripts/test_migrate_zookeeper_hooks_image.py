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


def test_a_tag_override_is_reported(zookeeper: ModuleType):
    _, notes = zookeeper.migrate_text(hooks_image("repository: acrprodmgmt.azurecr.io/k8s-kubectl", "tag: v1.25.4"))
    assert notes[0] == (
        "CHECK zac.solr-operator.zookeeper-operator.hooks.image.tag is set ('v1.25.4'): "
        "it must be the chart's 1.37.1 pin, or be removed"
    )


@pytest.mark.parametrize(
    "text",
    [
        "zac:\n  enabled: false\n",
        hooks_image("tag: 1.37.1"),
        hooks_image("repository: acrprodmgmt.azurecr.io/alpine/k8s"),
    ],
)
def test_nothing_to_migrate(zookeeper: ModuleType, text: str):
    assert zookeeper.migrate_text(text)[0] == text
