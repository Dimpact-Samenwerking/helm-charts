"""check_image_repository / find_images_without_repository — every
"image: {tag: ...}" block in values.yaml must resolve to an actual
repository, either podiumd's own override or the owning dependency's
vendored subchart default (see lib.chart.repository_path_map), else the
podiumd.image template helper renders a malformed "<empty>:<tag>"
reference. The real-world case this exists for: kiss.adapter.image's
own "repository:" is commented out in podiumd's values.yaml, and the
vendored kiss-chart subchart has no "adapter" key in its own defaults
either."""
import io
import tarfile

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


def test_no_values_yaml_passes(vp, tmp_path):
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_own_repository_set_passes(vp, tmp_path):
    write_chart_yaml(tmp_path, [make_dep("redis-operator", "0.26.1")])
    write_values_yaml(tmp_path, f"""\
redis-operator:
  redis-ha:
    image:
      repository: quay.io/opstree/redis
      tag: "8.6.6@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_repository_resolved_via_vendored_subchart_default_passes(vp, tmp_path):
    write_chart_yaml(tmp_path, [make_dep("zaakafhandelcomponent", "1.0.297", alias="zac")])
    make_tgz(tmp_path / "charts", "zaakafhandelcomponent", "1.0.297",
             {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "1.0.297"}})
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    tag: "5.4.4@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_missing_repository_everywhere_is_reported(vp, tmp_path, capsys):
    """kiss.adapter.image's own real-world shape: no own override, and
    the vendored subchart's own defaults have no matching key either."""
    write_chart_yaml(tmp_path, [make_dep("kiss-chart", "3.0.0", alias="kiss")])
    make_tgz(tmp_path / "charts", "kiss-chart", "3.0.0", {"image": {"repository": "ghcr.io/x/kiss", "tag": "3.0.0"}})
    write_values_yaml(tmp_path, f"""\
kiss:
  adapter:
    image:
      tag: "0.6.7@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    assert detail == "1 image(s) with no resolvable repository"
    out = capsys.readouterr().out
    assert "kiss.adapter.image" in out


def test_dependency_not_yet_vendored_is_reported(vp, tmp_path):
    """No .tgz on disk, no own override either — genuinely unresolvable,
    same as check_subchart_image_visibility's own "not vendored" case
    but a real failure here, not just a report."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    write_values_yaml(tmp_path, f"""\
openzaak:
  image:
    tag: "3.30.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    assert detail == "1 image(s) with no resolvable repository"


def test_global_shared_image_with_own_repository_passes(vp, tmp_path):
    """A "global.*" anchor is checked against podiumd's own values.yaml
    only — never a subchart fallback, same convention
    lib.chart.canonical_sidecar_row_names itself uses for this shape."""
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, f"""\
global:
  images:
    curlImage:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_global_shared_image_without_repository_is_reported(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, f"""\
global:
  images:
    curlImage:
      tag: "8.21.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    out = capsys.readouterr().out
    assert "global.images.curlImage" in out


def test_nested_sidecar_repository_resolved_via_subchart_default(vp, tmp_path):
    """A sub-chart default nested under more than one key (a sidecar)
    resolves via the SAME nested path in the vendored default, not just
    the top-level scope."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
             {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, f"""\
openzaak:
  redis:
    image:
      tag: "8.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True
    assert detail == "0 missing repository"


def test_multiple_missing_images_all_reported(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [make_dep("redis-operator", "0.26.1"), make_dep("openzaak", "1.14.2")])
    write_values_yaml(tmp_path, f"""\
redis-operator:
  redis-ha:
    image:
      tag: "8.6.6@sha256:{DIGEST_A}"
openzaak:
  image:
    tag: "3.30.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    assert detail == "2 image(s) with no resolvable repository"
    out = capsys.readouterr().out
    assert "redis-operator.redis-ha.image" in out
    assert "openzaak.image" in out
