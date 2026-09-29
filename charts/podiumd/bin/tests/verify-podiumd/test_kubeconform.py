"""check_kubeconform / split_rendered_by_source / run_kubeconform: validate the
render against Kubernetes API schemas.

kubeconform reports no source file, so the render is split into one stream for
own templates and one per vendored chart before validation. vp.run and
friendly_vendor_charts are mocked."""

import json

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


def kc_result(resources, returncode=1):
    return SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps({"resources": resources, "summary": {}}),
        stderr="",
    )


def no_friendly_vendors(libkubeconformcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("lib.render_scope.friendly_vendor_charts", lambda chart_dir: {})


RENDERED = (
    "---\n"
    "# Source: podiumd/templates/frankgateway.yaml\n"
    "apiVersion: v1\n"
    "kind: Service\n"
    "metadata:\n"
    "  name: frankgateway\n"
    "---\n"
    "# Source: podiumd/charts/zac/templates/configmap.yaml\n"
    "apiVersion: v1\n"
    "kind: ConfigMap\n"
    "metadata:\n"
    "  name: zac-config\n"
)


def fake_render_chart(rendered=RENDERED, returncode=0):
    def render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")

    return render_chart


@pytest.fixture(autouse=True)
def _default_render(monkeypatch: pytest.MonkeyPatch):
    """Default every test to the RENDERED fixture via render_chart; override
    by patching lib.render_scope.render_chart."""
    monkeypatch.setattr("lib.render_scope.render_chart", fake_render_chart(RENDERED))


def sequenced_run(own_resources, vendored_resources_by_chart=None, kc_returncode=1):
    """All run() calls are kubeconform: one for own text, then one per
    vendored chart (vendored_resources_by_chart, keyed by chart name)."""
    vendored_resources_by_chart = vendored_resources_by_chart or {}
    calls = {"n": 0}

    def run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return kc_result(own_resources, returncode=kc_returncode)
        chart_calls = sorted(vendored_resources_by_chart.keys())
        chart = chart_calls[calls["n"] - 2] if calls["n"] - 2 < len(chart_calls) else None
        resources = vendored_resources_by_chart.get(chart, [])
        return kc_result(resources, returncode=kc_returncode)

    return run


# --- run_kubeconform / schema cache ---


def test_run_kubeconform_creates_cache_dir_and_passes_cache_flag(
    libkubeconformcheck: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """kubeconform errors if the -cache directory doesn't exist, so it must be
    created first and the flag passed."""
    cache_dir = tmp_path / "kubeconform-schema-cache"
    monkeypatch.setattr(libkubeconformcheck, "kubeconform_cache_dir", lambda: cache_dir)
    assert not cache_dir.exists()

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return kc_result([])

    monkeypatch.setattr(libkubeconformcheck, "run", fake_run)
    libkubeconformcheck.run_kubeconform("apiVersion: v1\nkind: ConfigMap\n")

    assert cache_dir.is_dir()
    assert "-cache" in captured["cmd"]
    assert str(cache_dir) in captured["cmd"]


# --- split_rendered_by_source ---


def test_split_rendered_by_source_separates_own_and_vendored(librenderscope: ModuleType):
    docs = librenderscope.split_rendered_by_source(RENDERED)
    assert [source for source, _ in docs] == [
        "podiumd/templates/frankgateway.yaml",
        "podiumd/charts/zac/templates/configmap.yaml",
    ]


def test_split_rendered_by_source_keeps_doc_separator(librenderscope: ModuleType):
    docs = librenderscope.split_rendered_by_source(RENDERED)
    _, text = docs[0]
    assert text.startswith("---\n# Source: podiumd/templates/frankgateway.yaml\n")
    assert "kind: Service" in text


# --- check_kubeconform ---


def test_check_kubeconform_no_findings_passes(
    vp: ModuleType, libkubeconformcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[{"kind": "Service", "name": "frankgateway", "status": "statusValid"}],
            vendored_resources_by_chart={"zac": [{"kind": "ConfigMap", "name": "zac-config", "status": "statusValid"}]},
            kc_returncode=0,
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kubeconform_own_schema_violation_fails(
    vp: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[
                {
                    "kind": "Service",
                    "name": "frankgateway",
                    "status": "statusInvalid",
                    "msg": "jsonschema validation failed: additional properties 'badField' not allowed",
                },
            ]
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "1 real" in detail
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Service/frankgateway" in out
    assert "badField" in out


def test_check_kubeconform_own_finding_includes_rendered_line(
    vp: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """The resource's metadata.name line (3, after "# Source:" on 2) is
    printed alongside kind/name."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[
                {"kind": "Service", "name": "frankgateway", "status": "statusInvalid", "msg": "bad"},
            ]
        ),
    )

    vp.check_kubeconform(tmp_path, [])

    out = capsys.readouterr().out
    assert "Service/frankgateway (rendered line 3)" in out


def test_check_kubeconform_own_parse_error_fails(
    vp: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """An unloadable resource (statusError, e.g. a duplicate key) fails like
    a schema violation."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[
                {
                    "kind": "Service",
                    "name": "frankgateway",
                    "status": "statusError",
                    "msg": (
                        'error unmarshalling resource: yaml: unmarshal errors:\n  line 14: key "x" already set in map'
                    ),
                },
            ]
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "1 real" in detail
    out = capsys.readouterr().out
    assert "ERROR" in out


def test_check_kubeconform_skipped_crd_is_not_a_finding(
    vp: ModuleType, libkubeconformcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """statusSkipped (no schema, e.g. CRDs) is never a finding."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[{"kind": "Keycloak", "name": "keycloak", "status": "statusSkipped"}],
            kc_returncode=0,
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kubeconform_repeated_root_cause_is_grouped(
    vp: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Identical parse errors print as one grouped line with a count."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    msg = (
        "error unmarshalling resource: yaml: unmarshal errors:\n"
        '  line 14: key "app.kubernetes.io/name" already set in map'
    )
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[
                {"kind": "Service", "name": "frankgateway-shim", "status": "statusError", "msg": msg},
                {"kind": "Service", "name": "frankgateway", "status": "statusError", "msg": msg},
                {
                    "kind": "Deployment",
                    "name": "frankgateway",
                    "status": "statusError",
                    "msg": msg + '\n  line 29: key "app.kubernetes.io/name" already set in map',
                },
            ]
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "3 real" in detail
    out = capsys.readouterr().out
    assert out.count("[ERROR  ]") == 1  # one grouped line, not three
    assert "x3" in out
    assert "Service/frankgateway-shim" in out and "Deployment/frankgateway" in out


def test_check_kubeconform_other_vendor_finding_never_fails(
    vp: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[],
            vendored_resources_by_chart={
                "zac": [
                    {
                        "kind": "ConfigMap",
                        "name": "zac-config",
                        "status": "statusInvalid",
                        "msg": "some upstream schema violation",
                    },
                ]
            },
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "outside this repo's scope" in out
    assert "never a failure" in out
    assert "some upstream schema violation" not in out  # not dumped in detail


def test_check_kubeconform_friendly_vendor_finding_reported_per_item_never_fails(
    vp: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A partner-vendor finding is printed per item, attributed to its chart,
    but never fails."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    monkeypatch.setattr("lib.render_scope.friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        sequenced_run(
            own_resources=[],
            vendored_resources_by_chart={
                "zac": [
                    {
                        "kind": "ConfigMap",
                        "name": "zac-config",
                        "status": "statusInvalid",
                        "msg": "additional properties 'badField' not allowed",
                    },
                ]
            },
        ),
    )

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 partner-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "reported for visibility, never a failure" in out
    assert "ConfigMap/zac-config (rendered line 9)" in out
    assert "Info(NL)" in out
    assert "badField" in out  # per-item detail, not just a count


def test_check_kubeconform_missing_binary_fails(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_kubeconform_render_failure_fails(
    vp: ModuleType, libkubeconformcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    monkeypatch.setattr("lib.render_scope.render_chart", fake_render_chart("", returncode=1))
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_kubeconform_unparseable_own_output_fails(
    vp: ModuleType, libkubeconformcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="not json", stderr="")

    monkeypatch.setattr(libkubeconformcheck, "run", run)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail


def test_check_kubeconform_unparseable_vendored_output_fails(
    vp: ModuleType, libkubeconformcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Garbage output from a vendored-chart call fails with a clear message,
    not "0 vendored findings"."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    calls = {"n": 0}

    def run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return kc_result([])
        return SimpleNamespace(returncode=1, stdout="not json", stderr="")

    monkeypatch.setattr(libkubeconformcheck, "run", run)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail
