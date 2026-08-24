"""die, require_helm, resolve_chart_dir, lint_args_for, print_summary — the
small orchestration helpers not covered elsewhere."""
import pytest


def test_die_exits_nonzero_and_prints_to_stderr(vp, capsys):
    with pytest.raises(SystemExit) as exc_info:
        vp.die("something broke")
    assert exc_info.value.code == 1
    assert "FAIL: something broke" in capsys.readouterr().err


def test_require_helm_passes_when_helm_present(vp, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm")
    vp.require_helm()  # must not raise


def test_require_helm_dies_when_helm_missing(vp, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        vp.require_helm()


def test_resolve_chart_dir_returns_dir_with_chart_yaml(vp, tmp_path, monkeypatch):
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n")
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    assert vp.resolve_chart_dir() == tmp_path.resolve()


def test_resolve_chart_dir_dies_without_chart_yaml(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    with pytest.raises(SystemExit):
        vp.resolve_chart_dir()


def test_lint_args_for_uses_ci_values_when_present(vp, tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint-values.yaml").write_text("foo: bar\n")
    args = vp.lint_args_for(tmp_path)
    assert args == ["-f", str(tmp_path / "ci" / "lint-values.yaml")]


def test_lint_args_for_falls_back_without_ci_values(vp, tmp_path, capsys):
    args = vp.lint_args_for(tmp_path)
    assert args == []
    assert "WARNING" in capsys.readouterr().out


def test_print_summary_all_pass(vp, capsys):
    results = [("Lint", True, "0 errors"), ("Render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "PASS" in out
    assert "All checks passed." in out


def test_print_summary_reports_failure(vp, capsys):
    results = [("Lint", False, "1 error")]
    vp.print_summary(results, overall_ok=False)
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "One or more checks failed" in out


def test_print_summary_reports_skip(vp, capsys):
    """A step recorded with ok=None (skipped via --skip=) renders as
    SKIP, not PASS or FAIL, and does not read as a failure."""
    results = [("Lint", None, "skipped"), ("Full render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "SKIP" in out
    assert "All checks passed." in out


# --- SKIPPABLE_STEPS ---

def test_skippable_steps_names_match_main_run_steps(vp):
    """Every (flag, step name) pair in SKIPPABLE_STEPS must name a step that
    main() actually runs — a typo here would silently make a --skip= entry
    do nothing."""
    import inspect
    source = inspect.getsource(vp.main)
    for _, step_name in vp.SKIPPABLE_STEPS:
        assert f'run_step("{step_name}"' in source, \
            f'no run_step("{step_name}", ...) call found in main()'


def test_skippable_steps_order_matches_main_run_order(vp):
    """SKIPPABLE_STEPS documents itself as being "in the order they run"
    (drives --help's listing) — a step listed out of its actual position
    silently misdocuments --help without failing the membership check
    above (this caught "Dependencies" having drifted to position 2 in the
    list while actually running much later, right before "Image
    digests")."""
    import inspect
    source = inspect.getsource(vp.main)
    positions = [source.index(f'run_step("{step_name}"') for _, step_name in vp.SKIPPABLE_STEPS]
    assert positions == sorted(positions)


def test_skippable_steps_flags_are_unique_and_kebab_case(vp):
    flags = [flag for flag, _ in vp.SKIPPABLE_STEPS]
    assert len(flags) == len(set(flags))
    for flag in flags:
        assert flag == flag.lower()
        assert " " not in flag


def test_steps_help_lists_every_step_flag_and_title(vp):
    """--help must actually tell you which step names --skip=/--include=
    accept — a prior version buried that list only inside the (wrapped,
    easy-to-miss) --skip/--include option help text."""
    for flag, step_name in vp.SKIPPABLE_STEPS:
        assert flag in vp.STEPS_HELP
        assert step_name in vp.STEPS_HELP


def test_steps_help_is_in_argparse_epilog(vp, monkeypatch, capsys):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Steps usable with --skip=/--include=" in out
    assert "kube-score" in out


# --- main(): --skip= end-to-end ---

def test_main_skips_requested_steps_and_runs_the_rest(vp, monkeypatch, capsys):
    """--skip=helm-lint,full-render must skip exactly those two steps
    (never calling their check functions) while every other step still runs
    normally, and the run still exits 0."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--skip=helm-lint,full-render"])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: "/fake/chart/dir")
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])

    ran = []

    def make_check(name):
        def check(*args):
            ran.append(name)
            return True, "ok"
        return check

    monkeypatch.setattr(vp, "check_utf8_format", make_check("utf8"))
    monkeypatch.setattr(vp, "check_dependencies", make_check("deps"))
    monkeypatch.setattr(vp, "check_duplicate_keys", make_check("dupe"))
    monkeypatch.setattr(vp, "check_dry", make_check("dry"))
    monkeypatch.setattr(vp, "check_image_references", make_check("image-refs"))
    monkeypatch.setattr(vp, "check_node_selector", make_check("node-selector"))
    monkeypatch.setattr(vp, "check_image_digests", make_check("digests"))
    monkeypatch.setattr(vp, "check_docs_consistency", make_check("docs"))
    monkeypatch.setattr(vp, "check_helm_docs", make_check("helm-docs"))
    monkeypatch.setattr(vp, "check_vendored_tgz_extraction", make_check("tgz"))
    monkeypatch.setattr(vp, "check_yamllint", make_check("yamllint"))
    monkeypatch.setattr(vp, "check_kubeconform", make_check("kubeconform"))
    monkeypatch.setattr(vp, "check_shellcheck", make_check("shellcheck"))
    monkeypatch.setattr(vp, "check_kube_score", make_check("kube-score"))
    monkeypatch.setattr(vp, "check_image_upgrades", make_check("image-upgrades"))
    monkeypatch.setattr(vp, "check_cves", make_check("cves"))

    def fail_if_called(*args):
        raise AssertionError("this check should have been skipped")

    monkeypatch.setattr(vp, "check_lint", fail_if_called)
    monkeypatch.setattr(vp, "check_render", fail_if_called)

    vp.main()  # must not raise / must not sys.exit

    assert ran == ["utf8", "dupe", "dry", "image-refs", "node-selector", "tgz", "docs", "helm-docs",
                    "deps", "digests", "yamllint", "kubeconform", "shellcheck", "kube-score", "image-upgrades", "cves"]
    out = capsys.readouterr().out
    assert "Helm lint" in out and "SKIP" in out
    assert "Full render" in out and "SKIP" in out
    assert "All checks passed." in out


def test_main_skipped_step_does_not_count_as_failure(vp, monkeypatch):
    """Skipping every step except one that fails must still exit non-zero —
    a skip must never mask a real failure in a step that DID run."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--skip=dependencies,image-digests,docs-consistency,helm-lint,full-render"])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: "/fake/chart/dir")
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda: (True, "ok"))
    monkeypatch.setattr(vp, "check_utf8_format", lambda *a: (False, "BOM found"))

    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 1


# --- prerequisites_for ---

def test_prerequisites_for_render_based_check_needs_dependencies(vp):
    assert vp.prerequisites_for("kube-score") == {"Dependencies"}
    assert vp.prerequisites_for("Helm lint") == {"Dependencies"}


def test_prerequisites_for_image_digests_needs_dependencies(vp):
    """charts/*.tgz is gitignored — on a fresh checkout it doesn't exist at
    all until "Dependencies" has populated it, which the subchart-default
    repository fallback (lib.chart.subchart_default_repository) reads
    from directly."""
    assert vp.prerequisites_for("Image digests") == {"Dependencies"}


def test_prerequisites_for_cve_scan_needs_image_upgrades_too(vp):
    """CVE scan reads Image upgrades' own cache to mark a finding
    "upgradable to X" — a bare --include=check-cves must still populate
    that cache fresh, not just a full run."""
    assert vp.prerequisites_for("CVE scan") == {"Dependencies", "Image upgrades"}


def test_prerequisites_for_standalone_check_has_none(vp):
    assert vp.prerequisites_for("Image references") == set()
    assert vp.prerequisites_for("Dependencies") == set()
    assert vp.prerequisites_for("Helm docs check") == set()


# --- main(): --include= end-to-end ---

def _stub_all_checks(vp, monkeypatch, ran):
    """Same stub set test_main_skips_requested_steps_and_runs_the_rest uses
    — shared here so --include= tests don't have to repeat it."""
    def make_check(name):
        def check(*args):
            ran.append(name)
            return True, "ok"
        return check

    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: "/fake/chart/dir")
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda: (True, "ok"))
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(vp, "check_utf8_format", make_check("utf8"))
    monkeypatch.setattr(vp, "check_dependencies", make_check("deps"))
    monkeypatch.setattr(vp, "check_duplicate_keys", make_check("dupe"))
    monkeypatch.setattr(vp, "check_dry", make_check("dry"))
    monkeypatch.setattr(vp, "check_image_references", make_check("image-refs"))
    monkeypatch.setattr(vp, "check_node_selector", make_check("node-selector"))
    monkeypatch.setattr(vp, "check_image_digests", make_check("digests"))
    monkeypatch.setattr(vp, "check_docs_consistency", make_check("docs"))
    monkeypatch.setattr(vp, "check_helm_docs", make_check("helm-docs"))
    monkeypatch.setattr(vp, "check_vendored_tgz_extraction", make_check("tgz"))
    monkeypatch.setattr(vp, "check_lint", make_check("lint"))
    monkeypatch.setattr(vp, "check_render", make_check("render"))
    monkeypatch.setattr(vp, "check_yamllint", make_check("yamllint"))
    monkeypatch.setattr(vp, "check_kubeconform", make_check("kubeconform"))
    monkeypatch.setattr(vp, "check_shellcheck", make_check("shellcheck"))
    monkeypatch.setattr(vp, "check_kube_score", make_check("kube-score"))
    monkeypatch.setattr(vp, "check_image_upgrades", make_check("image-upgrades"))
    monkeypatch.setattr(vp, "check_cves", make_check("cves"))


def test_include_flag_runs_target_plus_its_prerequisite(vp, monkeypatch, capsys):
    """--include=kube-score must also run "Dependencies" (kube-score's own
    `helm template` call would otherwise fail on unresolved sub-charts) —
    but nothing else."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=kube-score"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()  # must not raise / must not sys.exit

    assert ran == ["deps", "kube-score"]
    out = capsys.readouterr().out
    for skipped in ("UTF-8 format", "Dupe check", "DRY check", "Helm lint", "Full render", "yamllint"):
        assert skipped in out
    assert "not included via --include=kube-score" in out
    assert "All checks passed." in out


def test_include_flag_image_digests_runs_target_plus_dependencies(vp, monkeypatch, capsys):
    """--include=image-digests must also run "Dependencies" first, so the
    subchart-default repository fallback sees a freshly-vendored charts/
    rather than whatever (if anything) happened to be on disk already."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=image-digests"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["deps", "digests"]


def test_include_flag_standalone_step_runs_without_dependencies(vp, monkeypatch, capsys):
    """A step with no prerequisite (see prerequisites_for) must run alone —
    --include=image-references must NOT also run "Dependencies"."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=image-references"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["image-refs"]
    out = capsys.readouterr().out
    assert "Dependencies" in out and "SKIP" in out


def test_include_and_skip_together_errors(vp, monkeypatch, capsys):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=helm-lint", "--skip=full-render"])
    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_multiple_include_flags_run_the_union_plus_each_ones_prerequisites(vp, monkeypatch, capsys):
    """Unlike the old one-flag-per-step --only-<step>, multiple steps in one --include= combine
    — each named step runs, plus whatever prerequisite(s) any of them need
    (deduplicated, so "Dependencies" only runs once for two render-based
    steps), and everything else still shows as SKIP."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=kube-score,shellcheck"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["deps", "shellcheck", "kube-score"]
    out = capsys.readouterr().out
    for skipped in ("UTF-8 format", "Helm lint", "Full render", "yamllint", "CVE scan"):
        assert skipped in out
    assert "All checks passed." in out


def test_multiple_include_flags_each_standalone_step_included_independently(vp, monkeypatch):
    """Two steps in one --include= with no prerequisite between them (neither
    needs "Dependencies") must both run, with no unrelated step pulled in."""
    monkeypatch.setattr(vp.sys, "argv",
                         ["verify-podiumd.py", "--include=image-references,node-selector"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["image-refs", "node-selector"]


# --- CVE scan joined the same --skip=/--include= family as every other step ---

def test_check_cves_no_longer_has_its_own_flag(vp, monkeypatch, capsys):
    """CVE scan used to be gated by a bespoke --check-cves opt-in flag,
    disconnected from --skip=/--include=. It's now just another entry in
    SKIPPABLE_STEPS (selectable via --skip=check-cves/--include=check-cves), so that
    separate flag must be gone — argparse rejects it as unrecognized."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--check-cves"])
    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_cve_scan_runs_by_default(vp, monkeypatch):
    """Unlike its old opt-in self, "CVE scan" now runs by default like every
    other step — no flag needed to make it run."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "cves" in ran


def test_skip_check_cves_skips_it(vp, monkeypatch, capsys):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--skip=check-cves"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "cves" not in ran
    out = capsys.readouterr().out
    assert "CVE scan" in out and "SKIP" in out


def test_include_check_cves_runs_it_plus_dependencies_and_image_upgrades(vp, monkeypatch):
    """CVE scan reads Image upgrades' own cache (see lib.cve_check), so a
    bare --include=check-cves must also run "Image upgrades" first —
    not just "Dependencies" — or that cache would never get populated."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=check-cves"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["deps", "image-upgrades", "cves"]


def test_skip_image_upgrades_skips_it(vp, monkeypatch, capsys):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--skip=image-upgrades"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "image-upgrades" not in ran
    out = capsys.readouterr().out
    assert "Image upgrades" in out and "SKIP" in out


def test_include_image_upgrades_runs_it_plus_dependencies(vp, monkeypatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=image-upgrades"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["deps", "image-upgrades"]


def test_skip_helm_docs_check_skips_it(vp, monkeypatch, capsys):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--skip=helm-docs-check"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert "helm-docs" not in ran
    out = capsys.readouterr().out
    assert "Helm docs check" in out and "SKIP" in out


def test_include_helm_docs_check_runs_standalone(vp, monkeypatch):
    """No prerequisite (doesn't need a render/Dependencies) — must run
    alone, unlike image-upgrades/CVE scan."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=helm-docs-check"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)

    vp.main()

    assert ran == ["helm-docs"]


def test_detail_flag_defaults_false_and_is_passed_to_check_cves(vp, monkeypatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=check-cves"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)
    captured = {}

    def fake_check_cves(*a):
        captured["args"] = a
        return True, "ok"

    monkeypatch.setattr(vp, "check_cves", fake_check_cves)

    vp.main()

    assert captured["args"][-1] is False


def test_detail_flag_true_is_passed_to_check_cves(vp, monkeypatch):
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--include=check-cves", "--detail-cve-check"])
    ran = []
    _stub_all_checks(vp, monkeypatch, ran)
    captured = {}

    def fake_check_cves(*a):
        captured["args"] = a
        return True, "ok"

    monkeypatch.setattr(vp, "check_cves", fake_check_cves)

    vp.main()

    assert captured["args"][-1] is True
