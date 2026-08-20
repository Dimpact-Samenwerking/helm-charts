#!/usr/bin/env python3
"""
Verifies the podiumd chart:
  1. values.yaml is valid UTF-8 with no BOM (a BOM breaks YAML tooling if present)
  2. all Chart.yaml dependencies actually resolve and bundle (helm dependency update)
  3. values.yaml has no duplicate keys silently overwriting earlier values
  4. the chart lints cleanly with the CI placeholder values
  5. the chart renders cleanly with `helm template` using the CI placeholder values

Stops at the first failing step and prints a PASS/FAIL summary table, mirroring
the /helm-precommit workflow (BOM check, dupe check, lint, full render) plus
this script's own dependency-resolution check.

Usage:
    verify-podiumd-chart.py                 # verify the local podiumd chart source checkout
                                             # (default: charts/podiumd next to this script) —
                                             # use this in the podiumd chart's own CI pipeline,
                                             # before packaging/publishing
    verify-podiumd-chart.py <chart-source>  # verify a different local chart source checkout

Env vars:
    CHART_NAME     name to pass to `helm template` (default: podiumd)
    CHART_VERSION  unused by the checks themselves, kept for parity with the shell version
    CHART_DIR      default chart source path, used when no positional arg is given

Exit code is non-zero if any check fails — safe to use as a CI gate.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CHART_DIR = SCRIPT_DIR.parent

# name -> repo URL, for every Chart.yaml dependency that uses a named/alias
# repository (not a plain https:// URL and not an oci:// registry — those
# don't need `helm repo add`).
REQUIRED_REPOS = {
    "adfinis": "https://charts.adfinis.com",
    "wiremind": "https://wiremind.github.io/wiremind-helm-charts",
    "dimpact": "https://Dimpact-Samenwerking.github.io/helm-charts/",
    "maykinmedia": "https://maykinmedia.github.io/charts/",
    "kiss-elastic": "https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic",
    "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
    "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
    "worth-nl": "https://worth-nl.github.io/helm-charts",
    "opstree": "https://ot-container-kit.github.io/helm-charts/",
}

TOP_N_TEMPLATES = 5


def log(title):
    print(f"\n=== {title} ===")


def die(message):
    """Hard-stop for setup/precondition failures that happen before any
    checklist step begins (not part of the PASS/FAIL summary)."""
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=False, **kwargs)


def require_helm():
    if shutil.which("helm") is None:
        die("helm is not installed")


def resolve_chart_dir(source_arg):
    chart_dir = Path(source_arg or os.environ.get("CHART_DIR", str(DEFAULT_CHART_DIR)))
    if not chart_dir.is_dir():
        die(f"{chart_dir} does not contain a Chart.yaml")
    chart_dir = chart_dir.resolve()
    if not (chart_dir / "Chart.yaml").is_file():
        die(f"{chart_dir} does not contain a Chart.yaml")
    return chart_dir


def check_utf8_format(chart_dir):
    values_path = chart_dir / "values.yaml"
    data = values_path.read_bytes()
    if data[:3] == b"\xef\xbb\xbf":
        values_path.write_bytes(data[3:])
        return False, "BOM found and stripped — re-stage this file before committing"
    print(f"OK: no BOM in {values_path.name}")
    return True, "no BOM"


def ensure_repos_configured():
    for name, url in REQUIRED_REPOS.items():
        result = run(["helm", "repo", "add", name, url, "--force-update"],
                      capture_output=True, text=True)
        if result.returncode != 0:
            die(f"helm repo add {name} failed\n{result.stderr.strip()}")
    result = run(["helm", "repo", "update"], capture_output=True, text=True)
    if result.returncode != 0:
        die(f"helm repo update failed\n{result.stderr.strip()}")


def check_dependencies(chart_dir):
    shutil.rmtree(chart_dir / "charts", ignore_errors=True)
    (chart_dir / "Chart.lock").unlink(missing_ok=True)
    result = run(["helm", "dependency", "update", str(chart_dir)])
    if result.returncode != 0:
        return False, "helm dependency update failed"

    result = run(["helm", "dependency", "list", str(chart_dir)], capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm dependency list failed: {result.stderr.strip()}"
    print(result.stdout, end="")

    rows = [line for line in result.stdout.splitlines()[1:] if line.strip()]
    bad_rows = [line for line in rows if line.split()[-1] != "ok"]
    if bad_rows:
        return False, "one or more dependencies did not resolve (STATUS != ok above)"

    dep_count = len(rows)
    chart_count = len(list((chart_dir / "charts").glob("*.tgz")))
    if dep_count != chart_count:
        return False, f"expected {dep_count} bundled dependencies, found {chart_count} in charts/"
    detail = f"{dep_count} dependencies bundled"
    print(f"OK: all {detail} in charts/")
    return True, detail


def check_duplicate_keys(chart_dir):
    """Scan values.yaml for duplicate keys that would silently overwrite an
    earlier value. Each YAML sequence item gets its own scope (tagged by the
    line its "-" appears on) so that unrelated list items sharing a key name
    (e.g. every item in a list having its own "value:" or "mountPath:") are
    never treated as duplicates of each other."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines(keepends=True)

    stack = []
    scope_keys = {}
    duplicates = []
    key_re = re.compile(r"^(\s*)([a-zA-Z0-9_\-][^:#\n]*?)\s*:")
    dash_re = re.compile(r"^(\s*)-\s*(.*)$")

    def register(scope_id, key, line_no):
        scope_keys.setdefault(scope_id, {})
        if key in scope_keys[scope_id]:
            parent = " > ".join(scope_id) if scope_id else "(root)"
            duplicates.append(
                f'Line {line_no}: duplicate "{key}" under [{parent}] (first line {scope_keys[scope_id][key]})'
            )
        else:
            scope_keys[scope_id][key] = line_no

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        if stripped.startswith("-"):
            dash_m = dash_re.match(line)
            list_indent = len(dash_m.group(1))
            rest = dash_m.group(2)
            while stack and stack[-1][0] >= list_indent:
                stack.pop()
            # unique per occurrence, so sibling list items never share a scope
            stack.append((list_indent, f"<item:{i}>"))

            km = key_re.match(rest)
            if km:
                key = km.group(2).strip()
                scope_id = tuple(k for _, k in stack)
                register(scope_id, key, i)
                stack.append((list_indent + 2, key))
            continue

        m = key_re.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        key = m.group(2).strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        scope_id = tuple(k for _, k in stack)
        register(scope_id, key, i)
        stack.append((indent, key))

    if duplicates:
        print(f"FOUND {len(duplicates)} duplicate(s):")
        for d in duplicates:
            print(" ", d)
        return False, f"{len(duplicates)} duplicate(s) found"
    print(f"OK: no duplicate keys in {values_path.name}")
    return True, "0 duplicates"


