"""lib.component_docs.aliased_pin_bullets — add_missing_pin_bullets."""

from typing import TYPE_CHECKING

from lib.component_docs.aliased_pin_bullets import MissingPinBullet
from lib.component_docs.aliased_pin_bullets import add_missing_pin_bullets

if TYPE_CHECKING:
    from lib.yaml_types import YamlValue

K8S: tuple[str, ...] = ("redis-operator.cron.image.tag", "redis-operator.pre.image.tag")
BAO: tuple[str, ...] = ("openbao.job.image.tag", "openbao.server.image.tag")
GROUPS: dict[str, tuple[str, ...]] = {path: group for group in (K8S, BAO) for path in group}


def baseline_with(pre: str) -> "YamlValue":
    """The baseline values, with redis-operator.pre's old tag `pre`."""
    return {
        "redis-operator": {"cron": {"image": {"tag": "1.37.0"}}, "pre": {"image": {"tag": pre}}},
        "openbao": {"job": {"image": {"tag": "2.5.4"}}, "server": {"image": {"tag": "2.5.4"}}},
    }


# Every aliased path had its documented pin's old version.
BASELINE = baseline_with("1.37.0")

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
    assert add_missing_pin_bullets(DOC, GROUPS, BASELINE)[1] == [
        MissingPinBullet("redis-operator - k8s 1.37.0 → 1.37.1", K8S[0], K8S[1]),
        MissingPinBullet("openbao 2.5.4 → 2.5.5 (chart 0.28.4, unchanged)", BAO[1], BAO[0]),
    ]


def test_add_copies_the_bullet_for_the_aliased_path():
    text, added = add_missing_pin_bullets(DOC, GROUPS, BASELINE)
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
    text, _ = add_missing_pin_bullets(DOC, GROUPS, BASELINE)
    assert not add_missing_pin_bullets(text, GROUPS, BASELINE)[1]
    assert add_missing_pin_bullets(text, GROUPS, BASELINE) == (text, [])


def test_a_hand_written_bullet_for_the_aliased_path_counts():
    doc = DOC.replace(
        "- `redis-operator.cron.image.tag` `1.37.0` → `1.37.1`\n",
        "- `redis-operator.cron.image.tag` `1.37.0` → `1.37.1`\n- `redis-operator.pre.image.tag` also bumped\n",
    )
    assert [m.missing_path for m in add_missing_pin_bullets(doc, GROUPS, BASELINE)[1]] == [BAO[0]]


def test_bullets_outside_changes_and_unaliased_paths_are_ignored():
    doc = "## Notes\n\n- `redis-operator.cron.image.tag` `1` → `2`\n\n## Changes\n\n### zac 1 → 2\n\n- `zac.image.tag` `1` → `2`\n"
    assert not add_missing_pin_bullets(doc, GROUPS, BASELINE)[1]


def test_an_alias_with_another_baseline_value_shows_its_own_version():
    """A path that joined the anchor keeps its own history in its bullet."""
    baseline = baseline_with("v1.25.4")
    text, added = add_missing_pin_bullets(DOC, GROUPS, baseline)
    assert MissingPinBullet("redis-operator - k8s 1.37.0 → 1.37.1", K8S[0], K8S[1]) in added
    assert (
        "- `redis-operator.pre.image.tag` `v1.25.4` → `1.37.1` "
        "(shares a YAML anchor with `redis-operator.cron.image.tag`)\n"
    ) in text


def test_an_alias_with_the_baseline_version_of_the_new_pin_shows_unchanged():
    """An alias already on the new version reads "(unchanged)", not the copied transition."""
    baseline = baseline_with("1.37.1")
    text, _ = add_missing_pin_bullets(DOC, GROUPS, baseline)
    assert (
        "- `redis-operator.pre.image.tag` `1.37.1` (unchanged) "
        "(shares a YAML anchor with `redis-operator.cron.image.tag`)\n"
    ) in text


def test_an_alias_with_another_baseline_value_documented_elsewhere_gets_no_bullet():
    """A path that joined the anchor and has its own section is not documented twice."""
    baseline = baseline_with("v1.25.4")
    doc = DOC + "\n### redis-operator - pre v1.25.4 → 1.37.1\n\n- `redis-operator.pre.image.tag` `v1.25.4` → `1.37.1`\n"
    assert add_missing_pin_bullets(doc, GROUPS, baseline)[1] == [
        MissingPinBullet("openbao 2.5.4 → 2.5.5 (chart 0.28.4, unchanged)", BAO[1], BAO[0]),
    ]
