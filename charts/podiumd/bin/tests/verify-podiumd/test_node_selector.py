"""check_node_selector / scan_missing_node_selector: every workload kind in
templates/*.yaml must expose a nodeSelector (AKS-Blue convention)."""

from pathlib import Path
from types import ModuleType

import pytest

DEPLOYMENT_WITH_SELECTOR = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frankgateway
spec:
  template:
    spec:
      nodeSelector: {}
      containers:
        - name: apisix
"""

DEPLOYMENT_WITHOUT_SELECTOR = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frankgateway
spec:
  template:
    spec:
      containers:
        - name: apisix
"""


def write_template(chart_dir, name, text):
    templates_dir = chart_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / name).write_text(text, encoding="utf-8")


def test_no_templates_dir_passes(vp: ModuleType, tmp_path: Path):
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_deployment_with_node_selector_passes(vp: ModuleType, tmp_path: Path):
    write_template(tmp_path, "frankgateway.yaml", DEPLOYMENT_WITH_SELECTOR)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_deployment_without_node_selector_flagged(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    write_template(tmp_path, "frankgateway.yaml", DEPLOYMENT_WITHOUT_SELECTOR)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail
    out = capsys.readouterr().out
    assert "frankgateway.yaml" in out
    assert "Deployment/frankgateway" in out


def test_non_workload_kinds_never_flagged(vp: ModuleType, tmp_path: Path):
    """ConfigMap/ServiceAccount/Role/etc. have no pod spec and must never
    be expected to carry a nodeSelector."""
    write_template(tmp_path, "a.yaml", "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n")
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_multi_document_file_isolates_each_resource(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Multi-document file: only the Job is checked, isolated from the other
    documents so they can't hide or fake its nodeSelector."""
    text = (
        "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: sa\n"
        "---\n"
        "apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata:\n  name: role\n"
        "---\n"
        "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: redis-ha-pre-delete\nspec:\n"
        "  template:\n    spec:\n      containers:\n        - name: c\n"
    )
    write_template(tmp_path, "redis-ha-pre-delete.yaml", text)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail
    out = capsys.readouterr().out
    assert "Job/redis-ha-pre-delete" in out
    assert "ServiceAccount" not in out.split("Found")[1]


def test_statefulset_and_daemonset_and_cronjob_also_checked(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_template(tmp_path, "a.yaml", "kind: StatefulSet\nmetadata:\n  name: etcd\n")
    write_template(tmp_path, "b.yaml", "kind: DaemonSet\nmetadata:\n  name: ds\n")
    write_template(tmp_path, "c.yaml", "kind: CronJob\nmetadata:\n  name: cj\n")
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "3 violation(s)" in detail
    out = capsys.readouterr().out
    assert "StatefulSet/etcd" in out
    assert "DaemonSet/ds" in out
    assert "CronJob/cj" in out


def test_multiple_violations_across_files_all_reported(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_template(tmp_path, "a.yaml", DEPLOYMENT_WITHOUT_SELECTOR)
    write_template(tmp_path, "b.yaml", DEPLOYMENT_WITHOUT_SELECTOR.replace("frankgateway", "other"))
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "2 violation(s)" in detail


# A Job whose pod spec (with nodeSelector) lives in a same-file `define`
# block that is `include`-d; the define sits before "---", in a different
# doc-split chunk than "kind: Job".
DEFINE_BLOCK_JOB_WITH_SELECTOR = """\
{{- define "podiumd.testJob.podTemplate" -}}
spec:
  {{- if .Values.nodeSelector }}
  nodeSelector:
    {{- toYaml .Values.nodeSelector | nindent 4 }}
  {{- end }}
  containers:
  - name: seed
{{- end }}
---
{{- $podTemplate := include "podiumd.testJob.podTemplate" . }}
apiVersion: batch/v1
kind: Job
metadata:
  name: test-seed-job
spec:
  template:
    {{- $podTemplate | nindent 4 }}
"""

DEFINE_BLOCK_JOB_WITHOUT_SELECTOR = DEFINE_BLOCK_JOB_WITH_SELECTOR.replace(
    """  {{- if .Values.nodeSelector }}
  nodeSelector:
    {{- toYaml .Values.nodeSelector | nindent 4 }}
  {{- end }}
""",
    "",
)


def test_job_with_selector_in_same_file_define_block_not_flagged(vp: ModuleType, tmp_path: Path):
    write_template(tmp_path, "test-seed-job.yaml", DEFINE_BLOCK_JOB_WITH_SELECTOR)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_job_missing_selector_in_referenced_define_block_still_flagged(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_template(tmp_path, "test-seed-job.yaml", DEFINE_BLOCK_JOB_WITHOUT_SELECTOR)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail
    out = capsys.readouterr().out
    assert "Job/test-seed-job" in out


def test_unrelated_same_file_define_block_never_credited(vp: ModuleType, tmp_path: Path):
    """A same-file `define` that this chunk never `include`s isn't credited."""
    text = (
        DEFINE_BLOCK_JOB_WITHOUT_SELECTOR + '\n---\n{{- define "podiumd.unused.podTemplate" -}}\n'
        "nodeSelector: {}\n"
        "{{- end }}\n"
    )
    write_template(tmp_path, "test-seed-job.yaml", text)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail


def test_non_literal_include_call_never_matches_a_define_name(vp: ModuleType, tmp_path: Path):
    """`include (print ...)` has no quoted name, so it never matches a
    `define` block, even one carrying a nodeSelector."""
    text = (
        '{{- define "podiumd.decoy.podTemplate" -}}\n'
        "nodeSelector: {}\n"
        "{{- end }}\n"
        "---\n"
        '{{- $x := include (print $.Template.BasePath "/decoy.yaml") . -}}\n'
        "apiVersion: batch/v1\n"
        "kind: Job\n"
        "metadata:\n"
        "  name: test-job\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers: []\n"
    )
    write_template(tmp_path, "test-job.yaml", text)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail


def test_scan_missing_node_selector_returns_path_kind_and_name(libnodeselectorcheck: ModuleType, tmp_path: Path):
    write_template(tmp_path, "frankgateway.yaml", DEPLOYMENT_WITHOUT_SELECTOR)
    findings = libnodeselectorcheck.scan_missing_node_selector(tmp_path)
    assert len(findings) == 1
    path, kind, name = findings[0]
    assert path.name == "frankgateway.yaml"
    assert kind == "Deployment"
    assert name == "frankgateway"
