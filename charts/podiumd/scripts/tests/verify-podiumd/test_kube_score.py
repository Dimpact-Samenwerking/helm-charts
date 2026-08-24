"""check_kube_score / run_kube_score / extract_resource_findings — checks
that every container declares CPU/memory requests AND limits, per
.github/copilot-instructions.md's documented "Resource Requests and
Limits" convention (the only kube-score check this repo actually has a
policy for — KUBE_SCORE_CHECK_ID scopes to just "container-resources",
ignoring every other kube-score opinion like NetworkPolicy/
ImagePullPolicy/SecurityContext).

Same own/partner-vendor/other-vendor scope split and per-item vs.
aggregate-only reporting as check_yamllint/check_kubeconform/
check_shellcheck — a partner-vendor finding is printed individually, an
other-vendor finding only gets a one-line count. The *fail* policy still
differs, though: NO vendored finding (partner or not) ever fails the
check regardless — every vendored finding is this repo's job to wire up
(via that sub-chart's values.yaml key), but promoting it to a failure is
a deliberate future step once the backlog is triaged. Only an OWN finding
fails.

kube-score's JSON output carries no per-resource source info (like
kubeconform), so each vendored sub-chart is scored as its own separate
kube-score run to attribute a finding back to its chart. All `helm`/
`kube-score` subprocess calls are mocked via vp.run; friendly_vendor_charts
is mocked too, since these tests use tmp_path (no real Chart.yaml) — no
real kube-score or helm invocation happens in these tests."""
import json
from types import SimpleNamespace


def ks_object(kind, name, checks):
    return {"object_name": f"{kind}/apps/v1//{name}", "checks": checks}


def resource_check(grade, comments=None, skipped=False):
    return {
        "check": {"id": "container-resources", "name": "Container Resources"},
        "grade": grade,
        "skipped": skipped,
        "comments": comments,
    }


def other_check(grade=1, comments=None):
    """A non-container-resources check with a low grade — must never be
    treated as a finding by this check, which only cares about
    container-resources."""
    return {
        "check": {"id": "pod-networkpolicy", "name": "Pod NetworkPolicy"},
        "grade": grade,
        "skipped": False,
        "comments": comments or [{"path": "", "summary": "no matching NetworkPolicy"}],
    }


def ks_result(objects, returncode=1):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(objects), stderr="")


def no_friendly_vendors(libkubescorecheck, monkeypatch):
    monkeypatch.setattr(libkubescorecheck, "friendly_vendor_charts", lambda chart_dir: {})


RENDERED = (
    "---\n"
    "# Source: podiumd/templates/foo.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: foo\n"
    "---\n"
    "# Source: podiumd/charts/zac/templates/deployment.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: zac\n"
)


def sequenced_run(own_objects, vendored_objects_by_chart=None, rendered=RENDERED, ks_returncode=1):
    """helm template --help, helm template (render), one kube-score call
    for this chart's own text, then one kube-score call per distinct
    vendored chart found in the render."""
    vendored_objects_by_chart = vendored_objects_by_chart or {}
    calls = {"n": 0}

    def run(cmd, **kwargs):
        if cmd[0] == "kube-score":
            calls["n"] += 1
            if calls["n"] == 1:
                return ks_result(own_objects, returncode=ks_returncode)
            chart_calls = sorted(vendored_objects_by_chart.keys())
            chart = chart_calls[calls["n"] - 2] if calls["n"] - 2 < len(chart_calls) else None
            return ks_result(vendored_objects_by_chart.get(chart, []), returncode=ks_returncode)
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")

    return run


# --- run_kube_score ---

def test_run_kube_score_normalizes_json_null_to_empty_list(vp, libkubescorecheck, monkeypatch):
    """Regression: kube-score prints the JSON value "null" (not "[]") for a
    stream with no scoreable objects at all (e.g. a vendored sub-chart
    consisting entirely of CRDs). json.loads("null") is None, which must
    NOT be treated the same as "unparseable output" — a CRD-only chart is
    not a crash."""
    monkeypatch.setattr(libkubescorecheck, "run", lambda cmd, **kwargs: SimpleNamespace(returncode=0, stdout="null", stderr=""))
    assert libkubescorecheck.run_kube_score("---\nkind: CustomResourceDefinition\n") == []


def test_run_kube_score_genuinely_unparseable_returns_none(vp, libkubescorecheck, monkeypatch):
    monkeypatch.setattr(libkubescorecheck, "run", lambda cmd, **kwargs: SimpleNamespace(returncode=1, stdout="not json", stderr=""))
    assert libkubescorecheck.run_kube_score("anything") is None


# --- extract_resource_findings ---

def test_extract_resource_findings_ignores_other_checks(libkubescorecheck):
    objects = [ks_object("Deployment", "foo", [other_check()])]
    assert libkubescorecheck.extract_resource_findings(objects) == []


def test_extract_resource_findings_ignores_skipped_and_full_grade(libkubescorecheck):
    objects = [ks_object("Deployment", "foo", [
        resource_check(10, comments=None),
        resource_check(1, comments=[{"path": "x", "summary": "should be skipped"}], skipped=True),
    ])]
    assert libkubescorecheck.extract_resource_findings(objects) == []


