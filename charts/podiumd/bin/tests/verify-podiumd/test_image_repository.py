"""check_image_repository / find_images_without_repository: every
"image: {tag: ...}" block must resolve a repository (own override or the
vendored subchart default), else podiumd.image renders "<empty>:<tag>"."""

import io
import tarfile

from pathlib import Path
from types import ModuleType

import pytest
import yaml

from dep_helpers import make_dep

DIGEST_A = "a" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def make_tgz(charts_dir, name, version, values):
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def test_no_values_yaml_passes(vp: ModuleType, tmp_path: Path):
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_own_repository_set_passes(vp: ModuleType, tmp_path: Path):
    write_chart_yaml(tmp_path, [make_dep("redis-operator", "0.26.1")])
    write_values_yaml(
        tmp_path,
        f"""\
redis-operator:
  redis-ha:
    image:
      repository: quay.io/opstree/redis
      tag: "8.6.6@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_repository_resolved_via_vendored_subchart_default_passes(vp: ModuleType, tmp_path: Path):
    write_chart_yaml(tmp_path, [make_dep("zaakafhandelcomponent", "1.0.297", alias="zac")])
    make_tgz(
        tmp_path / "charts",
        "zaakafhandelcomponent",
        "1.0.297",
        {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "1.0.297"}},
    )
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    tag: "5.4.4@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_missing_repository_everywhere_is_reported(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """No own override and no matching key in the vendored defaults."""
    write_chart_yaml(tmp_path, [make_dep("kiss-chart", "3.0.0", alias="kiss")])
    make_tgz(tmp_path / "charts", "kiss-chart", "3.0.0", {"image": {"repository": "ghcr.io/x/kiss", "tag": "3.0.0"}})
    write_values_yaml(
        tmp_path,
        f"""\
kiss:
  adapter:
    image:
      tag: "0.6.7@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    assert detail == "1 image(s) with no resolvable repository"
    out = capsys.readouterr().out
    assert "kiss.adapter.image" in out


def test_dependency_not_yet_vendored_is_reported(vp: ModuleType, tmp_path: Path):
    """No .tgz and no own override: a failure, not just a report."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    write_values_yaml(
        tmp_path,
        f"""\
openzaak:
  image:
    tag: "3.30.0@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    assert detail == "1 image(s) with no resolvable repository"


def test_global_shared_image_with_own_repository_passes(vp: ModuleType, tmp_path: Path):
    """A "global.*" anchor is checked against podiumd's own values only."""
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    curlImage:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_global_shared_image_without_repository_is_reported(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    curlImage:
      tag: "8.21.0@sha256:{DIGEST_A}"
""",
    )
    ok, _detail = vp.check_image_repository(tmp_path)
    assert ok is False
    out = capsys.readouterr().out
    assert "global.images.curlImage" in out


def test_orphan_top_level_block_with_own_repository_passes(vp: ModuleType, tmp_path: Path):
    """Regression: a top-level block with no Chart.yaml dependency (rendered
    from podiumd's own templates) is checked against its own value, not
    treated as missing. "keycloak" must not be confused with the
    "keycloak-operator" dependency."""
    write_chart_yaml(tmp_path, [make_dep("keycloak-operator", "1.12.1")])
    write_values_yaml(
        tmp_path,
        f"""\
keycloak:
  image:
    repository: quay.io/keycloak/keycloak
    tag: "26.7.2@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True, detail
    assert detail == "0 missing repository"


def test_orphan_top_level_block_without_repository_is_reported(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
apiproxy:
  image:
    tag: "1.31.4@sha256:{DIGEST_A}"
""",
    )
    ok, _detail = vp.check_image_repository(tmp_path)
    assert ok is False
    out = capsys.readouterr().out
    assert "apiproxy.image" in out


def test_nested_sidecar_repository_resolved_via_subchart_default(vp: ModuleType, tmp_path: Path):
    """A nested sidecar default resolves via the same nested path in the
    vendored default."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(
        tmp_path,
        f"""\
openzaak:
  redis:
    image:
      tag: "8.0@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_multiple_missing_images_all_reported(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    write_chart_yaml(tmp_path, [make_dep("redis-operator", "0.26.1"), make_dep("openzaak", "1.14.2")])
    write_values_yaml(
        tmp_path,
        f"""\
redis-operator:
  redis-ha:
    image:
      tag: "8.6.6@sha256:{DIGEST_A}"
openzaak:
  image:
    tag: "3.30.0@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    assert detail == "2 image(s) with no resolvable repository"
    out = capsys.readouterr().out
    assert "redis-operator.redis-ha.image" in out
    assert "openzaak.image" in out


def test_multiple_paths_sharing_the_same_repository_are_all_resolved(vp: ModuleType, tmp_path: Path):
    """Regression: several paths pinning the same repository (a YAML anchor)
    each resolve independently; a repository-keyed map collapsed them to one
    survivor and flagged the rest as missing."""
    write_chart_yaml(
        tmp_path,
        [
            make_dep("openarchiefbeheer", "2.0.0"),
            make_dep("openklant", "1.11.0"),
            make_dep("openformulieren", "1.12.0"),
        ],
    )
    write_values_yaml(
        tmp_path,
        f"""\
openarchiefbeheer:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
openklant:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
openformulieren:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
""",
    )
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True, detail
    assert detail == "0 missing repository"
