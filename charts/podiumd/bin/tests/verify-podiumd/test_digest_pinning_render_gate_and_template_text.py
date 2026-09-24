"""check_subchart_image_visibility's render-gate (rendered_chart_paths),
the removal of SUBCHART_VISIBILITY_EXEMPT (zaakbrug.staging is now an
ordinary finding), and subchart_template_text (structurally
unreferenced keys) — all further behavior of check_subchart_image_
visibility / find_unresolved_subchart_images, a separate, report-only
scan for images defined only in a vendored dependency's own default
values.yaml."""

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


def stub_render(monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType, chart_tree_paths, returncode=0):
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


# --- the render-gate itself (rendered_chart_paths) ---


def test_condition_disabled_dependency_not_reported_when_its_own_path_never_renders(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    """A dependency whose own chart-tree path never rendered at all (e.g.
    zaakbrug's own condition-disabled "staging" mode, or any dependency
    disabled via Helm's condition:/tags: mechanism) must stay silent
    structurally — the render-gate applies uniformly to every finding,
    regardless of what the dependency's own vendored default looks
    like."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(
        tmp_path / "charts",
        "zaakbrug",
        "2.3.28",
        {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, [])  # zaakbrug's own path never rendered

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "0 unresolved"


def test_null_tag_subchart_default_resolved_via_own_app_version_is_reported(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A top-level dependency's own default "image: {repository: ...,
    tag: null}" block (no podiumd override at all) — e.g. eck-operator,
    whose own vendored default relies entirely on Helm's ".tag | default
    .Chart.AppVersion" convention — must resolve to that dependency's own
    Chart.yaml "appVersion" (never a real digest-pinned tag, so reported
    as FLOATING) once its own chart-tree path renders."""
    write_chart_yaml(tmp_path, [make_dep("eck-operator", "3.5.0")])
    make_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
        chart_yaml={"name": "eck-operator", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/eck-operator"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "eck-operator.image.tag: '3.5.0' (FLOATING in the sub-chart's own default)" in out


def test_null_tag_with_no_repository_is_skipped(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
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


def test_nested_subchart_default_not_reported_when_its_own_path_never_renders(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
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
        tmp_path / "charts",
        "openinwoner",
        "1.0.0",
        {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}},
        chart_yaml={
            "name": "openinwoner",
            "version": "1.0.0",
            "appVersion": "1.0.0",
            "dependencies": [{"name": "eck-operator", "version": "3.2.0"}],
        },
        extra_files={
            "charts/eck-operator/Chart.yaml": yaml.safe_dump(
                {"name": "eck-operator", "version": "3.2.0", "appVersion": "3.2.0"}
            ),
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


def test_nested_subchart_default_reported_when_its_own_path_does_render(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """The flip side of the above: when the nested dependency's own
    chart-tree path DOES render, its own image is reported, resolved
    against ITS OWN Chart.yaml appVersion (3.2.0), not the outer
    dependency's (1.0.0)."""
    write_chart_yaml(tmp_path, [make_dep("openinwoner", "1.0.0")])
    make_tgz(
        tmp_path / "charts",
        "openinwoner",
        "1.0.0",
        {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}},
        chart_yaml={
            "name": "openinwoner",
            "version": "1.0.0",
            "appVersion": "1.0.0",
            "dependencies": [{"name": "eck-operator", "version": "3.2.0"}],
        },
        extra_files={
            "charts/eck-operator/Chart.yaml": yaml.safe_dump(
                {"name": "eck-operator", "version": "3.2.0", "appVersion": "3.2.0"}
            ),
        },
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(
        monkeypatch,
        libdigestpinningcheck,
        ["podiumd/charts/openinwoner", "podiumd/charts/openinwoner/charts/eck-operator"],
    )

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "eck-operator.image.tag: '3.2.0' (FLOATING in the sub-chart's own default)" in out


# --- zaakbrug.staging is now an ORDINARY finding (SUBCHART_VISIBILITY_EXEMPT removed) ---


def test_zaakbrug_staging_is_now_an_ordinary_unexempted_finding(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """SUBCHART_VISIBILITY_EXEMPT has been removed entirely: zaakbrug's
    own "staging" mode is no longer special-cased — once its own
    chart-tree path actually renders, it's reported exactly like any
    other unresolved subchart-default image, with no exempt bucket, no
    exempt count, no special wording."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(
        tmp_path / "charts",
        "zaakbrug",
        "2.3.28",
        {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zaakbrug"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "zaakbrug.staging.image.tag: '1.9.0' (FLOATING in the sub-chart's own default)" in out
    assert "exempt" not in out


def test_zaakbrug_staging_nested_prefix_is_also_an_ordinary_finding(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """staging.apiProxy (a nested sibling under the same "staging" key)
    is likewise just an ordinary finding now — no prefix-match exemption
    left to apply to it at all."""
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28")])
    make_tgz(
        tmp_path / "charts",
        "zaakbrug",
        "2.3.28",
        {"staging": {"apiProxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "stable"}}}},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zaakbrug"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "zaakbrug.staging.apiProxy.image.tag" in out


def test_multiple_findings_from_different_dependencies_all_reported_plainly(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    write_chart_yaml(tmp_path, [make_dep("zaakbrug", "2.3.28"), make_dep("openzaak", "1.14.2")])
    make_tgz(
        tmp_path / "charts",
        "zaakbrug",
        "2.3.28",
        {"staging": {"image": {"repository": "openzaak/open-zaak", "tag": "1.9.0"}}},
    )
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"redis": {"image": {"repository": "redis", "tag": "8.0"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/zaakbrug", "podiumd/charts/openzaak"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "2 floating (failing)"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out
    assert "zaakbrug.staging.image.tag" in out
    assert "exempt" not in out


# --- subchart_template_text (structurally unreferenced keys) ---


def test_unreferenced_subchart_key_is_dropped_when_templates_show_it_is_dead(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A vendored sub-chart's own top-level values key (e.g. pabc's "web"/
    "poller") that no template in that same sub-chart ever reads is
    structurally inert — reporting it as "unresolved" is just noise, since
    no podiumd override there could ever change what gets rendered."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(
        tmp_path / "charts",
        "pabc",
        "1.1.1",
        {"image": {"repository": "pabc/pabc-api", "tag": "1.1.1"}, "web": {"image": {"tag": "1.1.1"}}},
        templates={"deployment.yaml": "image: {{ .Values.image.repository }}:{{ .Values.image.tag }}\n"},
    )
    write_values_yaml(
        tmp_path,
        f"""\
pabc:
  image:
    repository: pabc/pabc-api
    tag: "1.1.1@sha256:{DIGEST_A}"
""",
    )
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/pabc"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is True
    assert detail == "0 unresolved"
    out = capsys.readouterr().out
    assert "web" not in out


def test_referenced_subchart_key_is_still_reported_even_with_templates_present(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """The flip side of the above: a key a template DOES read must still be
    reported as unresolved — the filter only drops keys with zero textual
    reference anywhere in templates/, not everything just because
    templates/ happens to be readable."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(
        tmp_path / "charts",
        "openzaak",
        "1.14.2",
        {"redis": {"image": {"repository": "redis", "tag": "8.0"}}},
        templates={"deployment.yaml": "image: {{ .Values.redis.image.repository }}\n"},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "openzaak.redis.image.tag" in out


def test_unreferenced_key_without_a_templates_dir_at_all_is_still_reported(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A vendored .tgz with no templates/ directory at all (the shape
    every other test's make_tgz call already uses) is "can't tell", not
    "definitely unreferenced" — must NOT be filtered out just because the
    haystack subchart_template_text would see is empty."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(tmp_path / "charts", "pabc", "1.1.1", {"web": {"image": {"tag": "1.1.1"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/pabc"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "pabc.web.image.tag" in out
