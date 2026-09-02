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


def test_orphan_top_level_block_with_own_repository_passes(vp, tmp_path):
    """Regression test: a top-level values.yaml block with NO matching
    Chart.yaml dependency at all (podiumd's own directly-templated
    resources, e.g. the real "keycloak"/"apiproxy"/"frankgateway"
    blocks — real Deployments rendered straight from podiumd's own
    templates/*.yaml, never a vendored subchart) must still be checked
    against podiumd's own value — "no owning dependency" must never by
    itself mean "missing" the way it first did here, treating every one
    of these as broken even though each has a perfectly real repository
    of its own. "keycloak" deliberately shares a name with the REAL
    "keycloak-operator" dependency's own alias-less top-level key to
    prove they're not confused with each other."""
    write_chart_yaml(tmp_path, [make_dep("keycloak-operator", "1.12.1")])
    write_values_yaml(tmp_path, f"""\
keycloak:
  image:
    repository: quay.io/keycloak/keycloak
    tag: "26.7.2@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True, detail
    assert detail == "0 missing repository"


def test_orphan_top_level_block_without_repository_is_reported(vp, tmp_path, capsys):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, f"""\
apiproxy:
  image:
    tag: "1.31.4@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is False
    out = capsys.readouterr().out
    assert "apiproxy.image" in out


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


def test_multiple_paths_sharing_the_same_repository_are_all_resolved(vp, tmp_path):
    """Regression test: several own-override paths that happen to pin
    the EXACT same repository (e.g. a shared nginx image aliased via a
    YAML anchor across multiple components) must each be recognized as
    resolved independently — an earlier implementation reused
    lib.chart.repository_path_map's own output, which is keyed by the
    repository string and silently collapses down to a single survivor
    whenever more than one path shares one, wrongly flagging every
    other path sharing that repository as "missing" even though each
    one's own values.yaml content has a perfectly real repository set."""
    write_chart_yaml(tmp_path, [
        make_dep("openarchiefbeheer", "2.0.0"),
        make_dep("openklant", "1.11.0"),
        make_dep("openformulieren", "1.12.0"),
    ])
    write_values_yaml(tmp_path, f"""\
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
""")
    ok, detail = vp.check_image_repository(tmp_path)
    assert ok is True, detail
    assert detail == "0 missing repository"