def lint_args_for(chart_dir):
    lint_values = chart_dir / "ci" / "lint-values.yaml"
    if lint_values.is_file():
        return ["-f", str(lint_values)]
    print("WARNING: no ci/lint-values.yaml found — linting with bare defaults only")
    return []


def check_lint(chart_dir, extra_args):
    result = run(["helm", "lint", str(chart_dir), *extra_args], capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output, end="" if output.endswith("\n") else "\n")

    error_count = len(re.findall(r"^\[ERROR\]", output, re.MULTILINE))
    warning_count = len(re.findall(r"^\[WARNING\]", output, re.MULTILINE))
    detail = f"{error_count} error(s), {warning_count} warning(s)"

    if result.returncode != 0 or error_count > 0:
        return False, detail
    return True, detail


def supports_skip_schema_validation():
    result = run(["helm", "template", "--help"], capture_output=True, text=True)
    return "--skip-schema-validation" in result.stdout


def report_largest_templates(rendered_text):
    source_re = re.compile(r"^# Source: (.+)$")
    counts = Counter()
    current = None
    for line in rendered_text.splitlines():
        m = source_re.match(line)
        if m:
            current = m.group(1)
        elif current:
            counts[current] += 1

    if not counts:
        return
    print("Largest rendered templates (by line count):")
    for path, n in counts.most_common(TOP_N_TEMPLATES):
        print(f"  {n:6d}  {path}")


def report_errors_by_subchart(error_text):
    chart_re = re.compile(r"([A-Za-z0-9_.\-]+)/templates/")
    counts = Counter(chart_re.findall(error_text))
    if not counts:
        return
    print("Errors by sub-chart:")
    for chart, n in counts.most_common():
        print(f"  {chart}: {n}")


def check_render(chart_dir, chart_name, extra_args):
    template_args = list(extra_args)
    if supports_skip_schema_validation():
        template_args.append("--skip-schema-validation")
    else:
        print(
            "WARNING: this helm version does not support --skip-schema-validation "
            "(needed for the KISS sub-chart's JSON schema) — CI uses a newer helm "
            "(azure/setup-helm@v5.0.1) where this works; consider upgrading your "
            "local helm to match. Rendering without it, may fail on schema validation."
        )

    result = run(["helm", "template", chart_name, str(chart_dir), *template_args],
                 capture_output=True, text=True)

    if result.returncode != 0:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        report_errors_by_subchart(result.stdout + result.stderr)
        return False, "helm template failed to render"

    doc_count = sum(1 for line in result.stdout.splitlines() if line.startswith("---"))
    if doc_count <= 0:
        return False, "rendered 0 manifests"

    report_largest_templates(result.stdout)
    detail = f"{doc_count} manifests"
    print(f"OK: rendered {detail}")
    return True, detail


def print_summary(results, overall_ok):
    log("VERIFY SUMMARY")
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name.ljust(width)} : {status} ({detail})")
    print()
    if overall_ok:
        print("All checks passed.")
    else:
        print("One or more checks failed — see details above.")


def main():
    if len(sys.argv) > 2:
        die("usage: verify-podiumd-chart.py [<chart-source>]")
    source_arg = sys.argv[1] if len(sys.argv) == 2 else None
    chart_name = os.environ.get("CHART_NAME", "podiumd")

    require_helm()

    log("Resolving chart source")
    chart_dir = resolve_chart_dir(source_arg)
    print(f"Using local chart source: {chart_dir}")

    results = []

    def run_step(name, title, func, *args):
        log(title)
        ok, detail = func(*args)
        results.append((name, ok, detail))
        if not ok:
            print_summary(results, overall_ok=False)
            sys.exit(1)

    run_step("UTF-8 format", "UTF-8 format check", check_utf8_format, chart_dir)

    log("Ensuring dependency repos are configured")
    ensure_repos_configured()

    run_step("Dependencies", "Resolving dependencies (helm dependency update)", check_dependencies, chart_dir)
    run_step("Dupe check", "Duplicate key scan", check_duplicate_keys, chart_dir)

    extra_args = lint_args_for(chart_dir)
    run_step("Lint", "helm lint", check_lint, chart_dir, extra_args)
    run_step("Full render", "helm template", check_render, chart_dir, chart_name, extra_args)

    print_summary(results, overall_ok=True)


if __name__ == "__main__":
    main()
