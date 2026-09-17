"""resolve_values_path_source (chart-name-or-local-file attribution) and
check_subchart_image_visibility / find_unresolved_subchart_images — a
separate, report-only scan for images defined only in a vendored
dependency's own default values.yaml (see lib.chart.subchart_values),
which check_digest_pinning can never see since it only ever walks
podiumd's own values.yaml."""

import io
import tarfile
from types import SimpleNamespace

import yaml
from dep_helpers import make_dep

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


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
    (see lib.digest_pinning_check's "from lib.render_scope import ...
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


# --- resolve_values_path_source (chart-name-or-local-file attribution) ---


def test_shared_image_usage_annotates_a_real_dependency_path_with_its_chart(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
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

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    out = capsys.readouterr().out
    assert "zac.nginx.image  [chart zaakafhandelcomponent@1.0.297]" in out


def test_shared_image_usage_annotates_an_orphan_path_with_its_local_template(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """ "frankgateway" has no Chart.yaml dependency of its own at all --
    it's a native, directly-templated top-level block. The local
    template file that actually references ".Values.frankgateway" must
    be named, deterministically (a literal text search, not a guess)."""
    write_chart_yaml(tmp_path, [])
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "frankgateway-nginx.yaml").write_text(
        "image: {{ .Values.frankgateway.nginx.image.repository }}:{{ .Values.frankgateway.nginx.image.tag }}\n",
        encoding="utf-8",
    )
    write_values_yaml(
        tmp_path,
        f"""\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
frankgateway:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
zac:
  nginx:
    image:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd"])

    ok, detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    out = capsys.readouterr().out
    assert "frankgateway.nginx.image  [local: templates/frankgateway-nginx.yaml]" in out


# --- check_subchart_image_visibility / find_unresolved_subchart_images ---
#
# Every call now also renders (see lib.render_scope.rendered_chart_paths)
# to gate findings on whether the owning chart-tree path actually
# produced output — stub_render() fakes that render's stdout so these
# tests don't need a real `helm template`. A dependency's own chart-tree
# path is CHART_NAME/charts/<dep name> (never the alias — see lib.chart.
# resolve_subchart_default), so stub_render is always given "podiumd/
# charts/<name>", not "podiumd/charts/<alias>".


def test_no_dependencies_passes(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, [])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_dependency_not_yet_vendored_is_skipped(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    """No .tgz on disk yet (the "Dependencies" step hasn't run) — nothing
    to read, so silently skipped rather than an error."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_overridden_subchart_image_is_not_reported(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(
        tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}}
    )
    write_values_yaml(
        tmp_path,
        f"""\
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.14.2@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_unoverridden_floating_subchart_image_fails_the_check(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """A FLOATING finding (no podiumd override AND no digest pin in the
    sub-chart's own default either) is genuinely unpinned and non-
    reproducible — it now FAILS the step, unlike a pinned finding."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2", alias="oz")])
    make_tgz(
        tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}}
    )
    write_values_yaml(tmp_path, "{}\n")
    # chart-tree path is keyed by the dependency's own alias ("oz"),
    # never its real chart name ("openzaak") — Helm's own "# Source:"
    # annotations name a chart-tree directory by alias when declared.
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/oz"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "FAILING:" in out
    assert "oz.image.tag: '1.14.2' (FLOATING in the sub-chart's own default)" in out


def test_subchart_image_visibility_finding_annotated_with_its_owning_chart(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """Every finding is annotated via the SAME shared resolver
    (lib.chart.resolve_values_path_source) _print_shared_image_usage
    uses — scope_key here is always a real Chart.yaml dependency's own
    alias-or-name by construction, so this can only ever hit the
    resolver's "chart X@Y" branch, never the local-file one."""
    write_chart_yaml(tmp_path, [make_dep("eck-operator", "3.5.0")])
    make_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": "3.5.0"}},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/eck-operator"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    out = capsys.readouterr().out
    assert (
        "eck-operator.image.tag: '3.5.0' (FLOATING in the sub-chart's own default)  [chart eck-operator@3.5.0]" in out
    )


def test_unoverridden_already_pinned_subchart_image_never_fails(
    vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys
):
    """A PINNED finding (the sub-chart's own default already embeds a
    real digest, podiumd just doesn't override it) is already
    reproducible as-is — report only, never fails the run on its own."""
    write_chart_yaml(tmp_path, [make_dep("zac", "1.0.297", alias="zac")])
    make_tgz(
        tmp_path / "charts",
        "zac",
        "1.0.297",
        {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector", "tag": f"0.169.0@sha256:{DIGEST_A}"}
            }
        },
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zac"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "0 floating, 1 pinned (report only)"
    out = capsys.readouterr().out
    assert "Report only, NOT failing:" in out
    assert "FAILING:" not in out
    assert (
        f"zac.opentelemetry-collector.image.tag: '0.169.0@sha256:{DIGEST_A}' (pinned in the sub-chart's own default)"
        in out
    )


def test_mix_of_floating_and_pinned_findings_fails_overall(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """A mix — one floating, one pinned — still fails overall (any
    floating finding fails the step), but the pinned one is still
    printed under its own separate, clearly-labeled report-only
    section, never conflated with the failing floating one."""
    write_chart_yaml(
        tmp_path,
        [
            make_dep("openzaak", "1.14.2"),
            make_dep("zac", "1.0.297", alias="zac"),
        ],
    )
    make_tgz(
        tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}}
    )
    make_tgz(
        tmp_path / "charts",
        "zac",
        "1.0.297",
        {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector", "tag": f"0.169.0@sha256:{DIGEST_A}"}
            }
        },
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak", "podiumd/charts/zac"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing), 1 pinned (report only)"
    out = capsys.readouterr().out
    assert "FAILING:" in out
    assert "openzaak.image.tag: '1.14.2' (FLOATING in the sub-chart's own default)" in out
    assert "Report only, NOT failing:" in out
    assert (
        f"zac.opentelemetry-collector.image.tag: '0.169.0@sha256:{DIGEST_A}' (pinned in the sub-chart's own default)"
        in out
    )


def test_nested_subchart_image_path_resolved_correctly(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    """A sub-chart default nested under more than one key (e.g. a sidecar)
    must be checked against the SAME nested path in podiumd's own
    values.yaml, not just its top-level scope."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(
        tmp_path,
        f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_B}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_exempted_digest_pinning_path_never_shows_up_as_unresolved(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    """keycloak-operator.operator is exempt from check_digest_pinning
    because podiumd DOES override it (with a split tag/sha convention
    instead of an embedded digest) — it must never appear as "unresolved"
    here, since it has an own_tag by definition."""
    write_chart_yaml(tmp_path, [make_dep("keycloak-operator", "1.0.0")])
    make_tgz(
        tmp_path / "charts",
        "keycloak-operator",
        "1.0.0",
        {"operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.6.4"}}},
    )
    write_values_yaml(
        tmp_path,
        """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/keycloak-operator"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_multiple_unresolved_images_all_reported(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    write_chart_yaml(
        tmp_path,
        [
            make_dep("openzaak", "1.14.2"),
            make_dep("openklant", "2.0.0"),
        ],
    )
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    make_tgz(tmp_path / "charts", "openklant", "2.0.0", {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak", "podiumd/charts/openklant"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "2 floating (failing)"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out
    assert "openklant.redis.image.tag" in out


def test_check_subchart_image_visibility_render_failure(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    monkeypatch.setattr(
        libdigestpinningcheck,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is False
    assert "helm template failed to render" in detail
