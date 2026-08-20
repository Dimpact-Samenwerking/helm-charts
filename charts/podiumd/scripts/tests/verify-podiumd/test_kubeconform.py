"""check_kubeconform / split_rendered_by_source / run_kubeconform — validates
the full `helm template` render against real Kubernetes API schemas, which
neither `helm lint` nor yamllint check. Unlike yamllint's per-line JSON
output, kubeconform only reports kind/name/version/status per resource, so
scoping (this chart's own templates/ vs. a vendored sub-chart) happens by
splitting the render into separate YAML streams BEFORE validation — one for
this chart's own templates, and one PER DISTINCT vendored chart (so a
finding can still be attributed to the chart it came from, for the
friendly-vendor per-item reporting). All `helm`/`kubeconform` subprocess
calls are mocked via vp.run; friendly_vendor_charts is mocked too, since
these tests use tmp_path (no real Chart.yaml) — no real kubeconform or helm
invocation happens in these tests."""
import json
from types import SimpleNamespace


def kc_result(resources, returncode=1):
    return SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps({"resources": resources, "summary": {}}),
        stderr="",
    )


def no_friendly_vendors(libkubeconformcheck, monkeypatch):
    monkeypatch.setattr(libkubeconformcheck, "friendly_vendor_charts", lambda chart_dir: {})


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


def sequenced_run(own_resources, vendored_resources_by_chart=None, rendered=RENDERED, kc_returncode=1):
    """Simulates: helm template --help, helm template (render), one
    kubeconform call for this chart's own text, then one kubeconform call
    per distinct vendored chart found in the render (in
    vendored_resources_by_chart, keyed by chart name, e.g. {"zac": [...]})."""
    vendored_resources_by_chart = vendored_resources_by_chart or {}
    calls = {"n": 0}

    def run(cmd, **kwargs):
        if cmd[0] == "kubeconform":
            calls["n"] += 1
            if calls["n"] == 1:
                return kc_result(own_resources, returncode=kc_returncode)
            chart_calls = sorted(vendored_resources_by_chart.keys())
            chart = chart_calls[calls["n"] - 2] if calls["n"] - 2 < len(chart_calls) else None
            resources = vendored_resources_by_chart.get(chart, [])
            return kc_result(resources, returncode=kc_returncode)
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")

    return run


# --- split_rendered_by_source ---

def test_split_rendered_by_source_separates_own_and_vendored(librenderscope):
    docs = librenderscope.split_rendered_by_source(RENDERED)
    assert [source for source, _ in docs] == [
        "podiumd/templates/frankgateway.yaml",
        "podiumd/charts/zac/templates/configmap.yaml",
    ]


def test_split_rendered_by_source_keeps_doc_separator(librenderscope):
    docs = librenderscope.split_rendered_by_source(RENDERED)
    _, text = docs[0]
    assert text.startswith("---\n# Source: podiumd/templates/frankgateway.yaml\n")
    assert "kind: Service" in text


# --- check_kubeconform ---

def test_check_kubeconform_no_findings_passes(vp, libkubeconformcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(
        own_resources=[{"kind": "Service", "name": "frankgateway", "status": "statusValid"}],
        vendored_resources_by_chart={"zac": [{"kind": "ConfigMap", "name": "zac-config", "status": "statusValid"}]},
        kc_returncode=0,
    ))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 friendly-vendor, 0 other-vendor"


def test_check_kubeconform_own_schema_violation_fails(vp, libkubeconformcheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(own_resources=[
        {"kind": "Service", "name": "frankgateway", "status": "statusInvalid",
         "msg": "jsonschema validation failed: additional properties 'badField' not allowed"},
    ]))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "1 real" in detail
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "Service/frankgateway" in out
    assert "badField" in out


def test_check_kubeconform_own_parse_error_fails(vp, libkubeconformcheck, tmp_path, monkeypatch, capsys):
    """A resource kubeconform's own YAML parser can't even load (e.g. the
    frankgateway duplicate-key bug) is statusError, not statusInvalid — must
    also fail, same as a schema violation."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(own_resources=[
        {"kind": "Service", "name": "frankgateway", "status": "statusError",
         "msg": 'error unmarshalling resource: yaml: unmarshal errors:\n  line 14: key "x" already set in map'},
    ]))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "1 real" in detail
    out = capsys.readouterr().out
    assert "ERROR" in out


def test_check_kubeconform_skipped_crd_is_not_a_finding(vp, libkubeconformcheck, tmp_path, monkeypatch):
    """statusSkipped (no known schema — expected for this chart's many
    CRDs: Keycloak, ECK, Redis, ...) must never count as a finding."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(
        own_resources=[{"kind": "Keycloak", "name": "keycloak", "status": "statusSkipped"}],
        kc_returncode=0,
    ))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 friendly-vendor, 0 other-vendor"


