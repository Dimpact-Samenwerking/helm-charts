"""check_kube_score / run_kube_score / extract_resource_findings: every
container declares CPU/memory requests and limits.

Only the "container-resources" check is enforced. Partner-vendor findings are
printed per item, other-vendor ones only counted; only own findings fail.
kube-score output has no source info, so each vendored chart is scored in a
separate run. vp.run and friendly_vendor_charts are mocked."""

import json

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


def ks_object(kind, name, checks):
    return {"object_name": f"{kind}/apps/v1//{name}", "checks": checks}


def resource_check(grade, comments=None, *, skipped=False):
    return {
        "check": {"id": "container-resources", "name": "Container Resources"},
        "grade": grade,
        "skipped": skipped,
        "comments": comments,
    }


def other_check(grade=1, comments=None):
    """A low grade on another check is never a finding."""
    return {
        "check": {"id": "pod-networkpolicy", "name": "Pod NetworkPolicy"},
        "grade": grade,
        "skipped": False,
        "comments": comments or [{"path": "", "summary": "no matching NetworkPolicy"}],
    }


def ks_result(objects, returncode=1):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(objects), stderr="")


def no_friendly_vendors(libkubescorecheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
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


def fake_render_chart(rendered=RENDERED, returncode=0):
    def render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")

    return render_chart


@pytest.fixture(autouse=True)
def _default_render(monkeypatch: pytest.MonkeyPatch):
    """Default every test to the RENDERED fixture via render_chart; override
    by patching lib.render_scope.render_chart."""
    monkeypatch.setattr("lib.render_scope.render_chart", fake_render_chart(RENDERED))


def sequenced_run(own_objects, vendored_objects_by_chart=None, ks_returncode=1):
    """All run() calls are kube-score: one for own text, then one per vendored
    chart. Extra calls raise, so over-invocation can't pass as "0 findings"."""
    vendored_objects_by_chart = vendored_objects_by_chart or {}
    chart_calls = sorted(vendored_objects_by_chart.keys())
    calls = {"n": 0}

    def run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ks_result(own_objects, returncode=ks_returncode)
        index = calls["n"] - 2
        if index >= len(chart_calls):
            pytest.fail(f"unexpected extra kube-score call #{calls['n']} (expected {1 + len(chart_calls)})")
        return ks_result(vendored_objects_by_chart[chart_calls[index]], returncode=ks_returncode)

    return run


# --- run_kube_score ---


def test_run_kube_score_normalizes_json_null_to_empty_list(
    vp: ModuleType, libkubescorecheck: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """Regression: kube-score prints "null" for a stream with nothing to score
    (e.g. CRD-only); that is not unparseable output."""
    monkeypatch.setattr(
        libkubescorecheck, "run", lambda cmd, **kwargs: SimpleNamespace(returncode=0, stdout="null", stderr="")
    )
    assert libkubescorecheck.run_kube_score("---\nkind: CustomResourceDefinition\n") == []


def test_run_kube_score_genuinely_unparseable_returns_none(
    vp: ModuleType, libkubescorecheck: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        libkubescorecheck, "run", lambda cmd, **kwargs: SimpleNamespace(returncode=1, stdout="not json", stderr="")
    )
    assert libkubescorecheck.run_kube_score("anything") is None


# --- extract_resource_findings ---


def test_extract_resource_findings_ignores_other_checks(libkubescorecheck: ModuleType):
    objects = [ks_object("Deployment", "foo", [other_check()])]
    assert libkubescorecheck.extract_resource_findings(objects, "container-resources") == []


def test_extract_resource_findings_ignores_skipped_and_full_grade(libkubescorecheck: ModuleType):
    objects = [
        ks_object(
            "Deployment",
            "foo",
            [
                resource_check(10, comments=None),
                resource_check(1, comments=[{"path": "x", "summary": "should be skipped"}], skipped=True),
            ],
        )
    ]
    assert libkubescorecheck.extract_resource_findings(objects, "container-resources") == []


def test_extract_resource_findings_returns_object_container_summary(libkubescorecheck: ModuleType):
    objects = [
        ks_object(
            "Deployment",
            "foo",
            [
                resource_check(
                    1,
                    comments=[
                        {"path": "app", "summary": "CPU limit is not set"},
                        {"path": "app", "summary": "Memory limit is not set"},
                    ],
                ),
            ],
        )
    ]
    findings = libkubescorecheck.extract_resource_findings(objects, "container-resources")
    assert findings == [
        ("Deployment/apps/v1//foo", "app", "CPU limit is not set"),
        ("Deployment/apps/v1//foo", "app", "Memory limit is not set"),
    ]


# --- check_kube_score ---


def test_check_kube_score_no_findings_passes(
    vp: ModuleType, libkubescorecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(
        libkubescorecheck,
        "run",
        sequenced_run(
            own_objects=[ks_object("Deployment", "foo", [resource_check(10)])],
            vendored_objects_by_chart={"zac": [ks_object("Deployment", "zac", [resource_check(10)])]},
            ks_returncode=0,
        ),
    )

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kube_score_own_finding_fails(
    vp: ModuleType,
    libkubescorecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(
        libkubescorecheck,
        "run",
        sequenced_run(
            own_objects=[
                ks_object(
                    "Deployment",
                    "foo",
                    [
                        resource_check(
                            1,
                            comments=[
                                {"path": "app", "summary": "CPU limit is not set"},
                                {"path": "app", "summary": "Memory limit is not set"},
                            ],
                        )
                    ],
                ),
            ],
            # zac still gets its own per-vendored-chart run; findings irrelevant here.
            vendored_objects_by_chart={"zac": []},
        ),
    )

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "2 real" in detail
    out = capsys.readouterr().out
    assert "fail the check" in out
    assert "Deployment/apps/v1//foo (app) — rendered line 3" in out
    assert "CPU limit is not set" in out and "Memory limit is not set" in out


def test_check_kube_score_ignores_non_resource_checks(
    vp: ModuleType, libkubescorecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A low grade on an unrelated check (e.g. pod-networkpolicy) is ignored."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(
        libkubescorecheck,
        "run",
        sequenced_run(
            own_objects=[
                ks_object("Deployment", "foo", [other_check(), resource_check(10)]),
            ],
            vendored_objects_by_chart={"zac": []},
        ),
    )

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kube_score_partner_vendor_finding_reported_per_item_never_fails(
    vp: ModuleType,
    libkubescorecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A partner-vendor finding is printed per item, attributed to its chart,
    but never fails."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    monkeypatch.setattr(libkubescorecheck, "friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    monkeypatch.setattr(
        libkubescorecheck,
        "run",
        sequenced_run(
            own_objects=[],
            vendored_objects_by_chart={
                "zac": [
                    ks_object(
                        "Deployment",
                        "zac",
                        [
                            resource_check(
                                1,
                                comments=[
                                    {"path": "zac", "summary": "CPU limit is not set"},
                                ],
                            )
                        ],
                    ),
                ]
            },
        ),
    )

    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert "0 real (own" in detail
    assert "1 partner-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "does not fail the check" in out
    assert "[zac] Deployment/apps/v1//zac (zac) — rendered line 9" in out
    assert "CPU limit is not set" in out


def test_check_kube_score_other_vendor_finding_aggregate_count_only_never_fails(
    vp: ModuleType,
    libkubescorecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """An other-vendor finding only gets an aggregate count, and never fails."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    monkeypatch.setattr(
        libkubescorecheck,
        "run",
        sequenced_run(
            own_objects=[],
            vendored_objects_by_chart={
                "zac": [
                    ks_object(
                        "Deployment",
                        "zac",
                        [
                            resource_check(
                                1,
                                comments=[
                                    {"path": "zac", "summary": "CPU limit is not set"},
                                ],
                            )
                        ],
                    ),
                ]
            },
        ),
    )

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


def test_check_kube_score_crd_only_vendored_chart_is_not_a_failure(
    vp: ModuleType, libkubescorecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A CRD-only vendored chart (kube-score "null") counts as 0 findings."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="null", stderr="")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_kube_score_missing_binary_fails(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_kube_score_render_failure_fails(
    vp: ModuleType, libkubescorecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    monkeypatch.setattr("lib.render_scope.render_chart", fake_render_chart("", returncode=1))
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_kube_score_unparseable_own_output_fails(
    vp: ModuleType, libkubescorecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="not json", stderr="")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail


def test_check_kube_score_unparseable_vendored_output_fails(
    vp: ModuleType, libkubescorecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/kube-score")
    no_friendly_vendors(libkubescorecheck, monkeypatch)
    calls = {"n": 0}

    def run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ks_result([])
        return SimpleNamespace(returncode=1, stdout="not json", stderr="")

    monkeypatch.setattr(libkubescorecheck, "run", run)
    ok, detail = vp.check_kube_score(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail


# --- parse_kube_score_object_name ---


def test_parse_kube_score_object_name_core_resource_no_namespace(libkubescorecheck: ModuleType):
    assert libkubescorecheck.parse_kube_score_object_name("Service/v1//pabc") == ("Service", "", "pabc")


def test_parse_kube_score_object_name_grouped_api_version_with_namespace(libkubescorecheck: ModuleType):
    """apiVersion may contain "/" (e.g. "batch/v1"): kind parses from the
    front, name/namespace from the back."""
    assert libkubescorecheck.parse_kube_score_object_name(
        "Job/batch/v1/podiumd-minikube/zookeeper-operator-post-install-upgrade"
    ) == ("Job", "podiumd-minikube", "zookeeper-operator-post-install-upgrade")


def test_parse_kube_score_object_name_unrecognized_shape_returns_none(libkubescorecheck: ModuleType):
    assert libkubescorecheck.parse_kube_score_object_name("not-the-expected-shape") == (None, None, None)