def test_extract_resource_findings_returns_object_container_summary(libkubescorecheck):
    objects = [ks_object("Deployment", "foo", [
        resource_check(1, comments=[
            {"path": "app", "summary": "CPU limit is not set"},
            {"path": "app", "summary": "Memory limit is not set"},
        ]),
    ])]
    findings = libkubescorecheck.extract_resource_findings(objects)
    assert findings == [
        ("Deployment/apps/v1//foo", "app", "CPU limit is not set"),
        ("Deployment/apps/v1//foo", "app", "Memory limit is not set"),
    ]


# --- check_kube_score ---

def test_check_kube_score_no_findings_passes(vp, libkubescorecheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(libkubescorecheck, "run", sequenced_run(
        own_objects=[ks_object("Deployment", "foo", [resource_check(10)])],
        vendored_objects_by_chart={"zac": [ks_object("Deployment", "zac", [resource_check(10)])]},
        ks_returncode=0,
    ))

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kube_score_own_finding_fails(vp, libkubescorecheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(libkubescorecheck, "run", sequenced_run(own_objects=[
        ks_object("Deployment", "foo", [resource_check(1, comments=[
            {"path": "app", "summary": "CPU limit is not set"},
            {"path": "app", "summary": "Memory limit is not set"},
        ])]),
    ]))

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "2 real" in detail
    out = capsys.readouterr().out
    assert "fail the check" in out
    assert "Deployment/apps/v1//foo (app)" in out
    assert "CPU limit is not set" in out and "Memory limit is not set" in out


def test_check_kube_score_ignores_non_resource_checks(vp, libkubescorecheck, tmp_path, monkeypatch):
    """A low grade on an unrelated check (e.g. pod-networkpolicy) must
    never be treated as a finding — this check only cares about
    container-resources, the one convention this repo has documented."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(libkubescorecheck, "run", sequenced_run(own_objects=[
        ks_object("Deployment", "foo", [other_check(), resource_check(10)]),
    ]))

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kube_score_partner_vendor_finding_reported_per_item_never_fails(vp, libkubescorecheck, tmp_path, monkeypatch, capsys):
    """A vendored sub-chart from a listed partner org gets its finding
    printed individually (attributed to the chart it came from, since
    kube-score is run once per distinct vendored chart precisely so this
    attribution is possible) but must still never fail."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    monkeypatch.setattr(libkubescorecheck, "friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    monkeypatch.setattr(libkubescorecheck, "run", sequenced_run(
        own_objects=[],
        vendored_objects_by_chart={"zac": [
            ks_object("Deployment", "zac", [resource_check(1, comments=[
                {"path": "zac", "summary": "CPU limit is not set"},
            ])]),
        ]},
    ))

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert "0 real (own" in detail
    assert "1 partner-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "does not fail the check" in out
    assert "[zac] Deployment/apps/v1//zac (zac)" in out
    assert "CPU limit is not set" in out


def test_check_kube_score_other_vendor_finding_aggregate_count_only_never_fails(vp, libkubescorecheck, tmp_path, monkeypatch, capsys):
    """A vendored sub-chart NOT from a listed partner org only ever gets a
    one-line aggregate count — no per-item detail — but still never fails
    (unlike check_yamllint/check_kubeconform/check_shellcheck, this
    finding is still genuinely actionable by this repo, just deprioritized
    in the output)."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(libkubescorecheck, "run", sequenced_run(
        own_objects=[],
        vendored_objects_by_chart={"zac": [
            ks_object("Deployment", "zac", [resource_check(1, comments=[
                {"path": "zac", "summary": "CPU limit is not set"},
            ])]),
        ]},
    ))

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert "0 real (own" in detail
    assert "0 partner-vendor" in detail
    assert "1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "does not fail the check" in out
    assert "1 other vendored" in out
    assert "[zac]" not in out  # per-item detail suppressed for other-vendor
    assert "CPU limit is not set" not in out


def test_check_kube_score_crd_only_vendored_chart_is_not_a_failure(vp, libkubescorecheck, tmp_path, monkeypatch):
    """Regression for the run_kube_score JSON-null-normalization bug: a
    vendored sub-chart consisting entirely of CRDs (kube-score returns
    JSON "null" for it, having nothing to score) must count as 0 findings
    for that chart, not "kube-score produced unparseable output"."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)

    def run(cmd, **kwargs):
        if cmd[0] == "kube-score":
            return SimpleNamespace(returncode=0, stdout="null", stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=RENDERED, stderr="")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kube_score_missing_binary_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_kube_score_render_failure_fails(vp, libkubescorecheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: broke")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_kube_score_unparseable_own_output_fails(vp, libkubescorecheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")

    def run(cmd, **kwargs):
        if cmd[0] == "kube-score":
            return SimpleNamespace(returncode=1, stdout="not json", stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=RENDERED, stderr="")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail


def test_check_kube_score_unparseable_vendored_output_fails(vp, libkubescorecheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    calls = {"n": 0}

    def run(cmd, **kwargs):
        if cmd[0] == "kube-score":
            calls["n"] += 1
            if calls["n"] == 1:
                return ks_result([])
            return SimpleNamespace(returncode=1, stdout="not json", stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=RENDERED, stderr="")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail
