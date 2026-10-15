"""Per-strategy tag writers in update-component-version, called directly with a minimal context."""

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import PinPath
from lib.chart.registered_paths import pin_paths_for

DIGEST = "sha256:" + "e" * 64


def image_pins(*paths: str) -> list[PinPath]:
    """PinPaths for "image:" blocks at `paths`."""
    return [PinPath(path, f"{path}.tag") for path in paths]


KEYCLOAK_CHECKED = {
    "path": "image",
    "repository": "quay.io/keycloak/keycloak",
    "host": "quay.io",
    "repo_path": "keycloak/keycloak",
    "exists": True,
    "digest": DIGEST,
}


def _ctx(values: dict[str, object], **extra: object) -> SimpleNamespace:
    return SimpleNamespace(values=values, values_key="keycloak", app_version="26.7.3", **extra)


def test_write_split_tag_sha_pin_leaves_an_alias_tag_line(ucv: ModuleType):
    """An alias-reference tag line keeps resolving to its anchor."""
    values_lines = [
        "keycloak:\n",
        "  image:\n",
        "    repository: quay.io/keycloak/keycloak\n",
        "    tag: *keycloakImageVersion\n",
        "    sha: *keycloakImageDigest\n",
    ]
    ctx = _ctx({"keycloak": {"image": {"repository": "quay.io/keycloak/keycloak"}}})

    ucv._write_split_tag_sha_pin(ctx, values_lines, "image", "sha", KEYCLOAK_CHECKED)

    assert values_lines[3] == "    tag: *keycloakImageVersion\n"


def test_write_split_tag_sha_pin_writes_tag_and_sha(ucv: ModuleType):
    values_lines = [
        "keycloak:\n",
        "  image:\n",
        "    repository: quay.io/keycloak/keycloak\n",
        '    tag: "26.7.2"\n',
    ]
    ctx = _ctx({"keycloak": {"image": {"repository": "quay.io/keycloak/keycloak"}}})

    ucv._write_split_tag_sha_pin(ctx, values_lines, "image", "sha", KEYCLOAK_CHECKED)

    assert values_lines[3] == '    tag: "26.7.3"\n'
    assert values_lines[4] == f'    sha: "{DIGEST.removeprefix("sha256:")}"\n'


def test_plan_delegated_tags_exits_cleanly_when_own_line_unchanged(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No change at the path or anything sharing its value must raise SystemExit with a message."""
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("zac:\n  image:\n    repository: ghcr.io/infonl/zac\n    tag: 5.4.3\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(ucv, "plan_image_version_update", lambda *args: [])
    ctx = SimpleNamespace(
        values={"zac": {"image": {"repository": "ghcr.io/infonl/zac"}}}, values_key="zac", app_version="5.4.3", dep=None
    )

    with pytest.raises(SystemExit, match=r"no pin to update for zac\.image\.tag"):
        ucv._plan_delegated_tags(ctx, image_pins("image"))


OLD_DIGEST = "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64

# openbao in 4.9.3: server.image.tag is a bare alias of the job image's anchored literal.
OPENBAO_VALUES = f"""\
openbao:
  configuration:
    job:
      image:
        repository: quay.io/openbao/openbao
        tag: &openbaoImageTag "2.5.5@sha256:{OLD_DIGEST}"
  server:
    image:
      registry: quay.io
      repository: quay.io/openbao/openbao
      tag: *openbaoImageTag
"""

# redis-ha: preDeleteJob.image aliases the whole image mapping, so it has no tag: line.
REDIS_VALUES = f"""\
redis-operator:
  cron:
    image: &k8s
      repository: docker.io/alpine/k8s
      tag: "1.37.0@sha256:{OLD_DIGEST}"
  pre:
    image: *k8s
"""

# Two literal pins of one basename, no alias.
TWO_LITERALS_VALUES = f"""\
zac:
  a:
    image:
      repository: ghcr.io/x/tool
      tag: "1.0.0@sha256:{OLD_DIGEST}"
  b:
    image:
      repository: ghcr.io/x/tool
      tag: "1.0.0@sha256:{OLD_DIGEST}"
"""


def _bump_delegated(
    ucv: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    key: str,
    pins: list[PinPath],
    version: str,
    dep: ChartDependency | None = None,
):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(text, encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr("lib.image.version.registry_tag_exists", lambda host, repo, tag: (True, NEW_DIGEST))
    ctx = SimpleNamespace(values=ucv.load_yaml_mapping(values_yaml), values_key=key, app_version=version, dep=dep)
    ucv._write_delegated_tags(ctx, ucv._plan_delegated_tags(ctx, pins))
    return values_yaml.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "paths", [["server.image", "configuration.job.image"], ["configuration.job.image", "server.image"]]
)
def test_delegated_alias_and_anchor_paths_bump_once_in_either_order(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths: list[str]
):
    text = _bump_delegated(ucv, tmp_path, monkeypatch, OPENBAO_VALUES, "openbao", image_pins(*paths), "2.6.3")
    assert text == OPENBAO_VALUES.replace(f"2.5.5@sha256:{OLD_DIGEST}", f"2.6.3@{NEW_DIGEST}")
    assert "tag: *openbaoImageTag" in text


def test_delegated_mapping_alias_path_is_written_through_its_anchor(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    text = _bump_delegated(
        ucv, tmp_path, monkeypatch, REDIS_VALUES, "redis-operator", image_pins("pre.image"), "1.37.1"
    )
    assert f'tag: "1.37.1@{NEW_DIGEST}"' in text


def test_two_literal_delegated_pins_of_one_basename_are_both_written(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    text = _bump_delegated(
        ucv, tmp_path, monkeypatch, TWO_LITERALS_VALUES, "zac", image_pins("a.image", "b.image"), "1.1.0"
    )
    assert text.count(f"1.1.0@{NEW_DIGEST}") == 2


def test_resolve_error_leaves_values_yaml_untouched(ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The second basename's tag is missing upstream: nothing may be written for the first."""
    text = OPENBAO_VALUES + REDIS_VALUES.replace("redis-operator:\n", "  extra:\n").replace("\n  ", "\n    ")
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text(text, encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)

    def exists(host: str, repo: str, tag: str) -> tuple[bool, str | None]:
        return (repo.endswith("openbao"), NEW_DIGEST)

    monkeypatch.setattr("lib.image.version.registry_tag_exists", exists)
    ctx = SimpleNamespace(
        values=ucv.load_yaml_mapping(values_yaml), values_key="openbao", app_version="9.9.9", dep=None
    )
    with pytest.raises(SystemExit, match="not found upstream"):
        ucv._plan_delegated_tags(ctx, image_pins("server.image", "extra.cron.image"))
    assert values_yaml.read_text(encoding="utf-8") == text


# redis-operator 4.10.0: split "imageName:"/"imageTag:" fields, no "image:" block.
REDIS_OPERATOR_VALUES = f"""\
redis-operator:
  redisOperator:
    imageName: quay.io/opstree/redis-operator
    imageTag: "v0.26.0@sha256:{OLD_DIGEST}"
    initContainerImageTag: "v0.26.0@sha256:{OLD_DIGEST}"
"""


def test_split_version_fields_are_written_through_the_registered_repository_field(
    ucv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The registered imageTag/initContainerImageTag pins bump together, their repository read from imageName."""
    dep: ChartDependency = {"name": "redis-operator", "version": "0.26.1", "repository": "@ot-helm"}
    pins = pin_paths_for("redis-operator")
    text = _bump_delegated(
        ucv, tmp_path, monkeypatch, REDIS_OPERATOR_VALUES, "redis-operator", pins, "v0.27.0", dep=dep
    )
    assert text == REDIS_OPERATOR_VALUES.replace(f"v0.26.0@sha256:{OLD_DIGEST}", f"v0.27.0@{NEW_DIGEST}")
