"""Tests for resolve_values_path_source and check_subchart_image_visibility.

The latter is a report-only scan for images defined only in a vendored subchart's
default values.yaml, which check_digest_pinning (podiumd values only) can't see."""

import io
import tarfile

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
import yaml

from dep_helpers import make_dep

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def write_values_yaml(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, extra_files=None):
    """Write a minimal vendored <name>-<version>.tgz with <name>/values.yaml.

    `templates` ({filename: text}) adds <name>/templates/; None omits templates/ entirely.
    `chart_yaml` (dict) is written as <name>/Chart.yaml (appVersion, nested dependencies).
    `extra_files` ({relative path: text}) is written verbatim under <name>/, e.g. a
    nested "charts/eck-operator/Chart.yaml"."""
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
    """Patch render_chart on lib.checks.digest_pinning (the module owning the binding) to
    report exactly `chart_tree_paths` as rendered."""
    monkeypatch.setattr(
        libdigestpinningcheck,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(
            returncode=returncode, stdout=render_stdout(chart_tree_paths), stderr=""
        ),
    )


# --- resolve_values_path_source (chart-name-or-local-file attribution) ---


def test_shared_image_usage_annotates_a_real_dependency_path_with_its_chart(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
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

    ok, _detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    out = capsys.readouterr().out
    assert "zac.nginx.image  [chart zaakafhandelcomponent@1.0.297]" in out


def test_shared_image_usage_annotates_an_orphan_path_with_its_local_template(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """ "frankgateway" has no Chart.yaml dependency: the local template referencing
    ".Values.frankgateway" is named via a literal text search, not a guess."""
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

    ok, _detail = vp.check_shared_image_usage(tmp_path, [])

    assert ok is True
    out = capsys.readouterr().out
    assert "frankgateway.nginx.image  [local: templates/frankgateway-nginx.yaml]" in out


# --- check_subchart_image_visibility / find_unresolved_subchart_images ---
# Findings are gated on whether the owning chart-tree path rendered; stub_render fakes
# that. Paths are given as "podiumd/charts/<name>" (see lib.chart.resolve_subchart_default).


def test_no_dependencies_passes(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    write_chart_yaml(tmp_path, [])
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, [])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_dependency_not_yet_vendored_is_skipped(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    """No .tgz on disk yet (Dependencies step not run): silently skipped, not an error."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/openzaak"])
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is True
    assert detail == "0 unresolved"


def test_overridden_subchart_image_is_not_reported(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
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


def test_unoverridden_floating_subchart_image_fails_the_check(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A FLOATING finding (no podiumd override, no digest in the subchart default) fails."""
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2", alias="oz")])
    make_tgz(
        tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"}}
    )
    write_values_yaml(tmp_path, "{}\n")
    # Helm's "# Source:" names the chart-tree dir by alias ("oz") when one is declared
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/oz"])

    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    assert detail == "1 floating (failing)"
    out = capsys.readouterr().out
    assert "FAILING:" in out
    assert "oz.image.tag: '1.14.2' (FLOATING in the sub-chart's own default)" in out


def test_subchart_image_visibility_finding_annotated_with_its_owning_chart(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """Findings are annotated via the shared lib.chart.resolve_values_path_source; scope_key
    is always a dependency alias-or-name, so only its "chart X@Y" branch is hit."""
    write_chart_yaml(tmp_path, [make_dep("eck-operator", "3.5.0")])
    make_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": "3.5.0"}},
    )
    write_values_yaml(tmp_path, "{}\n")
    stub_render(monkeypatch, libdigestpinningcheck, ["podiumd/charts/eck-operator"])

    ok, _detail = vp.check_subchart_image_visibility(tmp_path, [])

    assert ok is False
    out = capsys.readouterr().out
    assert (
        "eck-operator.image.tag: '3.5.0' (FLOATING in the sub-chart's own default)  [chart eck-operator@3.5.0]" in out
    )


def test_unoverridden_already_pinned_subchart_image_never_fails(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """A PINNED finding (subchart default embeds a digest) is report-only, never fails."""
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


def test_mix_of_floating_and_pinned_findings_fails_overall(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
    """One floating + one pinned: fails overall, with the pinned one in its own report-only section."""
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


def test_nested_subchart_image_path_resolved_correctly(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    """A nested subchart default (e.g. a sidecar) is checked against the same nested podiumd path."""
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


def test_exempted_digest_pinning_path_never_shows_up_as_unresolved(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    """keycloak-operator.operator is overridden by podiumd (split tag/sha), so it has an
    own_tag and must never appear as "unresolved"."""
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


def test_multiple_unresolved_images_all_reported(
    vp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libdigestpinningcheck: ModuleType,
    capsys: pytest.CaptureFixture[str],
):
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


def test_check_subchart_image_visibility_render_failure(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libdigestpinningcheck: ModuleType
):
    monkeypatch.setattr(
        libdigestpinningcheck,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    ok, detail = vp.check_subchart_image_visibility(tmp_path, [])
    assert ok is False
    assert "helm template failed to render" in detail
