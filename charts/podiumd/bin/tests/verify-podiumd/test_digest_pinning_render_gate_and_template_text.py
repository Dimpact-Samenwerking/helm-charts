"""check_subchart_image_visibility: render-gate (rendered_chart_paths),
zaakbrug.staging as an ordinary finding, and the subchart_template_text
filter for unreferenced keys."""

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


# --- the render-gate itself (rendered_chart_paths) ---


def test_condition_disabled_dependency_not_reported_when_its_own_path_never_renders(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    """A dependency whose chart-tree path never rendered (condition:/tags:
    disabled) stays silent, whatever its vendored default looks like."""
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
    """A null-tag default with no override resolves to the dependency's
    Chart.yaml appVersion (Helm's `.tag | default .Chart.AppVersion`),
    reported as FLOATING once its path renders."""
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
    """A null tag without a repository isn't an image block: nothing to report."""
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
    """openinwoner's nested, same-named eck-operator is tags:-disabled, so
    its path never renders though openinwoner's does. Not reported, and not
    confused with the top-level eck-operator."""
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
    """When the nested dependency's path renders, its image is reported
    against its own appVersion (3.2.0), not the parent's (1.0.0)."""
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


# --- zaakbrug.staging is an ordinary finding ---


def test_zaakbrug_staging_is_now_an_ordinary_unexempted_finding(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """zaakbrug's "staging" mode is not special-cased: once its path renders
    it is reported like any other unresolved subchart-default image."""
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
    """staging.apiProxy (nested sibling) is an ordinary finding too."""
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
    """A sub-chart values key no template in that sub-chart reads is inert:
    no override could change the render, so it isn't reported."""
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
    """A key a template does read is still reported as unresolved."""
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
    """No templates/ directory means "can't tell", not "unreferenced": not
    filtered."""
    write_chart_yaml(tmp_path, [make_dep("pabc", "1.1.1")])
    make_tgz(tmp_path / "charts", "pabc", "1.1.1", {"web": {"image": {"tag": "1.1.1"}}})
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/pabc"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "pabc.web.image.tag" in out


def test_nested_dependency_finding_survives_when_parent_templates_never_mention_it(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """openinwoner's nested eck-operator is read by the nested chart's
    templates, not openinwoner's, so the text filter must keep it (the
    render-gate decides). An unreferenced parent key ("web") is filtered."""
    write_chart_yaml(tmp_path, [make_dep("openinwoner", "1.0.0")])
    make_tgz(
        tmp_path / "charts",
        "openinwoner",
        "1.0.0",
        {
            "eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
            "web": {"image": {"repository": "maykinmedia/web", "tag": "1.0.0"}},
        },
        templates={"deployment.yaml": "image: {{ .Values.image.repository }}\n"},
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
    assert "openinwoner.eck-operator.image.tag: '3.2.0' (FLOATING in the sub-chart's own default)" in out
    assert "openinwoner.web" not in out
