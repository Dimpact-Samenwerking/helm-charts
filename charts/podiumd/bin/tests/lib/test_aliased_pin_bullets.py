"""lib.component_docs.aliased_pin_bullets — add_missing_pin_bullets."""

from typing import TYPE_CHECKING

from lib.component_docs.aliased_pin_bullets import MissingPinBullet
from lib.component_docs.aliased_pin_bullets import add_missing_pin_bullets
from lib.component_docs.aliased_pin_bullets import same_baseline_alias_groups

if TYPE_CHECKING:
    from lib.yaml_types import YamlValue

K8S: tuple[str, ...] = ("redis-operator.cron.image.tag", "redis-operator.pre.image.tag")
BAO: tuple[str, ...] = ("openbao.job.image.tag", "openbao.server.image.tag")
GROUPS: dict[str, tuple[str, ...]] = {path: group for group in (K8S, BAO) for path in group}

DOC = """\
# Upgrade guide

## Changes

### redis-operator - k8s 1.37.0 → 1.37.1

PodiumD 4.9.3 upgrades the **redis-operator - k8s** image to 1.37.1,
pinned at:

- `redis-operator.cron.image.tag` `1.37.0` → `1.37.1`

- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).

### openbao 2.5.4 → 2.5.5 (chart 0.28.4, unchanged)

PodiumD 4.9.3 upgrades **openbao** from app version 2.5.4
to 2.5.5.

- Image tag pin `openbao.server.image.tag` `2.5.4` → `2.5.5` in
  `charts/podiumd/values.yaml`.
- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).
"""


def test_add_reports_each_aliased_path_without_a_bullet():
    assert add_missing_pin_bullets(DOC, GROUPS)[1] == [
        MissingPinBullet("redis-operator - k8s 1.37.0 → 1.37.1", K8S[0], K8S[1]),
        MissingPinBullet("openbao 2.5.4 → 2.5.5 (chart 0.28.4, unchanged)", BAO[1], BAO[0]),
    ]


def test_add_copies_the_bullet_for_the_aliased_path():
    text, added = add_missing_pin_bullets(DOC, GROUPS)
    assert len(added) == 2
    assert (
        "- `redis-operator.cron.image.tag` `1.37.0` → `1.37.1`\n"
        "- `redis-operator.pre.image.tag` `1.37.0` → `1.37.1` "
        "(shares a YAML anchor with `redis-operator.cron.image.tag`)\n\n"
    ) in text
    # A two-line component bullet keeps " in" + its continuation line.
    assert (
        "  `charts/podiumd/values.yaml`.\n"
        "- Image tag pin `openbao.job.image.tag` `2.5.4` → `2.5.5` "
        "(shares a YAML anchor with `openbao.server.image.tag`) in\n"
        "  `charts/podiumd/values.yaml`.\n"
        "- Image / digest"
    ) in text


def test_add_is_idempotent():
    text, _ = add_missing_pin_bullets(DOC, GROUPS)
    assert not add_missing_pin_bullets(text, GROUPS)[1]
    assert add_missing_pin_bullets(text, GROUPS) == (text, [])


def test_a_hand_written_bullet_for_the_aliased_path_counts():
    doc = DOC.replace(
        "- `redis-operator.cron.image.tag` `1.37.0` → `1.37.1`\n",
        "- `redis-operator.cron.image.tag` `1.37.0` → `1.37.1`\n- `redis-operator.pre.image.tag` also bumped\n",
    )
    assert [m.missing_path for m in add_missing_pin_bullets(doc, GROUPS)[1]] == [BAO[0]]


def test_bullets_outside_changes_and_unaliased_paths_are_ignored():
    doc = "## Notes\n\n- `redis-operator.cron.image.tag` `1` → `2`\n\n## Changes\n\n### zac 1 → 2\n\n- `zac.image.tag` `1` → `2`\n"
    assert not add_missing_pin_bullets(doc, GROUPS)[1]


def test_an_alias_with_another_baseline_value_gets_no_copied_bullet():
    baseline: YamlValue = {
        "redis-operator": {"cron": {"image": {"tag": "1.37.0"}}, "pre": {"image": {"tag": "v1.25.4"}}}
    }
    groups = same_baseline_alias_groups(GROUPS, baseline)
    assert K8S[1] not in groups[K8S[0]]
    assert K8S[0] not in groups[K8S[1]]
    assert add_missing_pin_bullets(DOC, groups)[1] == [
        MissingPinBullet("openbao 2.5.4 → 2.5.5 (chart 0.28.4, unchanged)", BAO[1], BAO[0]),
    ]


def test_an_alias_with_the_same_baseline_value_keeps_its_copied_bullet():
    baseline: YamlValue = {
        "redis-operator": {"cron": {"image": {"tag": "1.37.0"}}, "pre": {"image": {"tag": "1.37.0"}}}
    }
    assert K8S[1] in same_baseline_alias_groups(GROUPS, baseline)[K8S[0]]
