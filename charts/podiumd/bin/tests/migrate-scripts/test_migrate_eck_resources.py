"""charts/podiumd/scripts/migrate-eck-resources-4.10.0.py: overrides it cannot edit, quoted quantities, notes."""

import re

from collections.abc import Callable
from types import ModuleType

import pytest

NODESETS = "openinwoner:\n  eck-elasticsearch:\n    nodeSets:\n"
COMPLETE = """\
        podTemplate:
          spec:
            containers:
              - name: elasticsearch
                resources:
                  requests:
                    cpu: 250m
                    memory: 2Gi
                  limits:
                    cpu: 2000m
                    memory: 2Gi
"""


@pytest.fixture(scope="module")
def eck(script: Callable[[str], ModuleType]) -> ModuleType:
    return script("migrate-eck-resources-4.10.0.py")


def container(resources: str) -> str:
    """One node set whose elasticsearch container has the `resources` line(s)."""
    return (
        NODESETS
        + "      - name: default\n        podTemplate:\n          spec:\n            containers:\n"
        + "              - name: elasticsearch\n"
        + resources
    )


@pytest.mark.parametrize(
    ("text", "where"),
    [
        (
            NODESETS + "      - name: default\n        podTemplate:\n          spec:\n            containers:\n"
            "              - {name: elasticsearch, env: []}\n",
            "openinwoner.eck-elasticsearch.nodeSets[default].podTemplate.spec.containers[elasticsearch]",
        ),
        (
            container("                resources: {limits: {memory: 4Gi}}\n"),
            "openinwoner.eck-elasticsearch.nodeSets[default].podTemplate.spec.containers[elasticsearch].resources.limits",
        ),
        (NODESETS + "      - {name: default, count: 1}\n", "openinwoner.eck-elasticsearch.nodeSets[default]"),
    ],
    ids=["container", "resources", "node-set"],
)
def test_a_flow_style_mapping_is_refused_with_its_path(eck: ModuleType, text: str, where: str):
    with pytest.raises(eck.MigrationError, match=f"^{re.escape(where)} is a flow-style"):
        eck.migrate_text(text)


@pytest.mark.parametrize(
    ("text", "where"),
    [
        (
            container("                resources:\n"),
            "openinwoner.eck-elasticsearch.nodeSets[default].podTemplate.spec.containers[elasticsearch].resources",
        ),
        (
            NODESETS + "      - name: default\n        podTemplate:\n",
            "openinwoner.eck-elasticsearch.nodeSets[default].podTemplate",
        ),
    ],
    ids=["resources", "podTemplate"],
)
def test_a_key_without_a_value_is_refused_with_its_path(eck: ModuleType, text: str, where: str):
    with pytest.raises(eck.MigrationError, match=f"^{re.escape(where)} is not a mapping"):
        eck.migrate_text(text)


def test_a_quoted_request_copied_into_a_limit_stays_a_string(eck: ModuleType):
    text = container('                resources:\n                  requests:\n                    cpu: "3"\n')

    new, _ = eck.migrate_text(text)

    assert "                    cpu: '3'\n" in new.split("limits:\n", 1)[1]
    assert eck.migrate_text(new) == (new, [])


def test_only_node_sets_that_change_get_a_note(eck: ModuleType):
    text = NODESETS + "      - name: full\n" + COMPLETE + "      - name: partial\n        count: 1\n"

    _, notes = eck.migrate_text(text)

    assert notes == ["openinwoner.eck-elasticsearch.nodeSets[partial]: elasticsearch resources"]


def test_a_kibana_container_is_added_at_the_indent_of_the_containers_list(eck: ModuleType):
    text = "kiss-eck:\n  eck-kibana:\n    podTemplate:\n      spec:\n        containers:\n        - name: sidecar\n"

    new, notes = eck.migrate_text(text)

    assert new.startswith(text + "        - name: kibana\n          resources:\n")
    assert notes == ["kiss-eck.eck-kibana.podTemplate: kibana resources"]
