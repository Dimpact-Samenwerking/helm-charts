"""check_node_selector / scan_missing_node_selector — every
Deployment/StatefulSet/DaemonSet/Job/CronJob in templates/*.yaml must
expose a nodeSelector field somewhere in its document, per
.github/copilot-instructions.md's AKS-Blue convention."""

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


def test_no_templates_dir_passes(vp, tmp_path):
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_deployment_with_node_selector_passes(vp, tmp_path):
    write_template(tmp_path, "frankgateway.yaml", DEPLOYMENT_WITH_SELECTOR)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_deployment_without_node_selector_flagged(vp, tmp_path, capsys):
    write_template(tmp_path, "frankgateway.yaml", DEPLOYMENT_WITHOUT_SELECTOR)
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "1 violation(s)" in detail
    out = capsys.readouterr().out
    assert "frankgateway.yaml" in out
    assert "Deployment/frankgateway" in out


def test_non_workload_kinds_never_flagged(vp, tmp_path):
    """ConfigMap/ServiceAccount/Role/etc. have no pod spec and must never
    be expected to carry a nodeSelector."""
    write_template(tmp_path, "a.yaml", "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n")
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is True
    assert "0 violation(s)" in detail


def test_multi_document_file_isolates_each_resource(vp, tmp_path, capsys):
    """redis-ha-pre-delete.yaml's shape: ServiceAccount + Role + RoleBinding
    + Job in one file, separated by bare `---` lines — only the Job (a
    workload kind) should be checked, and it must be isolated from the
    other three documents so an unrelated resource's content can't hide or
    fake a nodeSelector for it."""
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


def test_statefulset_and_daemonset_and_cronjob_also_checked(vp, tmp_path, capsys):
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


def test_multiple_violations_across_files_all_reported(vp, tmp_path, capsys):
    write_template(tmp_path, "a.yaml", DEPLOYMENT_WITHOUT_SELECTOR)
    write_template(tmp_path, "b.yaml", DEPLOYMENT_WITHOUT_SELECTOR.replace("frankgateway", "other"))
    ok, detail = vp.check_node_selector(tmp_path)
    assert ok is False
    assert "2 violation(s)" in detail


def test_scan_missing_node_selector_returns_path_kind_and_name(libnodeselectorcheck, tmp_path):
    write_template(tmp_path, "frankgateway.yaml", DEPLOYMENT_WITHOUT_SELECTOR)
    findings = libnodeselectorcheck.scan_missing_node_selector(tmp_path)
    assert len(findings) == 1
    path, kind, name = findings[0]
    assert path.name == "frankgateway.yaml"
    assert kind == "Deployment"
    assert name == "frankgateway"