def test_check_kubeconform_repeated_root_cause_is_grouped(vp, libkubeconformcheck, tmp_path, monkeypatch, capsys):
    """Same shape as the real frankgateway bug: several resources hitting
    the identical parse error must print as one grouped line with an
    occurrence count, not one line per resource."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    msg = 'error unmarshalling resource: yaml: unmarshal errors:\n  line 14: key "app.kubernetes.io/name" already set in map'
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(own_resources=[
        {"kind": "Service", "name": "frankgateway-shim", "status": "statusError", "msg": msg},
        {"kind": "Service", "name": "frankgateway", "status": "statusError", "msg": msg},
        {"kind": "Deployment", "name": "frankgateway", "status": "statusError",
         "msg": msg + '\n  line 29: key "app.kubernetes.io/name" already set in map'},
    ]))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "3 real" in detail
    out = capsys.readouterr().out
    assert out.count("[ERROR  ]") == 1  # one grouped line, not three
    assert "x3" in out
    assert "Service/frankgateway-shim" in out and "Deployment/frankgateway" in out


def test_check_kubeconform_other_vendor_finding_never_fails(vp, libkubeconformcheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(
        own_resources=[],
        vendored_resources_by_chart={"zac": [
            {"kind": "ConfigMap", "name": "zac-config", "status": "statusInvalid",
             "msg": "some upstream schema violation"},
        ]},
    ))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "outside this repo's scope" in out
    assert "never a failure" in out
    assert "some upstream schema violation" not in out  # not dumped in detail


def test_check_kubeconform_friendly_vendor_finding_reported_per_item_never_fails(vp, libkubeconformcheck, tmp_path, monkeypatch, capsys):
    """A vendored sub-chart from a listed partner org gets its finding
    printed individually (attributed to the chart it came from, since
    kubeconform is run once per distinct vendored chart precisely so this
    attribution is possible) but must still never fail."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    monkeypatch.setattr(libkubeconformcheck, "friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    monkeypatch.setattr(libkubeconformcheck, "run", sequenced_run(
        own_resources=[],
        vendored_resources_by_chart={"zac": [
            {"kind": "ConfigMap", "name": "zac-config", "status": "statusInvalid",
             "msg": "additional properties 'badField' not allowed"},
        ]},
    ))

    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 friendly-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "reported for visibility, never a failure" in out
    assert "ConfigMap/zac-config" in out
    assert "Info(NL)" in out
    assert "badField" in out  # per-item detail, not just a count


def test_check_kubeconform_missing_binary_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_kubeconform_render_failure_fails(vp, libkubeconformcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: broke")

    monkeypatch.setattr(libkubeconformcheck, "run", run)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_kubeconform_unparseable_own_output_fails(vp, libkubeconformcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)

    def run(cmd, **kwargs):
        if cmd[0] == "kubeconform":
            return SimpleNamespace(returncode=1, stdout="not json", stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=RENDERED, stderr="")

    monkeypatch.setattr(libkubeconformcheck, "run", run)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail


def test_check_kubeconform_unparseable_vendored_output_fails(vp, libkubeconformcheck, tmp_path, monkeypatch):
    """The own-scope kubeconform call succeeds, but a vendored-chart call
    returns garbage — must still fail with a clear message, not silently
    swallow it as "0 vendored findings"."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kubeconform")
    no_friendly_vendors(libkubeconformcheck, monkeypatch)
    calls = {"n": 0}

    def run(cmd, **kwargs):
        if cmd[0] == "kubeconform":
            calls["n"] += 1
            if calls["n"] == 1:
                return kc_result([])
            return SimpleNamespace(returncode=1, stdout="not json", stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=RENDERED, stderr="")

    monkeypatch.setattr(libkubeconformcheck, "run", run)
    ok, detail = vp.check_kubeconform(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail
