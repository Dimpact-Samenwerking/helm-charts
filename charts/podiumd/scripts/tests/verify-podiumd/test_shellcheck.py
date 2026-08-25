"""check_shellcheck / find_shell_scripts / extract_shell_scripts /
run_shellcheck — lints every shell script embedded in a container's
command/args (this chart's `command: [".../sh", "-c"], args: [<script>]` /
`command: [...], args: ["-c", <script>]` convention). Same own/vendored
scope split as check_yamllint/check_kubeconform: only error/warning-level
findings in this chart's OWN templates fail; a partner-vendor finding
(Maykin/Info(NL)/ICATT/Worth/WeAreFrank/Dimpact/local) is printed per-item
but never fails; any other vendored finding only ever gets a one-line
aggregate count; info/style are cosmetic and never reported anywhere. All
`helm`/`shellcheck` subprocess calls are mocked via vp.run;
friendly_vendor_charts is mocked too, since these tests use tmp_path (no
real Chart.yaml) — no real shellcheck or helm invocation happens in these
tests."""
import json
from types import SimpleNamespace


def sc_result(comments, returncode=1):
    return SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps({"comments": comments}),
        stderr="",
    )


def no_friendly_vendors(libshellcheckcheck, monkeypatch):
    monkeypatch.setattr(libshellcheckcheck, "friendly_vendor_charts", lambda chart_dir: {})


RENDERED = (
    "---\n"
    "# Source: podiumd/templates/keycloak-ensure-operator-sa.yaml\n"
    "apiVersion: batch/v1\n"
    "kind: Job\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: wait\n"
    "          image: curlimages/curl\n"
    "          command: [\"/bin/sh\", \"-c\"]\n"
    "          args:\n"
    "            - |\n"
    "              set -euo pipefail\n"
    "              echo hi\n"
    "---\n"
    "# Source: podiumd/charts/zac/templates/deployment.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      initContainers:\n"
    "        - name: wait-for-db\n"
    "          command: [\"sh\", \"-c\", \"until nc -z db 5432; do sleep 1; done\"]\n"
)


# --- find_shell_scripts ---

def test_find_shell_scripts_detects_command_then_args_pattern(libshellcheckcheck):
    manifest = {
        "spec": {"containers": [
            {"name": "a", "command": ["/bin/sh", "-c"], "args": ["echo hi"]},
        ]}
    }
    found = libshellcheckcheck.find_shell_scripts(manifest, "podiumd/templates/x.yaml")
    assert len(found) == 1
    source, path, shell, script = found[0]
    assert shell == "sh"
    assert script == "echo hi"


def test_find_shell_scripts_detects_command_only_pattern(libshellcheckcheck):
    manifest = {"command": ["sh", "-c", "echo hi"]}
    found = libshellcheckcheck.find_shell_scripts(manifest, "podiumd/templates/x.yaml")
    assert len(found) == 1
    assert found[0][2] == "sh"
    assert found[0][3] == "echo hi"


def test_find_shell_scripts_ignores_non_shell_commands(libshellcheckcheck):
    manifest = {"command": ["/usr/bin/curl", "-c", "not-a-shell-flag-context"]}
    found = libshellcheckcheck.find_shell_scripts(manifest, "podiumd/templates/x.yaml")
    # "curl" is not a recognized shell name, so this must not be treated as one
    assert found == []


def test_find_shell_scripts_recurses_into_nested_structures(libshellcheckcheck):
    manifest = {
        "spec": {"template": {"spec": {"initContainers": [
            {"name": "a", "command": ["bash", "-c", "echo one"]},
        ], "containers": [
            {"name": "b", "command": ["dash", "-c", "echo two"]},
        ]}}}
    }
    found = libshellcheckcheck.find_shell_scripts(manifest, "podiumd/templates/x.yaml")
    assert {f[3] for f in found} == {"echo one", "echo two"}


# --- check_shellcheck ---

def sequenced_run(own_comments, vendored_comments=None, rendered=RENDERED, sc_returncode=1):
    """helm template --help, helm template (render), then one shellcheck
    call per embedded script found — own scripts first (in render order),
    then vendored."""
    calls = {"n": 0}

    def run(cmd, **kwargs):
        if cmd[0] == "shellcheck":
            calls["n"] += 1
            comments = own_comments if calls["n"] == 1 else (vendored_comments or [])
            return sc_result(comments, returncode=sc_returncode)
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")

    return run


def test_check_shellcheck_no_findings_passes(vp, libshellcheckcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(own_comments=[], vendored_comments=[], sc_returncode=0))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_shellcheck_own_warning_fails(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(own_comments=[
        {"level": "warning", "code": 3040, "line": 1,
         "message": "In POSIX sh, set option pipefail is undefined."},
    ]))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    assert "1 real" in detail
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "SC3040" in out
    assert "pipefail" in out


def test_check_shellcheck_own_error_fails(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(own_comments=[
        {"level": "error", "code": 1072, "line": 2, "message": "Unexpected token."},
    ]))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    out = capsys.readouterr().out
    assert "ERROR" in out


