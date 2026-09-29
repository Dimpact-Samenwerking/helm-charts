"""check_shared_image_usage: render-based check of global.images.* entries.

0 or 1 live aliasing consumer (another path with the same repository whose
chart-tree path rendered) fails: the shared anchor is pointless. 2+ is
report-only. Incidentally shared repositories never fail. "podiumd" must be
in every stub_render for paths not under a Chart.yaml dependency."""

import io
import tarfile

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
import yaml

from dep_helpers import make_dep

DIGEST_A = "a" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, extra_files=None):
    """Write a minimal vendored <name>-<version>.tgz with <name>/values.yaml.

    `templates` ({filename: text}) adds <name>/templates/; None omits the
    directory. `chart_yaml` (dict) becomes <name>/Chart.yaml; `extra_files`
    ({relative path: text}) is written verbatim under <name>/ (e.g. a nested
    sub-subchart's Chart.yaml)."""
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
    """Fake `helm template` stdout with one "# Source:" line per chart-tree path."""
    return "".join(f"# Source: {p}/templates/x.yaml\n" for p in chart_tree_paths)


def stub_render(monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType, chart_tree_paths, returncode=0):
    """Make render_chart report exactly `chart_tree_paths` as rendered.

    Patched on lib.checks.digest_pinning, the module that owns the binding."""
    monkeypatch.setattr(
        libdigestpinningcheck,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(
            returncode=returncode, stdout=render_stdout(chart_tree_paths), stderr=""
        ),
    )


def test_global_image_with_zero_consumers_fails(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
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


def test_global_image_with_exactly_one_consumer_fails(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """One consumer is under-used: no better than setting the value there."""
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


def test_global_image_with_two_or_more_consumers_passes(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """2+ consumers is genuinely shared: report only, with the consumer list."""
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
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A path under an enabled (rendered) dependency still counts as a consumer."""
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
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """openzaak.redis.image configures a nested redis sub-subchart disabled
    via tags, so it never renders: global.images.redis has zero live
    consumers, not one."""
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
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd", "podiumd/charts/openzaak"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is False
    assert "1 global.images.* entry under-used (failing)" in detail
    out = capsys.readouterr().out
    assert "global.images.redis (0 real consumer(s)):" in out
    # a dead consumer must not appear in the printed path list either
    assert "openzaak.redis.image" not in out


def test_non_global_repository_shared_at_two_or_more_paths_never_fails(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """An incidentally shared repository (not global.images.*) never fails."""
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
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A repository pinned at one path isn't shared: no noise."""
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


def test_check_shared_image_usage_render_failure(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, [], returncode=1)

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is False
    assert "helm template failed to render" in detail


def test_global_image_usage_excludes_single_use_repos(libdigestpinningcheck: ModuleType, tmp_path: Path):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""",
    )
    values = libdigestpinningcheck.load_yaml_mapping(tmp_path / "values.yaml")
    deps = []
    repo_groups = libdigestpinningcheck._repository_groups(tmp_path, values, deps)
    assert libdigestpinningcheck._global_image_usage(values, repo_groups) == {}
    assert libdigestpinningcheck._non_global_shared_repo_groups(values, repo_groups, {}) == {}


def test_global_image_usage_finds_multi_path_repos(libdigestpinningcheck: ModuleType, tmp_path: Path):
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
    values = libdigestpinningcheck.load_yaml_mapping(tmp_path / "values.yaml")
    deps = []
    repo_groups = libdigestpinningcheck._repository_groups(tmp_path, values, deps)
    usage = libdigestpinningcheck._global_image_usage(values, repo_groups)
    assert set(usage) == {("global", "images", "curl")}
    assert usage[("global", "images", "curl")] == [("zac", "curl", "image")]


def test_path_chart_tree_path_orphan_key_is_always_chart_name(libdigestpinningcheck: ModuleType, tmp_path: Path):
    assert libdigestpinningcheck._path_chart_tree_path(tmp_path, [], ("global", "images", "nginx")) == "podiumd"


def test_path_chart_tree_path_dependency_resolves_via_resolve_subchart_default(
    libdigestpinningcheck: ModuleType, tmp_path: Path
):
    deps = [make_dep("openzaak", "1.14.2")]
    assert (
        libdigestpinningcheck._path_chart_tree_path(tmp_path, deps, ("openzaak", "image")) == "podiumd/charts/openzaak"
    )


def test_live_repository_groups_drops_dead_consumer_paths(libdigestpinningcheck: ModuleType, tmp_path: Path):
    """A path whose chart-tree path never rendered is dropped entirely."""
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

    assert live == {"library/redis": [("global", "images", "redis")]}  # only the (always-live) definition survives
