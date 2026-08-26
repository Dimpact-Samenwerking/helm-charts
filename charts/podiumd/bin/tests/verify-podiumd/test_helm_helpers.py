"""check_lint, check_render, report_largest_templates,
report_errors_by_subchart — with `helm`/`git` subprocess calls mocked out
via vp.run, so these tests need neither tool installed nor network access.
check_dependencies now lives in lib.dependencies (also used by
set-image-digests.py) — see tests/lib/test_dependencies.py."""
from types import SimpleNamespace


def fake_run(returncode=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


# --- check_lint ---

def test_check_lint_passes_on_clean_output(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "1 chart(s) linted, 0 chart(s) failed\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is True
    assert detail == "0 error(s), 0 warning(s)"


def test_check_lint_fails_on_error_count(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "[ERROR] values.yaml: bad\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is False
    assert "1 error(s)" in detail


def test_check_lint_fails_on_nonzero_returncode(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(1, "", "boom"))
    ok, _ = vp.check_lint(tmp_path, [])
    assert ok is False


def test_check_lint_counts_warnings_without_failing(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "[WARNING] Chart.yaml: icon is recommended\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is True
    assert "1 warning(s)" in detail


# --- check_render ---

def test_check_render_success(vp, tmp_path, monkeypatch):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n---\n# Source: podiumd/templates/b.yaml\nkind: Bar\n"
    monkeypatch.setattr(vp, "run", fake_run(0, rendered, ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is True
    assert detail == "2 manifests"


def test_check_render_failure_reports_error(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(1, "", "Error: something broke"))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_render_zero_manifests_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "", ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is False
    assert "0 manifests" in detail


# --- report_largest_templates / report_errors_by_subchart (just check they don't crash and print something sensible) ---

def test_report_largest_templates_output(vp, capsys):
    text = "# Source: a.yaml\nline\nline\n# Source: b.yaml\nline\n"
    vp.report_largest_templates(text)
    out = capsys.readouterr().out
    assert "a.yaml" in out and "b.yaml" in out


def test_report_largest_templates_no_sources_prints_nothing(vp, capsys):
    vp.report_largest_templates("no source markers here")
    assert capsys.readouterr().out == ""


def test_report_errors_by_subchart_groups_by_chart(vp, capsys):
    text = "Error: zac/templates/a.yaml:1\nError: zac/templates/b.yaml:2\nError: openzaak/templates/c.yaml:1\n"
    vp.report_errors_by_subchart(text)
    out = capsys.readouterr().out
    assert "zac: 2" in out
    assert "openzaak: 1" in out


# --- build_resource_locations / resource_line ---
# shared by check_kubeconform/check_kube_score/check_shellcheck to attach a
# "(rendered line N)" debugging hint to a finding — none of those three
# tools reports a line number of its own.

def test_build_resource_locations_maps_kind_name_to_start_line(librenderscope):
    rendered = (
        "---\n"
        "# Source: podiumd/templates/a.yaml\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: foo\n"
    )
    locations = librenderscope.build_resource_locations(rendered)
    assert locations == {("Service", "", "foo"): 3}


def test_build_resource_locations_captures_namespace(librenderscope):
    rendered = (
        "---\n"
        "# Source: podiumd/templates/a.yaml\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: foo\n"
        "  namespace: podiumd\n"
    )
    locations = librenderscope.build_resource_locations(rendered)
    assert locations == {("Service", "podiumd", "foo"): 3}


def test_build_resource_locations_skips_resource_without_name(librenderscope):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Service\n"
    assert librenderscope.build_resource_locations(rendered) == {}


def test_build_resource_locations_multiple_documents(librenderscope):
    rendered = (
        "---\n"
        "# Source: podiumd/templates/a.yaml\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: foo\n"
        "---\n"
        "# Source: podiumd/templates/b.yaml\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: bar\n"
    )
    locations = librenderscope.build_resource_locations(rendered)
    assert locations[("Service", "", "foo")] == 3
    assert locations[("ConfigMap", "", "bar")] == 8


def test_resource_line_exact_match_with_namespace(librenderscope):
    locations = {("Service", "podiumd", "foo"): 3, ("Service", "other-ns", "foo"): 9}
    assert librenderscope.resource_line(locations, "Service", "foo", namespace="podiumd") == 3
    assert librenderscope.resource_line(locations, "Service", "foo", namespace="other-ns") == 9


def test_resource_line_falls_back_to_kind_name_when_unique(librenderscope):
    locations = {("Service", "", "foo"): 3}
    assert librenderscope.resource_line(locations, "Service", "foo") == 3


def test_resource_line_none_when_ambiguous_across_namespaces(librenderscope):
    """Without a namespace to disambiguate (kubeconform's JSON has none),
    the same kind+name rendering into two different namespaces must not
    guess — a wrong line is worse than no hint at all."""
    locations = {("Service", "ns-a", "foo"): 3, ("Service", "ns-b", "foo"): 9}
    assert librenderscope.resource_line(locations, "Service", "foo") is None


def test_resource_line_none_when_not_found(librenderscope):
    locations = {("Service", "", "foo"): 3}
    assert librenderscope.resource_line(locations, "ConfigMap", "bar") is None


# --- render_chart ---
# render_chart lives in lib.render_scope and calls its OWN `run` binding —
# same reason every other librenderscope test above uses librenderscope,
# not vp, as the monkeypatch target.

def _sequenced_run(rendered, returncode=0, stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr=stderr)
    return _run


def test_render_chart_returns_helm_templates_result(librenderscope, tmp_path, monkeypatch):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n"
    monkeypatch.setattr(librenderscope, "run", _sequenced_run(rendered))
    result = librenderscope.render_chart(tmp_path, [])
    assert result.returncode == 0
    assert result.stdout == rendered


def test_render_chart_passes_extra_args_through(librenderscope, tmp_path, monkeypatch):
    captured = {}

    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(librenderscope, "run", _run)
    librenderscope.render_chart(tmp_path, ["-f", "values.yaml"])
    assert "-f" in captured["cmd"] and "values.yaml" in captured["cmd"]


def test_render_chart_propagates_failure(librenderscope, tmp_path, monkeypatch):
    monkeypatch.setattr(librenderscope, "run", _sequenced_run("", returncode=1, stderr="Error: broke"))
    result = librenderscope.render_chart(tmp_path, [])
    assert result.returncode == 1
    assert "broke" in result.stderr


# --- lint_args_for (moved from verify-podiumd.py — see also
# tests/verify-podiumd/test_misc.py, which covers the vp.lint_args_for
# re-export used by main()) ---

def test_lint_args_for_lives_in_render_scope(librenderscope, tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint-values.yaml").write_text("foo: bar\n")
    assert librenderscope.lint_args_for(tmp_path) == ["-f", str(tmp_path / "ci" / "lint-values.yaml")]
