"""Orchestration helpers (die, require_helm, lint_args_for, print_summary, ...) and main() step selection."""

from pathlib import Path
from types import ModuleType

import pytest


def test_die_exits_nonzero_and_prints_to_stderr(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        vp.die("something broke")
    assert exc_info.value.code == 1
    assert "FAIL: something broke" in capsys.readouterr().err


def test_require_helm_passes_when_helm_present(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm")
    vp.require_helm()  # must not raise


def test_require_helm_dies_when_helm_missing(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        vp.require_helm()


def test_resolve_chart_dir_returns_dir_with_chart_yaml(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n")
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    assert vp.resolve_chart_dir() == tmp_path.resolve()


def test_resolve_chart_dir_dies_without_chart_yaml(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    with pytest.raises(SystemExit):
        vp.resolve_chart_dir()


def test_lint_args_for_uses_ci_values_when_present(vp: ModuleType, tmp_path: Path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint-values.yaml").write_text("foo: bar\n")
    args = vp.lint_args_for(tmp_path)
    assert args == ["-f", str(tmp_path / "ci" / "lint-values.yaml")]


def test_lint_args_for_falls_back_without_ci_values(vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    args = vp.lint_args_for(tmp_path)
    assert args == []
    assert "WARNING" in capsys.readouterr().out


def test_print_summary_all_pass(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    results = [("Lint", True, "0 errors"), ("Render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "PASS" in out
    assert "All checks passed." in out


def test_print_summary_reports_failure(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    results = [("Lint", False, "1 error")]
    vp.print_summary(results, overall_ok=False)
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "One or more checks failed" in out


def test_print_summary_reports_skip(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    """ok=None (skipped via --skip=) renders as SKIP and is not a failure."""
    results = [("Lint", None, "skipped"), ("Full render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "SKIP" in out
    assert "All checks passed." in out


# --- SKIPPABLE_STEPS ---


def test_skippable_steps_names_match_main_run_steps(vp: ModuleType):
    """Every SKIPPABLE_STEPS name must be a step _run_all_steps runs; a typo makes --skip= a no-op."""
    import inspect
    import re

    source = inspect.getsource(vp._run_all_steps)
    for _, step_name in vp.SKIPPABLE_STEPS:
        assert re.search(rf'runner\.run\(\s*"{re.escape(step_name)}"', source), (
            f'no runner.run("{step_name}", ...) call found in _run_all_steps()'
        )


def test_skippable_steps_order_matches_main_run_order(vp: ModuleType):
    """SKIPPABLE_STEPS must be in run order, since it drives the --help listing."""
    import inspect
    import re

    source = inspect.getsource(vp._run_all_steps)
    positions = []
    for _, step_name in vp.SKIPPABLE_STEPS:
        m = re.search(rf'runner\.run\(\s*"{re.escape(step_name)}"', source)
        assert m is not None, f"{step_name!r} is not run in _run_all_steps"
        positions.append(m.start())
    assert positions == sorted(positions)


def test_skippable_steps_flags_are_unique_and_kebab_case(vp: ModuleType):
    flags = [flag for flag, _ in vp.SKIPPABLE_STEPS]
    assert len(flags) == len(set(flags))
    for flag in flags:
        assert flag == flag.lower()
        assert " " not in flag


def test_steps_help_lists_every_step_flag_and_title(vp: ModuleType):
    """--help lists the step names --skip=/--include= accept."""
    for flag, step_name in vp.SKIPPABLE_STEPS:
        assert flag in vp.STEPS_HELP
        assert step_name in vp.STEPS_HELP


def test_steps_help_is_in_argparse_epilog(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Steps usable with --skip=/--include=" in out
    assert "kube-score" in out


# --- main(): --skip= end-to-end ---


def test_main_skips_requested_steps_and_runs_the_rest(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """--skip=helm-lint,full-render skips exactly those steps; the rest run and exit is 0."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--skip=helm-lint,full-render"])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: Path("/fake/chart/dir"))
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda chart_dir: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])

    ran = []

    def make_check(name):
        def check(*args, **kwargs):
            ran.append(name)
            return True, "ok"

        return check

    monkeypatch.setattr(vp, "check_utf8_format", make_check("utf8"))
    monkeypatch.setattr(vp, "check_dependencies", make_check("deps"))
    monkeypatch.setattr(vp, "check_repo_access", make_check("repo-access"))
    monkeypatch.setattr(vp, "check_duplicate_keys", make_check("dupe"))
    monkeypatch.setattr(vp, "check_dry", make_check("dry"))
    monkeypatch.setattr(vp, "check_image_references", make_check("image-refs"))
    monkeypatch.setattr(vp, "check_node_selector", make_check("node-selector"))
    monkeypatch.setattr(vp, "check_oidc_url_coverage", make_check("oidc-url-coverage"))
    monkeypatch.setattr(vp, "check_digest_pinning", make_check("digest-pinning"))
    monkeypatch.setattr(vp, "check_subchart_image_visibility", make_check("subchart-images"))
    monkeypatch.setattr(vp, "check_shared_image_usage", make_check("shared-image-usage"))
    monkeypatch.setattr(vp, "check_image_repository", make_check("image-repository"))
    monkeypatch.setattr(vp, "check_image_digests", make_check("digests"))
    monkeypatch.setattr(vp, "check_docs_consistency", make_check("docs"))
    monkeypatch.setattr(vp, "check_helm_docs", make_check("helm-docs"))
    monkeypatch.setattr(vp, "check_markdown", make_check("markdown"))
    monkeypatch.setattr(vp, "check_vendored_tgz_extraction", make_check("tgz"))
    monkeypatch.setattr(vp, "check_release_baseline", make_check("release-baseline"))
    monkeypatch.setattr(vp, "check_lockstep_versions", make_check("lockstep"))
    monkeypatch.setattr(vp, "check_yamllint", make_check("yamllint"))
    monkeypatch.setattr(vp, "check_kubeconform", make_check("kubeconform"))
    monkeypatch.setattr(vp, "check_shellcheck", make_check("shellcheck"))
    monkeypatch.setattr(vp, "check_kube_score", make_check("kube-score"))
    monkeypatch.setattr(vp, "check_release_secret_size", make_check("release-secret-size"))
    monkeypatch.setattr(vp, "check_chart_upgrades", make_check("chart-upgrades"))
    monkeypatch.setattr(vp, "check_root_containers", make_check("root-containers"))
    monkeypatch.setattr(vp, "check_image_upgrades", make_check("image-upgrades"))
    monkeypatch.setattr(vp, "check_cves", make_check("cves"))
    monkeypatch.setattr(vp, "check_cve_diff", make_check("cve-diff"))

    def fail_if_called(*args):
        msg = "this check should have been skipped"
        raise AssertionError(msg)

    monkeypatch.setattr(vp, "check_lint", fail_if_called)
    monkeypatch.setattr(vp, "check_render", fail_if_called)

    vp.main()  # must not raise / must not sys.exit

    assert ran == [
        "utf8",
        "dupe",
        "dry",
        "image-refs",
        "node-selector",
        "oidc-url-coverage",
        "digest-pinning",
        "tgz",
        "release-baseline",
        "lockstep",
        "helm-docs",
        "markdown",
        "repo-access",
        "deps",
        "docs",
        "subchart-images",
        "shared-image-usage",
        "image-repository",
        "digests",
        "yamllint",
        "kubeconform",
        "shellcheck",
        "kube-score",
        "release-secret-size",
        "chart-upgrades",
        "root-containers",
        "image-upgrades",
        "cves",
        "cve-diff",
    ]
    out = capsys.readouterr().out
    assert "Helm lint" in out and "SKIP" in out
    assert "Full render" in out and "SKIP" in out
    assert "All checks passed." in out


def test_main_skipped_step_does_not_count_as_failure(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """A failed step makes the run exit non-zero even if later steps pass."""
    monkeypatch.setattr(
        vp.sys, "argv", ["verify-podiumd", "--skip=dependencies,image-digests,doc-consistency,helm-lint,full-render"]
    )
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: Path("/fake/chart/dir"))
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda chart_dir: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(vp, "check_utf8_format", lambda *a: (False, "BOM found"))

    def ok(*args, **kwargs):
        return True, "ok"

    for name in (
        "check_repo_access",
        "check_duplicate_keys",
        "check_dry",
        "check_image_references",
        "check_node_selector",
        "check_oidc_url_coverage",
        "check_digest_pinning",
        "check_vendored_tgz_extraction",
        "check_release_baseline",
        "check_lockstep_versions",
        "check_helm_docs",
        "check_markdown",
        "check_subchart_image_visibility",
        "check_shared_image_usage",
        "check_image_repository",
        "check_yamllint",
        "check_kubeconform",
        "check_shellcheck",
        "check_kube_score",
        "check_release_secret_size",
        "check_chart_upgrades",
        "check_root_containers",
        "check_image_upgrades",
        "check_cves",
        "check_cve_diff",
    ):
        monkeypatch.setattr(vp, name, ok)

    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 1


def test_main_continues_past_a_failed_step(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A failing step doesn't abort the run; every step not blocked via STEP_PREREQUISITES still runs."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd"])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: Path("/fake/chart/dir"))
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda chart_dir: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])

    ran = []

    def make_check(name, result=(True, "ok")):
        def check(*args, **kwargs):
            ran.append(name)
            return result

        return check

    monkeypatch.setattr(vp, "check_utf8_format", make_check("utf8", (False, "BOM found")))
    monkeypatch.setattr(vp, "check_dependencies", make_check("deps"))
    monkeypatch.setattr(vp, "check_repo_access", make_check("repo-access"))
    monkeypatch.setattr(vp, "check_duplicate_keys", make_check("dupe"))
    monkeypatch.setattr(vp, "check_dry", make_check("dry"))
    monkeypatch.setattr(vp, "check_image_references", make_check("image-refs"))
    monkeypatch.setattr(vp, "check_node_selector", make_check("node-selector"))
    monkeypatch.setattr(vp, "check_oidc_url_coverage", make_check("oidc-url-coverage"))
    monkeypatch.setattr(vp, "check_digest_pinning", make_check("digest-pinning"))
    monkeypatch.setattr(vp, "check_subchart_image_visibility", make_check("subchart-images"))
    monkeypatch.setattr(vp, "check_shared_image_usage", make_check("shared-image-usage"))
    monkeypatch.setattr(vp, "check_image_repository", make_check("image-repository"))
    monkeypatch.setattr(vp, "check_image_digests", make_check("digests"))
    monkeypatch.setattr(vp, "check_docs_consistency", make_check("docs"))
    monkeypatch.setattr(vp, "check_helm_docs", make_check("helm-docs"))
    monkeypatch.setattr(vp, "check_markdown", make_check("markdown"))
    monkeypatch.setattr(vp, "check_vendored_tgz_extraction", make_check("tgz"))
    monkeypatch.setattr(vp, "check_release_baseline", make_check("release-baseline"))
    monkeypatch.setattr(vp, "check_lockstep_versions", make_check("lockstep"))
    monkeypatch.setattr(vp, "check_lint", make_check("helm-lint"))
    monkeypatch.setattr(vp, "check_render", make_check("full-render"))
    monkeypatch.setattr(vp, "check_yamllint", make_check("yamllint"))
    monkeypatch.setattr(vp, "check_kubeconform", make_check("kubeconform"))
    monkeypatch.setattr(vp, "check_shellcheck", make_check("shellcheck"))
    monkeypatch.setattr(vp, "check_kube_score", make_check("kube-score"))
    monkeypatch.setattr(vp, "check_release_secret_size", make_check("release-secret-size"))
    monkeypatch.setattr(vp, "check_chart_upgrades", make_check("chart-upgrades"))
    monkeypatch.setattr(vp, "check_root_containers", make_check("root-containers"))
    monkeypatch.setattr(vp, "check_image_upgrades", make_check("image-upgrades"))
    monkeypatch.setattr(vp, "check_cves", make_check("cves"))
    monkeypatch.setattr(vp, "check_cve_diff", make_check("cve-diff"))

    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 1

    # None of these depend on "UTF-8 format" via STEP_PREREQUISITES.
    assert ran == [
        "utf8",
        "dupe",
        "dry",
        "image-refs",
        "node-selector",
        "oidc-url-coverage",
        "digest-pinning",
        "tgz",
        "release-baseline",
        "lockstep",
        "helm-docs",
        "markdown",
        "repo-access",
        "deps",
        "docs",
        "subchart-images",
        "shared-image-usage",
        "image-repository",
        "digests",
        "helm-lint",
        "full-render",
        "yamllint",
        "kubeconform",
        "shellcheck",
        "kube-score",
        "release-secret-size",
        "chart-upgrades",
        "root-containers",
        "image-upgrades",
        "cves",
        "cve-diff",
    ]
    out = capsys.readouterr().out
    assert "UTF-8 format" in out and "FAIL" in out
    assert "One or more checks failed" in out


def test_main_skips_dependents_of_a_failed_prerequisite(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A failed "Dependencies" skips its dependents (avoids noisy follow-on failures); others still run."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd"])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: Path("/fake/chart/dir"))
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda chart_dir: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])

    def ok(*args, **kwargs):
        return True, "ok"

    for name in (
        "check_utf8_format",
        "check_duplicate_keys",
        "check_dry",
        "check_image_references",
        "check_node_selector",
        "check_oidc_url_coverage",
        "check_digest_pinning",
        "check_vendored_tgz_extraction",
        "check_release_baseline",
        "check_lockstep_versions",
        "check_helm_docs",
        "check_markdown",
        "check_repo_access",
        "check_chart_upgrades",
    ):
        monkeypatch.setattr(vp, name, ok)

    def fail_if_called(*args):
        msg = "this check should have been skipped as a prerequisite's dependent"
        raise AssertionError(msg)

    monkeypatch.setattr(vp, "check_dependencies", lambda *a: (False, "helm dependency update failed"))
    for name in (
        "check_docs_consistency",
        "check_subchart_image_visibility",
        "check_shared_image_usage",
        "check_image_repository",
        "check_image_digests",
        "check_lint",
        "check_render",
        "check_yamllint",
        "check_kubeconform",
        "check_shellcheck",
        "check_kube_score",
        "check_release_secret_size",
        "check_root_containers",
        "check_image_upgrades",
        "check_cves",
        "check_cve_diff",
    ):
        monkeypatch.setattr(vp, name, fail_if_called)

    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Dependencies" in out and "FAIL" in out
    assert 'prerequisite "Dependencies" failed' in out


# --- prerequisites_for ---


def test_prerequisites_for_render_based_check_needs_dependencies(vp: ModuleType):
    assert vp.prerequisites_for("kube-score") == {"Dependencies", "Repo access"}
    assert vp.prerequisites_for("Helm lint") == {"Dependencies", "Repo access"}
    assert vp.prerequisites_for("Release secret size") == {"Dependencies", "Repo access"}


def test_prerequisites_for_image_digests_needs_dependencies(vp: ModuleType):
    """charts/*.tgz is gitignored; the subchart-default repository fallback needs it populated."""
    assert vp.prerequisites_for("Image digests") == {"Dependencies", "Repo access"}


def test_prerequisites_for_doc_consistency_needs_dependencies(vp: ModuleType):
    """Images set only in vendored subchart values (e.g. zac's gotenberg) need the .tgz populated."""
    assert vp.prerequisites_for("Doc consistency") == {"Dependencies", "Repo access"}


def test_prerequisites_for_cve_scan_needs_image_upgrades_too(vp: ModuleType):
    """CVE scan reads the Image upgrades cache for "upgradable to X"."""
    assert vp.prerequisites_for("CVE scan") == {"Dependencies", "Image upgrades", "Repo access"}


def test_prerequisites_for_dependencies_needs_repo_access(vp: ModuleType):
    """Not a data dependency: gives a bare --include=dependencies the repo-access fast fail."""
    assert vp.prerequisites_for("Dependencies") == {"Repo access"}


def test_prerequisites_for_standalone_check_has_none(vp: ModuleType):
    assert vp.prerequisites_for("Image references") == set()
    assert vp.prerequisites_for("Repo access") == set()
    assert vp.prerequisites_for("Helm doc") == set()


# --- main(): --include= end-to-end ---


def _stub_all_checks(vp: ModuleType, monkeypatch: pytest.MonkeyPatch, ran):
    """Stub every step check for the --include= tests."""

    def make_check(name):
        def check(*args, **kwargs):
            ran.append(name)
            return True, "ok"

        return check

    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: Path("/fake/chart/dir"))
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda chart_dir: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(vp, "check_utf8_format", make_check("utf8"))
    monkeypatch.setattr(vp, "check_dependencies", make_check("deps"))
    monkeypatch.setattr(vp, "check_repo_access", make_check("repo-access"))
    monkeypatch.setattr(vp, "check_duplicate_keys", make_check("dupe"))
    monkeypatch.setattr(vp, "check_dry", make_check("dry"))
    monkeypatch.setattr(vp, "check_image_references", make_check("image-refs"))
    monkeypatch.setattr(vp, "check_node_selector", make_check("node-selector"))
    monkeypatch.setattr(vp, "check_oidc_url_coverage", make_check("oidc-url-coverage"))
    monkeypatch.setattr(vp, "check_digest_pinning", make_check("digest-pinning"))
    monkeypatch.setattr(vp, "check_subchart_image_visibility", make_check("subchart-images"))
    monkeypatch.setattr(vp, "check_shared_image_usage", make_check("shared-image-usage"))
    monkeypatch.setattr(vp, "check_image_digests", make_check("digests"))
    monkeypatch.setattr(vp, "check_docs_consistency", make_check("docs"))
    monkeypatch.setattr(vp, "check_helm_docs", make_check("helm-docs"))
    monkeypatch.setattr(vp, "check_markdown", make_check("markdown"))
    monkeypatch.setattr(vp, "check_vendored_tgz_extraction", make_check("tgz"))
    monkeypatch.setattr(vp, "check_release_baseline", make_check("release-baseline"))
    monkeypatch.setattr(vp, "check_lockstep_versions", make_check("lockstep"))
    monkeypatch.setattr(vp, "check_lint", make_check("lint"))
    monkeypatch.setattr(vp, "check_render", make_check("render"))
    monkeypatch.setattr(vp, "check_yamllint", make_check("yamllint"))
    monkeypatch.setattr(vp, "check_kubeconform", make_check("kubeconform"))
    monkeypatch.setattr(vp, "check_shellcheck", make_check("shellcheck"))
    monkeypatch.setattr(vp, "check_kube_score", make_check("kube-score"))
    monkeypatch.setattr(vp, "check_release_secret_size", make_check("release-secret-size"))
    monkeypatch.setattr(vp, "check_chart_upgrades", make_check("chart-upgrades"))
    monkeypatch.setattr(vp, "check_root_containers", make_check("root-containers"))
    monkeypatch.setattr(vp, "check_image_upgrades", make_check("image-upgrades"))
    monkeypatch.setattr(vp, "check_cves", make_check("cves"))
    monkeypatch.setattr(vp, "check_cve_diff", make_check("cve-diff"))


def test_include_flag_runs_target_plus_its_prerequisite(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """--include=kube-score also runs "Dependencies" (its helm template needs sub-charts), nothing else."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=kube-score"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()  # must not raise / must not sys.exit

    assert ran == ["repo-access", "deps", "kube-score"]
    out = capsys.readouterr().out
    for skipped in ("UTF-8 format", "Dupe check", "DRY check", "Helm lint", "Full render", "yamllint"):
        assert skipped in out
    assert "not included via --include=kube-score" in out
    assert "All checks passed." in out


def test_include_flag_image_digests_runs_target_plus_dependencies(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """--include=image-digests runs "Dependencies" first so the subchart fallback sees fresh charts/."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=image-digests"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["repo-access", "deps", "digests"]


def test_include_flag_standalone_step_runs_without_dependencies(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A step without prerequisites runs alone: no "Dependencies" for --include=image-references."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=image-references"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["image-refs"]
    out = capsys.readouterr().out
    assert "Dependencies" in out and "SKIP" in out


def test_include_and_skip_together_errors(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=helm-lint", "--skip=full-render"])
    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_multiple_include_flags_run_the_union_plus_each_ones_prerequisites(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Multiple --include= steps combine with deduplicated prerequisites; everything else is SKIP."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=kube-score,shellcheck"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["repo-access", "deps", "shellcheck", "kube-score"]
    out = capsys.readouterr().out
    for skipped in ("UTF-8 format", "Helm lint", "Full render", "yamllint", "CVE scan"):
        assert skipped in out
    assert "All checks passed." in out


def test_multiple_include_flags_each_standalone_step_included_independently(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """Two prerequisite-free --include= steps both run, pulling in nothing else."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=image-references,node-selector"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["image-refs", "node-selector"]


# --- CVE scan selection via --skip=/--include= ---


def test_check_cves_no_longer_has_its_own_flag(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """--check-cves is not an option; CVE scan is selected via --skip=/--include=."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--check-cves"])
    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_cve_scan_runs_by_default(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """CVE scan runs by default."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "cves" in ran


def test_skip_cve_scan_skips_it(vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--skip=cve-scan"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "cves" not in ran
    out = capsys.readouterr().out
    assert "CVE scan" in out and "SKIP" in out


def test_include_cve_scan_runs_it_plus_dependencies_and_image_upgrades(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """--include=cve-scan also runs "Image upgrades", whose cache it reads."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=cve-scan"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["repo-access", "deps", "image-upgrades", "cves"]


def test_skip_cve_diff_skips_it(vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--skip=cve-diff"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "cve-diff" not in ran
    out = capsys.readouterr().out
    assert "CVE diff" in out and "SKIP" in out


def test_include_cve_diff_runs_it_plus_its_prerequisites(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """--include=cve-diff pulls in Dependencies, Image upgrades and Image digests, in pipeline order."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=cve-diff"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["repo-access", "deps", "digests", "image-upgrades", "cve-diff"]


def test_skip_image_upgrades_skips_it(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--skip=image-upgrades"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "image-upgrades" not in ran
    out = capsys.readouterr().out
    assert "Image upgrades" in out and "SKIP" in out


def test_include_image_upgrades_runs_it_plus_dependencies(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=image-upgrades"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["repo-access", "deps", "image-upgrades"]


def test_skip_release_secret_size_skips_it(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--skip=release-secret-size"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "release-secret-size" not in ran
    out = capsys.readouterr().out
    assert "Release secret size" in out and "SKIP" in out


def test_include_release_secret_size_runs_it_plus_dependencies(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Its render and `helm package` need "Dependencies" to populate charts/*.tgz."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=release-secret-size"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["repo-access", "deps", "release-secret-size"]


def test_skip_helm_doc_skips_it(vp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--skip=helm-doc"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "helm-docs" not in ran
    out = capsys.readouterr().out
    assert "Helm doc" in out and "SKIP" in out


def test_include_helm_doc_runs_standalone(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """No prerequisite: runs alone."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=helm-doc"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["helm-docs"]


def test_detail_flag_defaults_false_and_is_passed_to_check_cves(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=cve-scan"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)
    captured = {}

    def fake_check_cves(chart_dir, extra_args, *, detail=False):
        captured["detail"] = detail
        return True, "ok"

    monkeypatch.setattr(vp, "check_cves", fake_check_cves)

    vp.main()

    assert captured["detail"] is False


def test_detail_flag_true_is_passed_to_check_cves(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=cve-scan", "--detail-cve-check"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)
    captured = {}

    def fake_check_cves(chart_dir, extra_args, *, detail=False):
        captured["detail"] = detail
        return True, "ok"

    monkeypatch.setattr(vp, "check_cves", fake_check_cves)

    vp.main()

    assert captured["detail"] is True


def test_detail_cve_diff_flag_defaults_false_and_is_passed_to_check_cve_diff(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=cve-diff"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)
    captured = {}

    def fake_check_cve_diff(chart_dir, extra_args, *, detail=False):
        captured["detail"] = detail
        return True, "ok"

    monkeypatch.setattr(vp, "check_cve_diff", fake_check_cve_diff)

    vp.main()

    assert captured["detail"] is False


def test_detail_cve_diff_flag_true_is_passed_to_check_cve_diff(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd", "--include=cve-diff", "--detail-cve-diff"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)
    captured = {}

    def fake_check_cve_diff(chart_dir, extra_args, *, detail=False):
        captured["detail"] = detail
        return True, "ok"

    monkeypatch.setattr(vp, "check_cve_diff", fake_check_cve_diff)

    vp.main()

    assert captured["detail"] is True


# --- --skip=dependencies stale-vendored-state guard ---


def test_guard_not_called_when_dependencies_step_runs(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """The "Dependencies" step repairs a stale charts/ itself — no guard."""
    calls = []
    monkeypatch.setattr(vp, "ensure_vendored_dependencies", calls.append)
    vp._ensure_vendored_dependencies_if_skipped(Path("/chart"), set())
    assert not calls


def test_guard_called_when_dependencies_skipped_but_a_dependent_step_runs(
    vp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    calls = []
    monkeypatch.setattr(vp, "ensure_vendored_dependencies", calls.append)
    vp._ensure_vendored_dependencies_if_skipped(Path("/chart"), {"Dependencies"})
    assert calls == [Path("/chart")]


def test_guard_not_called_when_every_dependent_step_is_skipped_too(vp: ModuleType, monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(vp, "ensure_vendored_dependencies", calls.append)
    dependents = {name for _, name in vp.SKIPPABLE_STEPS if "Dependencies" in vp.prerequisites_for(name)}
    vp._ensure_vendored_dependencies_if_skipped(Path("/chart"), {"Dependencies", *dependents})
    assert not calls
