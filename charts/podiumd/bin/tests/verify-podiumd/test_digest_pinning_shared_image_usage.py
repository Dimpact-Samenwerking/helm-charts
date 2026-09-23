"""check_shared_image_usage: a SEPARATE, render-based check —

For each global.images.* registered entry (lib.chart.global_image_paths
— the deliberate "this is meant to be shared" mechanism), 0 or 1 real,
LIVE aliasing consumer (any OTHER path resolving to the same
repository AND whose own chart-tree path actually rendered, excluding
the global.images.<name> definition path itself) now FAILS check_
shared_image_usage — the shared-anchor mechanism itself is pointless
there. 2+ real consumers stays report only. A repository that's shared
incidentally (not a global.images.* registration at all) never fails,
regardless of consumer count. Every test here stubs the render (see
stub_render, below) — "podiumd" itself (CHART_NAME) must always be
included for any path whose top-level key is NOT a real Chart.yaml
dependency (an orphan/native top-level block, or the global.images.*
anchor itself — see _path_chart_tree_path), since that's always
considered live whenever anything renders at all."""

import io
import tarfile

from types import SimpleNamespace

import yaml

from dep_helpers import make_dep

DIGEST_A = "a" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, extra_files=None):
    """A minimal vendored <name>-<version>.tgz containing <name>/values.yaml
    and, if `templates` is given (a {filename: text} dict), <name>/templates/
    <filename> for each entry — enough to exercise subchart_values and
    subchart_template_text without a real `helm pull`. `templates=None`
    (the default) omits templates/ entirely, matching a vendored .tgz whose
    layout subchart_template_text can't make sense of.

    `chart_yaml`, if given (a dict), is written as <name>/Chart.yaml — used
    by subchart_app_version/subchart_dependencies (e.g. a dependency's own
    "appVersion" for a null-tag default, or its own nested "dependencies"
    list for the openinwoner/eck-operator-style nested-dependency case).
    `extra_files`, if given (a {relative path: text} dict), is written
    verbatim under <name>/ — used for a NESTED sub-subchart's own
    Chart.yaml (e.g. "charts/eck-operator/Chart.yaml")."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for filename, text in (templates or {}).items():
            tpl_data = text.encode("utf-8")
            tpl_info = tarfile.TarInfo(name=f"{name}/templates/{filename}")
            tpl_info.size = len(tpl_data)
            tar.addfile(tpl_info, io.BytesIO(tpl_data))
        if chart_yaml is not None:
            cy_data = yaml.safe_dump(chart_yaml).encode("utf-8")
            cy_info = tarfile.TarInfo(name=f"{name}/Chart.yaml")
            cy_info.size = len(cy_data)
            tar.addfile(cy_info, io.BytesIO(cy_data))
        for relpath, text in (extra_files or {}).items():
            ef_data = text.encode("utf-8")
            ef_info = tarfile.TarInfo(name=f"{name}/{relpath}")
            ef_info.size = len(ef_data)
            tar.addfile(ef_info, io.BytesIO(ef_data))


def render_stdout(chart_tree_paths):
    """A fake `helm template` stdout carrying one "# Source:" line per
    given chart-tree path — enough for lib.render_scope.rendered_
    chart_paths to recover exactly that set, without a real render."""
    return "".join(f"# Source: {p}/templates/x.yaml\n" for p in chart_tree_paths)


def stub_render(monkeypatch, libdigestpinningcheck, chart_tree_paths, returncode=0):
    """Replaces check_subchart_image_visibility's own render_chart call
    (see lib.checks.digest_pinning's "from lib.render_scope import ...
    render_chart" binding — must be patched on THAT module, not vp/
    render_scope, per this test suite's own module-that-owns-the-binding
    convention) with one that reports exactly `chart_tree_paths` as
    rendered, with no real `helm template` invocation."""
    monkeypatch.setattr(
        libdigestpinningcheck,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(
            returncode=returncode, stdout=render_stdout(chart_tree_paths), stderr=""
        ),
    )


def test_global_image_with_zero_consumers_fails(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is False
    assert "1 global.images.* entry under-used (failing)" in detail
    out = capsys.readouterr().out
    assert "FAILING: 1 global.images.* entry registered as a shared image" in out
    assert "global.images.nginx (0 real consumer(s)):" in out


def test_global_image_with_exactly_one_consumer_fails(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """Exactly one real consumer is still under-used — a shared anchor
    with only one alias site is no different from just setting the
    value directly there."""
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    curl:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
zac:
  curl:
    image:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is False
    assert "1 global.images.* entry under-used (failing)" in detail
    out = capsys.readouterr().out
    assert "FAILING: 1 global.images.* entry registered as a shared image" in out
    assert "global.images.curl (1 real consumer(s)):" in out
    assert "zac.curl.image" in out


def test_global_image_with_two_or_more_consumers_passes(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """2+ real consumers is genuinely shared -- working as intended,
    still worth seeing the full consumer list for, but report only."""
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
zac:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
frankgateway:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True  # 2+ consumers -- purely informational, never fails
    assert "under-used" not in detail
    out = capsys.readouterr().out
    assert "FAILING" not in out
    assert "1 global.images.* entry genuinely shared (2+ real consumers) — report only:" in out
    assert "global.images.nginx (2 real consumers):" in out
    assert "zac.nginx.image" in out
    assert "frankgateway.nginx.image" in out


def test_global_image_consumer_under_a_genuinely_enabled_dependency_counts_normally(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """The flip side of the render-gate regression tests below: a path
    under a genuinely ENABLED dependency (its own chart-tree path DOES
    render) still counts as a real consumer -- the render-gate fix must
    not regress the already-correct nginx/curl/busybox-shaped case."""
    write_chart_yaml(tmp_path, [make_dep("zaakafhandelcomponent", "1.0.297", alias="zac")])
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
zac:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
frankgateway:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd", "podiumd/charts/zac"])

    ok, _detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    out = capsys.readouterr().out
    assert "global.images.nginx (2 real consumers):" in out
    assert "zac.nginx.image" in out
    assert "frankgateway.nginx.image" in out


def test_global_image_zero_live_consumers_because_nested_dependency_tags_disabled_fails(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """The exact real bug this render-gate fixes, confirmed live against
    the real chart: every Maykin chart's own "<name>.redis.image"
    override (here, openzaak's) configures that chart's OWN NESTED
    bitnami/redis sub-dependency, globally disabled via "tags: {redis:
    false}" — openzaak ITSELF renders fine (its own top-level chart-tree
    path is live), but its own nested redis sub-subchart never does.
    global.images.redis's TRUE live consumer count is zero — a purely
    static scan would have wrongly counted it as one."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(
        tmp_path / "charts",
        "openzaak",
        "1.14.2",
        {"image": {"repository": "openzaak/open-zaak", "tag": f"1.14.2@sha256:{DIGEST_A}"}},
        chart_yaml={
            "name": "openzaak",
            "version": "1.14.2",
            "dependencies": [{"name": "redis", "version": "18.0.0", "repository": "@bitnami", "tags": ["redis"]}],
        },
    )
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    redis:
      repository: redis
      tag: "8.0@sha256:{DIGEST_A}"
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.14.2@sha256:{DIGEST_A}"
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_A}"
""",
    )
    # openzaak's own top-level path DOES render; its own nested redis
    # sub-subchart's own path never does (never included here).
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd", "podiumd/charts/openzaak"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is False
    assert "1 global.images.* entry under-used (failing)" in detail
    out = capsys.readouterr().out
    assert "global.images.redis (0 real consumer(s)):" in out
    # the dead consumer must not merely be excluded from the count --
    # it must not appear in the printed path list either.
    assert "openzaak.redis.image" not in out


def test_non_global_repository_shared_at_two_or_more_paths_never_fails(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """A repository shared incidentally (NOT a global.images.*
    registration at all -- e.g. keycloak/keycloak-shaped) is never a
    failure, regardless of consumer count -- purely informational,
    exactly like before this feature's pass/fail split existed."""
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
keycloak-operator:
  operator:
    config:
      keycloakImage:
        repository: quay.io/keycloak/keycloak
        tag: "26.7.3@sha256:{DIGEST_A}"