def test_check_shellcheck_location_includes_script_line_and_column(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    """Beyond source/path, each location also shows shellcheck's own
    line (and column, when shellcheck reports one) — position within
    the embedded script text, not the rendered YAML."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(own_comments=[
        {"level": "warning", "code": 2086, "line": 3, "column": 6,
         "message": "Double quote to prevent globbing and word splitting."},
    ]))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    out = capsys.readouterr().out
    assert "script line 3:6" in out


def test_check_shellcheck_location_line_without_column(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    """A finding with a line but no column still shows the line alone,
    not a bare trailing colon."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(own_comments=[
        {"level": "error", "code": 1072, "line": 2, "message": "Unexpected token."},
    ]))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    out = capsys.readouterr().out
    assert "script line 2" in out
    assert "script line 2:" not in out


def test_check_shellcheck_info_and_style_never_reported(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    """info/style findings are cosmetic — not just non-failing, not
    mentioned in output or detail at all, same policy as yamllint."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(own_comments=[
        {"level": "info", "code": 2086, "line": 1, "message": "Double quote to prevent globbing."},
        {"level": "style", "code": 2006, "line": 2, "message": "Use $(...) instead of legacy backticks."},
    ]))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"
    out = capsys.readouterr().out
    assert "2086" not in out
    assert "2006" not in out


def test_check_shellcheck_repeated_root_cause_is_grouped(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)

    def run(cmd, **kwargs):
        if cmd[0] == "shellcheck":
            return sc_result([
                {"level": "warning", "code": 3040, "line": 1,
                 "message": "In POSIX sh, set option pipefail is undefined."},
            ])
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        # two own scripts with the identical shellcheck finding
        rendered = (
            "---\n"
            "# Source: podiumd/templates/a.yaml\n"
            "spec:\n"
            "  containers:\n"
            "    - command: [\"/bin/sh\", \"-c\"]\n"
            "      args: [\"set -euo pipefail\\necho a\"]\n"
            "---\n"
            "# Source: podiumd/templates/b.yaml\n"
            "spec:\n"
            "  containers:\n"
            "    - command: [\"/bin/sh\", \"-c\"]\n"
            "      args: [\"set -euo pipefail\\necho b\"]\n"
        )
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")

    monkeypatch.setattr(libshellcheckcheck, "run", run)
    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    assert "2 real" in detail
    out = capsys.readouterr().out
    assert out.count("[WARNING") == 1  # one grouped line, not two
    assert "x2" in out


def test_check_shellcheck_other_vendor_finding_never_fails(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(
        own_comments=[],
        vendored_comments=[{"level": "error", "code": 1072, "line": 1, "message": "Unexpected token."}],
    ))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "outside this repo's scope" in out
    assert "never a failure" in out
    assert "Unexpected token" not in out  # not dumped in detail


def test_check_shellcheck_friendly_vendor_finding_reported_per_item_never_fails(vp, libshellcheckcheck, tmp_path, monkeypatch, capsys):
    """A vendored sub-chart from a listed partner org (here: zac -> Info(NL))
    gets its finding printed individually — unlike a plain vendored
    finding, which only ever gets an aggregate count — but must still
    never fail."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    monkeypatch.setattr(libshellcheckcheck, "friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    monkeypatch.setattr(libshellcheckcheck, "run", sequenced_run(
        own_comments=[],
        vendored_comments=[{"level": "error", "code": 1072, "line": 1, "message": "Unexpected token."}],
    ))

    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 partner-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "reported for visibility, never a failure" in out
    assert "Info(NL)" in out
    assert "Unexpected token" in out  # per-item detail, not just a count
    assert "podiumd/charts/zac/templates/deployment.yaml" in out
    assert "script line 1" in out  # location detail survives alongside the vendor tag


def test_check_shellcheck_no_scripts_found_passes(vp, libshellcheckcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "shellcheck":
            raise AssertionError("shellcheck should never be invoked — no scripts to check")
        return SimpleNamespace(returncode=0, stdout="---\n# Source: podiumd/templates/x.yaml\nkind: ConfigMap\n", stderr="")

    monkeypatch.setattr(libshellcheckcheck, "run", run)
    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is True
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"


def test_check_shellcheck_missing_binary_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_shellcheck_render_failure_fails(vp, libshellcheckcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: broke")

    monkeypatch.setattr(libshellcheckcheck, "run", run)
    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_shellcheck_unparseable_output_fails(vp, libshellcheckcheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/shellcheck")
    no_friendly_vendors(libshellcheckcheck, monkeypatch)

    def run(cmd, **kwargs):
        if cmd[0] == "shellcheck":
            return SimpleNamespace(returncode=1, stdout="not json", stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=RENDERED, stderr="")

    monkeypatch.setattr(libshellcheckcheck, "run", run)
    ok, detail = vp.check_shellcheck(tmp_path, [])
    assert ok is False
    assert "unparseable" in detail
