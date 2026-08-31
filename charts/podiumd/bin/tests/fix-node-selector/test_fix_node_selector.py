"""find_fixes/apply_fixes (pure logic) plus a main() integration test
against real files in tmp_path. No git/network/helm needed."""
import pytest

DEPLOYMENT_MISSING = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
      - name: my-app
        image: foo:1.0
"""

DEPLOYMENT_WITH_NODE_SELECTOR = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.azure.com/mode: user
      containers:
      - name: my-app
        image: foo:1.0
"""

# Real chart shape: nested well past a Deployment's own depth.
CRONJOB_MISSING = """apiVersion: batch/v1
kind: CronJob
metadata:
  name: my-cronjob
spec:
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: my-cronjob
            image: foo:1.0
"""

DEPLOYMENT_WITH_INIT_CONTAINERS_ONLY = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      initContainers:
      - name: init
        image: foo:1.0
"""

NON_WORKLOAD = """apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
data:
  foo: bar
"""


def test_find_fixes_deployment_missing_node_selector(sub):
    fixes, unresolved = sub.find_fixes(DEPLOYMENT_MISSING)
    assert unresolved == []
    assert len(fixes) == 1
    insert_at, new_text, kind, name = fixes[0]
    assert kind == "Deployment"
    assert name == "my-app"
    assert new_text == "      nodeSelector:\n        kubernetes.azure.com/mode: user\n"
    # inserted text lands right before the "containers:" line, at its own indent
    assert DEPLOYMENT_MISSING[insert_at:].startswith("      containers:")


def test_find_fixes_already_has_node_selector_is_a_noop(sub):
    fixes, unresolved = sub.find_fixes(DEPLOYMENT_WITH_NODE_SELECTOR)
    assert fixes == []
    assert unresolved == []


def test_find_fixes_non_workload_kind_ignored(sub):
    fixes, unresolved = sub.find_fixes(NON_WORKLOAD)
    assert fixes == []
    assert unresolved == []


def test_find_fixes_cronjob_deep_nesting_anchors_on_containers(sub):
    fixes, unresolved = sub.find_fixes(CRONJOB_MISSING)
    assert unresolved == []
    assert len(fixes) == 1
    insert_at, new_text, kind, name = fixes[0]
    assert kind == "CronJob"
    assert name == "my-cronjob"
    assert new_text == "          nodeSelector:\n            kubernetes.azure.com/mode: user\n"
    assert CRONJOB_MISSING[insert_at:].startswith("          containers:")


def test_find_fixes_init_containers_only_is_unresolved_not_misfixed(sub):
    """initContainers: must never be mistaken for the containers: anchor
    — a workload with only initContainers (no containers: key at all in
    this fixture) has nothing safe to anchor on."""
    fixes, unresolved = sub.find_fixes(DEPLOYMENT_WITH_INIT_CONTAINERS_ONLY)
    assert fixes == []
    assert unresolved == [("Deployment", "my-app")]


def test_apply_fixes_inserts_at_correct_position(sub):
    fixes, _ = sub.find_fixes(DEPLOYMENT_MISSING)
    result = sub.apply_fixes(DEPLOYMENT_MISSING, fixes)
    assert result == DEPLOYMENT_WITH_NODE_SELECTOR


def test_apply_fixes_handles_multiple_documents_without_offset_corruption(sub):
    combined = DEPLOYMENT_MISSING + "---\n" + CRONJOB_MISSING
    fixes, unresolved = sub.find_fixes(combined)
    assert unresolved == []
    assert len(fixes) == 2

    result = sub.apply_fixes(combined, fixes)
    assert result == DEPLOYMENT_WITH_NODE_SELECTOR + "---\n" + (
        "apiVersion: batch/v1\n"
        "kind: CronJob\n"
        "metadata:\n"
        "  name: my-cronjob\n"
        "spec:\n"
        "  jobTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          nodeSelector:\n"
        "            kubernetes.azure.com/mode: user\n"
        "          containers:\n"
        "          - name: my-cronjob\n"
        "            image: foo:1.0\n"
    )


# --- main() integration ---

def make_templates(tmp_path, files):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    for name, content in files.items():
        (templates_dir / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_main_help_flag_prints_usage_and_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_templates(tmp_path, {"deploy.yaml": DEPLOYMENT_MISSING})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == sub.__doc__ + "\n"
    assert (chart_dir / "templates" / "deploy.yaml").read_text(encoding="utf-8") == DEPLOYMENT_MISSING


def test_main_no_findings_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_templates(tmp_path, {"deploy.yaml": DEPLOYMENT_WITH_NODE_SELECTOR})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert "OK:" in capsys.readouterr().out


def test_main_fixes_a_real_file_and_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_templates(tmp_path, {"deploy.yaml": DEPLOYMENT_MISSING})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert (chart_dir / "templates" / "deploy.yaml").read_text(encoding="utf-8") == DEPLOYMENT_WITH_NODE_SELECTOR
    out = capsys.readouterr().out
    assert "Deployment/my-app: inserted nodeSelector" in out
    assert "Inserted nodeSelector into 1 template" in out


def test_main_dry_run_reports_but_does_not_write(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_templates(tmp_path, {"deploy.yaml": DEPLOYMENT_MISSING})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 1
    assert (chart_dir / "templates" / "deploy.yaml").read_text(encoding="utf-8") == DEPLOYMENT_MISSING
    out = capsys.readouterr().out
    assert "would insert nodeSelector" in out
    assert "dry-run" in out


def test_main_unresolved_case_exits_nonzero_and_leaves_file_untouched(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_templates(tmp_path, {"deploy.yaml": DEPLOYMENT_WITH_INIT_CONTAINERS_ONLY})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 1
    assert (chart_dir / "templates" / "deploy.yaml").read_text(encoding="utf-8") == DEPLOYMENT_WITH_INIT_CONTAINERS_ONLY
    assert "review by hand" in capsys.readouterr().out


def test_main_fixes_multiple_files(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_templates(tmp_path, {
        "deploy.yaml": DEPLOYMENT_MISSING,
        "cronjob.yaml": CRONJOB_MISSING,
    })
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert "nodeSelector" in (chart_dir / "templates" / "deploy.yaml").read_text(encoding="utf-8")
    assert "nodeSelector" in (chart_dir / "templates" / "cronjob.yaml").read_text(encoding="utf-8")
    assert "Inserted nodeSelector into 2 template" in capsys.readouterr().out


def test_main_is_idempotent(sub, tmp_path, monkeypatch):
    """Running twice must not insert a second nodeSelector."""
    chart_dir = make_templates(tmp_path, {"deploy.yaml": DEPLOYMENT_MISSING})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-node-selector"])

    with pytest.raises(SystemExit):
        sub.main()
    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    content = (chart_dir / "templates" / "deploy.yaml").read_text(encoding="utf-8")
    assert content.count("nodeSelector:") == 1