keycloak:
  image:
    repository: quay.io/keycloak/keycloak
    tag: "26.7.3@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    assert "under-used" not in detail
    out = capsys.readouterr().out
    assert "FAILING" not in out
    assert "1 other image(s) incidentally shared across 2+ values.yaml paths" in out
    assert "keycloak/keycloak (2 consumers):" in out


def test_check_shared_image_usage_does_not_report_a_single_use_repository_as_shared(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """A repository pinned at exactly one path isn't "shared" in any
    interesting sense -- no false-positive noise for the common case."""
    write_chart_yaml(tmp_path, [])
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd"])

    ok, _detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    out = capsys.readouterr().out
    assert "shared across" not in out
    assert "FAILING" not in out


def test_check_shared_image_usage_render_failure(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, [], returncode=1)

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is False
    assert "helm template failed to render" in detail


def test_global_image_usage_excludes_single_use_repos(libdigestpinningcheck, tmp_path):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""",
    )
    values = libdigestpinningcheck.load_yaml(tmp_path / "values.yaml")
    deps = []
    repo_groups = libdigestpinningcheck._repository_groups(tmp_path, values, deps)
    assert libdigestpinningcheck._global_image_usage(values, repo_groups) == {}
    assert libdigestpinningcheck._non_global_shared_repo_groups(values, repo_groups, {}) == {}


def test_global_image_usage_finds_multi_path_repos(libdigestpinningcheck, tmp_path):
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    curl:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
zac:
  curl:
    image:
      repository: curlimages/curl
      tag: "8.21.0@sha256:{DIGEST_A}"
""",
    )
    values = libdigestpinningcheck.load_yaml(tmp_path / "values.yaml")
    deps = []
    repo_groups = libdigestpinningcheck._repository_groups(tmp_path, values, deps)
    usage = libdigestpinningcheck._global_image_usage(values, repo_groups)
    assert set(usage) == {("global", "images", "curl")}
    assert usage[("global", "images", "curl")] == [("zac", "curl", "image")]


