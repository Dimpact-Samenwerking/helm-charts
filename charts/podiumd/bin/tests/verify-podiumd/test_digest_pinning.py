"""check_digest_pinning — every "image: {tag: ...}" block in values.yaml
must have a digest-pinned tag, except the one known keycloak-operator
field that uses a separate split tag/sha convention instead.

Also check_subchart_image_visibility / find_unresolved_subchart_images —
a separate, report-only scan for images defined only in a vendored
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
        libdigestpinningcheck, "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(
            returncode=returncode, stdout=render_stdout(chart_tree_paths), stderr=""))


def test_no_values_yaml_passes(vp, tmp_path):
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert "0 pin(s)" in detail


def test_all_digest_pinned_passes(vp, tmp_path):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_floating_tag_fails(vp, tmp_path, capsys):
    write_values_yaml(tmp_path, """\
clamav:
  metrics:
    image:
      repository: docker.io/sergeymakinen/clamav_exporter
      tag: "v2.1.8"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/1 image(s) not digest-pinned"
    out = capsys.readouterr().out
    assert "clamav.metrics.image.tag: 'v2.1.8'" in out


def test_mix_of_pinned_and_floating_reports_only_the_floating_one(vp, tmp_path):
    write_values_yaml(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
clamav:
  metrics:
    image:
      repository: docker.io/sergeymakinen/clamav_exporter
      tag: "v2.1.8"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/2 image(s) not digest-pinned"


def test_keycloak_operator_own_image_is_exempt(vp, tmp_path):
    """keycloak-operator.operator.image uses the adfinis chart's own
    split tag/sha convention -- embedding @sha256 in tag there would
    produce a double digest. Must never be flagged, regardless of what
    its own tag looks like."""
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_keycloak_operator_keycloak_image_is_exempt(vp, tmp_path):
    """keycloak-operator.operator.config.keycloakImage uses the exact
    same split tag/sha convention as operator.image above -- only
    visible to this check at all since find_image_tag_paths started
    recognizing "...Image"-suffixed keys, not just the literal "image"."""
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    config:
      keycloakImage:
        repository: quay.io/keycloak/keycloak
        tag: "26.7.3"
        sha: "ff4257d0d64efbe99ed1ddfaf07765cc3c36dc7518bf8324d41961327f441c54"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_omc_own_image_is_exempt(vp, tmp_path):
    """omc's values.yaml comment says the subchart itself can't handle a
    digest-pinned tag -- must never be flagged."""
    write_values_yaml(tmp_path, """\
omc:
  image:
    tag: "1.17.19"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "1 pin(s), 0 unpinned"


def test_keycloak_operator_exemption_does_not_hide_other_violations(vp, tmp_path):
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
  jobs:
    ensurePodiumdAdminUser:
      image:
        repository: postgres
        tag: "16"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/2 image(s) not digest-pinned"


def test_sha256_style_digest_is_case_sensitive_lowercase_hex(vp, tmp_path):
    """A malformed/uppercase digest must still fail -- this check is
    about the shape scan_digest_pins itself requires, not just "has an
    @sha256 substring somewhere"."""
    write_values_yaml(tmp_path, """\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False


def test_multiple_violations_all_reported(vp, tmp_path, capsys):
    write_values_yaml(tmp_path, f"""\
clamav:
  metrics:
    image:
      repository: docker.io/sergeymakinen/clamav_exporter
      tag: "v2.1.8"
pabc:
  initContainers:
    waitFor:
      image:
        repository: groundnuty/k8s-wait-for
        tag: "v2.0"
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{DIGEST_A}"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "2/3 image(s) not digest-pinned"
    out = capsys.readouterr().out
    assert "clamav.metrics.image.tag" in out
    assert "pabc.initContainers.waitFor.image.tag" in out


def test_suffixed_image_key_is_enforced_too(vp, tmp_path, capsys):
    """A component needing more than one distinctly-named image (e.g. a
    job's main "image" plus a separate "initImage") can't use the bare
    "image" key for both — real-world case: ensurePodiumdAdminUser's
    Python init image. Regression: find_image_tag_paths used to only
    recognize the literal key "image", silently exempting every
    "...Image"-suffixed sibling from digest-pin enforcement entirely."""
    write_values_yaml(tmp_path, """\
keycloak-operator:
  jobs:
    ensurePodiumdAdminUser:
      initImage:
        repository: python
        tag: "3.14-slim"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is False
    assert detail == "1/1 image(s) not digest-pinned"
    out = capsys.readouterr().out
    assert "keycloak-operator.jobs.ensurePodiumdAdminUser.initImage.tag: '3.14-slim'" in out


def test_plural_images_container_not_treated_as_an_image_block(vp, tmp_path):
    """"images" (plural, a container of several named templates, e.g.
    global.images.nginx) must not itself be flagged — it doesn't end in
    "Image" (capital I), so only its own literally-"image"/"...Image"-
    keyed children would ever be."""
    write_values_yaml(tmp_path, """\
global:
  images:
    nginx:
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.4"
""")
    ok, detail = vp.check_digest_pinning(tmp_path)
    assert ok is True
    assert detail == "0 pin(s), 0 unpinned"


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
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}})
    write_values_yaml(tmp_path, f"""\
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.14.2@sha256:{DIGEST_A}"
""")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_unoverridden_floating_subchart_image_is_reported_but_never_fails(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2", alias="oz")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}})
    write_values_yaml(tmp_path, "{}\n")
    # chart-tree path is keyed by the dependency's own alias ("oz"),
    # never its real chart name ("openzaak") — Helm's own "# Source:"
    # annotations name a chart-tree directory by alias when declared.
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/oz"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "oz.image.tag: '1.14.2' (FLOATING in the sub-chart's own default)" in out


def test_unoverridden_already_pinned_subchart_image_is_reported_as_pinned(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    write_chart_yaml(tmp_path, [make_dep("zac", "1.0.297", alias="zac")])
    make_tgz(tmp_path / "charts", "zac", "1.0.297",
              {"opentelemetry-collector": {"image": {
                  "repository": "otel/opentelemetry-collector", "tag": f"0.169.0@sha256:{DIGEST_A}"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zac"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (0 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert f"zac.opentelemetry-collector.image.tag: '0.169.0@sha256:{DIGEST_A}' (pinned in the sub-chart's own default)" in out


def test_nested_subchart_image_path_resolved_correctly(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    """A sub-chart default nested under more than one key (e.g. a sidecar)
    must be checked against the SAME nested path in podiumd's own
    values.yaml, not just its top-level scope."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_B}"
""")
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
    make_tgz(tmp_path / "charts", "keycloak-operator", "1.0.0",
              {"operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator", "tag": "26.6.4"}}})
    write_values_yaml(tmp_path, """\
keycloak-operator:
  operator:
    image:
      repository: quay.io/keycloak/keycloak-operator
      tag: "26.6.4"
""")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/keycloak-operator"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_multiple_unresolved_images_all_reported(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    write_chart_yaml(tmp_path, [
        make_dep("openzaak", "1.14.2"),
        make_dep("openklant", "2.0.0"),
    ])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    make_tgz(tmp_path / "charts", "openklant", "2.0.0",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak", "podiumd/charts/openklant"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "2 unresolved (2 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out
    assert "openklant.redis.image.tag" in out


def test_check_subchart_image_visibility_render_failure(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    monkeypatch.setattr(libdigestpinningcheck, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is False
    assert "helm template failed to render" in detail


# --- the render-gate itself (rendered_chart_paths) ---

def test_condition_disabled_dependency_not_reported_when_its_own_path_never_renders(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    """A dependency whose own chart-tree path never rendered at all (e.g.
    zaakbrug's own condition-disabled "staging" mode, or any dependency
    disabled via Helm's condition:/tags: mechanism) must stay silent
    structurally — the render-gate applies uniformly to every finding,
    regardless of what the dependency's own vendored default looks
    like."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, [])  # zaakbrug's own path never rendered

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "0 unresolved"


def test_null_tag_subchart_default_resolved_via_own_app_version_is_reported(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """A top-level dependency's own default "image: {repository: ...,
    tag: null}" block (no podiumd override at all) — e.g. eck-operator,
    whose own vendored default relies entirely on Helm's ".tag | default
    .Chart.AppVersion" convention — must resolve to that dependency's own
    Chart.yaml "appVersion" (never a real digest-pinned tag, so reported
    as FLOATING) once its own chart-tree path renders."""
    write_chart_yaml(tmp_path, [make_dep("eck-operator", "3.5.0")])
    make_tgz(tmp_path / "charts", "eck-operator", "3.5.0",
              {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
              chart_yaml={"name": "eck-operator", "version": "3.5.0", "appVersion": "3.5.0"})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/eck-operator"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "eck-operator.image.tag: '3.5.0' (FLOATING in the sub-chart's own default)" in out


def test_null_tag_with_no_repository_is_skipped(vp, tmp_path, monkeypatch, libdigestpinningcheck):
    """A null/missing "tag:" with no "repository:" either isn't a real
    image block at all (find_image_tag_paths' own include_null_tags mode
    already requires a repository) — nothing to resolve or report."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"tag": None}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_nested_subchart_default_not_reported_when_its_own_path_never_renders(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """openinwoner's own vendored default bundles a SEPARATE, same-named
    nested "eck-operator" dependency (its OWN Chart.yaml declares it,
    distinct from the top-level "eck-operator" dependency) — globally
    disabled via Helm's own tags: mechanism, so its own nested chart-tree
    path (podiumd/charts/openinwoner/charts/eck-operator) never renders,
    even though openinwoner's OWN top-level path does. Must not be
    reported, and must not be confused with the top-level eck-operator
    dependency's own image."""
    write_chart_yaml(tmp_path, [make_dep("openinwoner", "1.0.0")])
    make_tgz(
        tmp_path / "charts", "openinwoner", "1.0.0",
        {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}},
        chart_yaml={
            "name": "openinwoner", "version": "1.0.0", "appVersion": "1.0.0",
            "dependencies": [{"name": "eck-operator", "version": "3.2.0"}],
        },
        extra_files={
            "charts/eck-operator/Chart.yaml": yaml.safe_dump(
                {"name": "eck-operator", "version": "3.2.0", "appVersion": "3.2.0"}),
        },
    )
    write_values_yaml(tmp_path, "{}\n")
    # openinwoner's own top-level path DOES render; its nested eck-operator's own path does not.
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openinwoner"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "0 unresolved"
    out = capsys.readouterr().out
    assert "eck-operator" not in out


def test_nested_subchart_default_reported_when_its_own_path_does_render(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """The flip side of the above: when the nested dependency's own
    chart-tree path DOES render, its own image is reported, resolved
    against ITS OWN Chart.yaml appVersion (3.2.0), not the outer
    dependency's (1.0.0)."""
    write_chart_yaml(tmp_path, [make_dep("openinwoner", "1.0.0")])
    make_tgz(
        tmp_path / "charts", "openinwoner", "1.0.0",
        {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}},
        chart_yaml={
            "name": "openinwoner", "version": "1.0.0", "appVersion": "1.0.0",
            "dependencies": [{"name": "eck-operator", "version": "3.2.0"}],
        },
        extra_files={
            "charts/eck-operator/Chart.yaml": yaml.safe_dump(
                {"name": "eck-operator", "version": "3.2.0", "appVersion": "3.2.0"}),
        },
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck,
                ["podiumd/charts/openinwoner", "podiumd/charts/openinwoner/charts/eck-operator"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "eck-operator.image.tag: '3.2.0' (FLOATING in the sub-chart's own default)" in out


# --- zaakbrug.staging is now an ORDINARY finding (SUBCHART_VISIBILITY_EXEMPT removed) ---

def test_zaakbrug_staging_is_now_an_ordinary_unexempted_finding(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """SUBCHART_VISIBILITY_EXEMPT has been removed entirely: zaakbrug's
    own "staging" mode is no longer special-cased — once its own
    chart-tree path actually renders, it's reported exactly like any
    other unresolved subchart-default image, with no exempt bucket, no
    exempt count, no special wording."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zaakbrug"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "zaakbrug.staging.image.tag: '1.9.0' (FLOATING in the sub-chart's own default)" in out
    assert "exempt" not in out


def test_zaakbrug_staging_nested_prefix_is_also_an_ordinary_finding(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """staging.apiProxy (a nested sibling under the same "staging" key)
    is likewise just an ordinary finding now — no prefix-match exemption
    left to apply to it at all."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"apiProxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "stable"}}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zaakbrug"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "zaakbrug.staging.apiProxy.image.tag" in out


def test_multiple_findings_from_different_dependencies_all_reported_plainly(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28"), make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "zaakbrug", "2.3.28",
              {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}})
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zaakbrug", "podiumd/charts/openzaak"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "2 unresolved (2 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out
    assert "zaakbrug.staging.image.tag" in out
    assert "exempt" not in out


# --- subchart_template_text (structurally unreferenced keys) ---

def test_unreferenced_subchart_key_is_dropped_when_templates_show_it_is_dead(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """A vendored sub-chart's own top-level values key (e.g. pabc's "web"/
    "poller") that no template in that same sub-chart ever reads is
    structurally inert — reporting it as "unresolved" is just noise, since
    no podiumd override there could ever change what gets rendered."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(tmp_path / "charts", "pabc", "1.1.1",
              {"image": {"repository": "pabc/pabc-api", "tag": "1.1.1"},
               "web": {"image": {"tag": "1.1.1"}}},
              templates={"deployment.yaml": "image: {{ .Values.image.repository }}:{{ .Values.image.tag }}\n"})
    write_values_yaml(tmp_path, f"""\
pabc:
  image:
    repository: pabc/pabc-api
    tag: "1.1.1@sha256:{DIGEST_A}"
""")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/pabc"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "0 unresolved"
    out = capsys.readouterr().out
    assert "web" not in out


def test_referenced_subchart_key_is_still_reported_even_with_templates_present(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """The flip side of the above: a key a template DOES read must still be
    reported as unresolved — the filter only drops keys with zero textual
    reference anywhere in templates/, not everything just because
    templates/ happens to be readable."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2",
              {"redis": {"image": {"repository": "redis", "tag": "8.0"}}},
              templates={"deployment.yaml": "image: {{ .Values.redis.image.repository }}\n"})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out


def test_unreferenced_key_without_a_templates_dir_at_all_is_still_reported(vp, tmp_path, monkeypatch, libdigestpinningcheck, capsys):
    """A vendored .tgz with no templates/ directory at all (the shape
    every other test's make_tgz call already uses) is "can't tell", not
    "definitely unreferenced" — must NOT be filtered out just because the
    haystack subchart_template_text would see is empty."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(tmp_path / "charts", "pabc", "1.1.1",
              {"web": {"image": {"tag": "1.1.1"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/pabc"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "1 unresolved (1 floating tag(s)) — report only"
    out = capsys.readouterr().out
    assert "pabc.web.image.tag" in out