def test_path_chart_tree_path_orphan_key_is_always_chart_name(libdigestpinningcheck, tmp_path):
    assert libdigestpinningcheck._path_chart_tree_path(tmp_path, [], ("global", "images", "nginx")) == "podiumd"


def test_path_chart_tree_path_dependency_resolves_via_resolve_subchart_default(libdigestpinningcheck, tmp_path):
    deps = [make_dep("openzaak", "1.14.2")]
    assert (
        libdigestpinningcheck._path_chart_tree_path(tmp_path, deps, ("openzaak", "image")) == "podiumd/charts/openzaak"
    )


def test_live_repository_groups_drops_dead_consumer_paths(libdigestpinningcheck, tmp_path):
    """The render-gate primitive check_shared_image_usage's own
    consumer counting is built on: a path whose own chart-tree path
    never rendered is dropped entirely, not just from a count."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(
        tmp_path / "charts",
        "openzaak",
        "1.14.2",
        {},
        chart_yaml={
            "name": "openzaak",
            "version": "1.14.2",
            "dependencies": [{"name": "redis", "version": "18.0.0", "repository": "@bitnami", "tags": ["redis"]}],
        },
    )
    values = {
        "global": {"images": {"redis": {"repository": "redis", "tag": f"8.0@sha256:{DIGEST_A}"}}},
        "openzaak": {"redis": {"image": {"repository": "redis", "tag": f"8.0@sha256:{DIGEST_A}"}}},
    }
    deps = [make_dep("openzaak", "1.14.2")]
    rendered_paths = {"podiumd", "podiumd/charts/openzaak"}  # nested redis never rendered

    live = libdigestpinningcheck._live_repository_groups(tmp_path, deps, values, rendered_paths)

    assert live == {"redis": [("global", "images", "redis")]}  # only the (always-live) definition survives
