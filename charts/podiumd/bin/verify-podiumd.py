#!/usr/bin/env python3
"""
Verifies the podiumd chart, cheapest/local checks first so a plain content
bug fails fast without waiting on `helm dependency update`'s network round
trip:
  1. values.yaml is valid UTF-8 with no BOM (a BOM breaks YAML tooling if present)
  2. values.yaml has no duplicate keys silently overwriting earlier values
  3. templates/*.yaml has no pair of files that are structurally near-
     duplicates of each other (report-only, never fails — see lib.dry_check)
  4. every `image:` field in this chart's OWN templates/*.yaml calls the
     shared podiumd.image helper, per .github/copilot-instructions.md's
     "Image References" convention (never a hand-interpolated
     `.repository`:`.tag` or a bare literal) — scanned on the raw template
     source, since a rendered image string can't be told apart from one
     that used the helper (see lib.image_references_check)
  5. every Deployment/StatefulSet/DaemonSet/Job/CronJob in this chart's OWN
     templates/*.yaml has a nodeSelector field somewhere in its pod spec,
     per .github/copilot-instructions.md's AKS-Blue convention ("all
     workloads" require one) — a template with none can never be made
     compliant by an env-values override (see lib.node_selector_check)
  6. no vendored sub-chart under charts/podiumd/charts/ has BOTH a pinned
     .tgz package and an extracted directory of the same name sitting next
     to it — Helm silently prefers the extracted (possibly stale/modified)
     copy over the pinned package, "has caused broken deployments" per
     .claude/commands/helm-tgz-inspect.md. A cheap filesystem check, so it
     runs up front with the other trivial scans — and it must run before
     step 9 regardless: that step's own dependency rebuild (rm -rf charts/
     + helm dependency update) would otherwise wipe the evidence before
     this check ever saw it (see lib.vendored_tgz_check)
  7. component versions in Chart.yaml + values.yaml match the matching
     docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and docs/images/images-<version>.yaml
     (any component the doc lists, not a hardcoded set) — and, given --baseline,
     every component that actually changed vs the baseline (chart version,
     app/image tag, added, or removed) has a row in that upgrade.md, a
     mention in the matching values-deltas.md, and — if its image tag
     changed — an entry in images-<version>.yaml, even if no doc mentions
     it yet (see lib.docs_consistency)
  8. README.md's values-reference content is not out of sync with
     values.yaml (a renamed/added/removed key, or a changed default/
     comment) — regenerated via a real `helm-docs --dry-run` and diffed
     against the actual file, never written in place (see
     lib.helm_docs_check). Unrelated to step 7: that's upgrade-doc drift
     triggered by a version bump; this is values-reference drift
     triggered by any values.yaml edit at all, version bump or not
  9. every repo a Chart.yaml dependency actually needs (a classic Helm
     repo's index.yaml, or an OCI chart's manifest), AND every registry a
     values.yaml digest pin resolves to without needing Dependencies to
     have vendored anything yet, is reachable and authorized — a handful
     of lightweight requests, not a real `helm dependency update` or a
     full image pull, so an unreachable/unauthorized repo/registry fails
     here in seconds instead of however far into step 10's full
     re-download (or, for a pin needing the vendored-subchart-default
     fallback, step 11's own check) the same problem would otherwise
     surface. Each finding is reported with its kind (chart/image) and
     source location (Chart.yaml:<line> / values.yaml:<line>) (see
     lib.repo_access)
  10. all Chart.yaml dependencies actually resolve and bundle (helm
      dependency update)

  11. every digest-pinned image in values.yaml still matches its live
      upstream registry digest — except a tag known to slide (this repo's
      git history shows it's changed digest before, or the registry
      currently has a more specific sibling tag at the same digest), where
      drift is expected and passes, just reported for visibility. Runs
      right after step 10 rather than with the other local/network checks
      above: a pin with no "repository:" of its own in values.yaml (e.g.
      openzaak, openformulieren) falls back to the same component's
      vendored subchart default, read straight out of its .tgz under
      charts/podiumd/charts/ — which step 10 is what actually populates
      (see lib.chart.subchart_default_repository, lib.image_digests)
  12. the chart lints cleanly with the CI placeholder values
  13. the chart renders cleanly with `helm template` using the CI placeholder values
  14. yamllint against that render finds no structurally-real problem (duplicate
      keys, syntax errors) in this chart's OWN templates — cosmetic findings
      (trailing whitespace, comment style, ...) aren't reported at all, and
      a vendored sub-chart finding is printed per-item if it's from a
      partner vendor, else only gets a one-line count — neither
      scope ever fails except OWN (see lib.yamllint_check)
  15. kubeconform against that same render finds no real API-schema
      violation in this chart's OWN templates (wrong types, unknown fields,
      a resource that doesn't even parse) — a CRD with no known schema
      (Keycloak, ECK, Redis, ...) is skipped, not an error, and vendored
      findings follow the same partner-vendor-gets-detail rule, never a
      failure (see lib.kubeconform_check)
  16. shellcheck against every shell script embedded in a container's
      command/args in this chart's OWN templates finds no real bug
      (error/warning-level — bad quoting, undefined variables, portability
      issues) — info/style-level suggestions aren't reported at all, and
      vendored findings follow the same partner-vendor-gets-detail rule,
      never a failure (see lib.shellcheck_check)
  17. kube-score's container-resources check finds every container in this
      chart's OWN templates declaring CPU/memory requests AND limits, per
      .github/copilot-instructions.md's own documented "Resource Requests
      and Limits" convention — the only kube-score check this repo has an
      actual policy for; every other kube-score check (NetworkPolicy,
      ImagePullPolicy, SecurityContext UID/GID, PodDisruptionBudgets, ...)
      is unused, generic best-practice noise this repo has never claimed
      to enforce. Same partner-vendor/other-vendor reporting split as
      steps 14-16 (partner gets per-item detail, other stays a one-line
      count) — but a vendored sub-chart's missing resources IS this
      repo's job regardless of which org maintains it (wireable via that
      sub-chart's values.yaml key, same doc), so an other-vendor finding
      here is genuinely actionable, just deprioritized in the output.
      Neither ever fails the check yet, though: the backlog is untriaged
      and partly upstream-blocked (see lib.kube_score_check)

  18. every unique digest-pinned image has its own newest same-variant tag
      looked up on its upstream registry (a tag-list call, no image pull —
      cached by (repository, version), see lib.image_upgrade_check) —
      "upgradable" if a numerically-newer tag is currently published,
      regardless of whether it fixes anything (that's step 19's job).
      Report-only, never fails (see lib.image_upgrade_check)

  19. every unique digest-pinned image is scanned for known CVEs with a fix
      available, via a per-image `docker run aquasec/trivy:latest` (same
      tool this repo already scans images with in
      .github/workflows/trivy-vuln-scanner.yaml). Deliberately last: pulling
      and scanning every image via Docker is by far the heaviest single
      operation in this whole script, so every cheaper step gets a chance
      to fail fast first. Report-only, never fails regardless of severity —
      a HIGH/CRITICAL finding is a triage decision for a human, not a
      chart-correctness fact (see lib.cve_check)

  Steps 14-19's "partner vendor" carve-out (see lib.render_scope.friendly_vendor_charts):
  Maykin, Info(NL), ICATT, Worth, WeAreFrank, Dimpact, and any local
  ("file://") dependency are close/collaborative enough that their
  findings are worth seeing individually, even though this repo still
  can't fix their code directly. Every other vendored sub-chart (elastic,
  redis-operator, keycloak-operator, openbao, ...) stays
  aggregate-count-only. Steps 4-6 don't use this carve-out — they
  only ever scan this chart's own templates/checked-out sub-charts, never
  a vendored sub-chart's rendered content.

Steps 8, 14-19 each need an external tool (helm-docs/yamllint/kubeconform/
shellcheck/kube-score/none (just network)/docker+trivy, respectively)
beyond helm — run --help for exactly which binary/package each one needs,
and add its step to --skip= to bypass a missing one (skipping means that
check doesn't run, not that it passes; step 19 is the one exception — a
missing docker makes it report itself skipped rather than failed, since
it was designed as non-blocking even before it joined the regular
--skip=/--include= pipeline). Steps 4-6 and 9 are pure-Python (step 9 uses
only the standard library's own urllib, no external binary) and need no
external tool beyond a network connection.

Stops at the first failing step and prints a PASS/FAIL summary table, mirroring
the /helm-precommit workflow (BOM check, dupe check, lint, full render) plus
this script's own dependency-resolution, image-digest, and docs-consistency checks.

Always verifies charts/podiumd next to this script — there is no way to point
it at a different chart source.

The actual check logic lives in charts/podiumd/bin/lib/ (one module per
check, plus lib/render_scope.py for the infrastructure shared by every
check that inspects a `helm template` render, and lib/dependencies.py for
the dependency-vendoring set-image-digests.py also needs) — this file is
the CLI entry point: argument parsing, the ordered run_step() pipeline,
and the handful of checks too small/foundational to warrant their own
module (UTF-8/BOM, duplicate-key scan, lint/render).

Usage:
    verify-podiumd.py
    verify-podiumd.py --baseline 4.8.5
        # also check the doc's SOURCE (left-hand) versions for each changed
        # component against the actual baseline release — resolved to the
        # `podiumd-4.8.5` tag, falling back to the `feature/podiumd-4.8.5` /
        # `origin/feature/podiumd-4.8.5` branch if the tag doesn't exist yet.
        # Pass an explicit git ref instead of a bare version to use it as-is.
    verify-podiumd.py --skip=helm-lint,full-render
        # skip one or more steps entirely, comma-separated, no spaces
        # (shown as SKIP, never a failure) — useful to iterate faster on a
        # single check, or work around a step that's broken for reasons
        # unrelated to what you're testing. Valid step names: utf8-format,
        # dupe-check, dry-check, image-references, node-selector,
        # vendored-tgz, docs-consistency, helm-docs-check, repo-access,
        # dependencies, image-digests, helm-lint, full-render, yamllint,
        # kubeconform, shellcheck, kube-score, image-upgrades, check-cves.
        # See --help for the full list.
        # Note: check-cves is the one most worth skipping day to day if you
        # just want a normal run WITHOUT pulling every image via Docker —
        # step 19 runs by default like every other step (no separate
        # opt-in flag).
    verify-podiumd.py --include=kube-score
        # the inverse of --skip=: run ONLY the named step(s) (plus whatever
        # step(s) each one needs as a prerequisite — e.g. kube-score also
        # pulls in "Dependencies", since its render would otherwise fail on
        # unresolved sub-charts). Every other step shows as SKIP.
    verify-podiumd.py --include=kube-score,shellcheck
        # comma-separate multiple step names to run a specific subset —
        # each one's own prerequisites are still included automatically, so
        # "Dependencies" here still runs once, not twice. --include= cannot
        # be combined with --skip= (nothing left to skip once everything
        # but the included set is already skipped).
    verify-podiumd.py --detail-cve-check
        # CVE scan: itemize CRITICAL/HIGH findings per affected package for
        # EVERY image bucket (own, partner-vendor, AND other-vendor) instead
        # of the default terse per-image severity totals — see lib.cve_check.

Exit code is non-zero if any check fails — safe to use as a CI gate.
"""
import argparse
import re
import shutil
import sys

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import UTF8_BOM
from lib.procutil import run

# Each check's actual logic lives in its own lib module (see that module's
# docstring for what it does and why) — main()'s run_step() pipeline is the
# only thing here that needs the check functions themselves. Tests exercise
# a check (and any helper it calls) through that same lib module directly —
# see charts/podiumd/bin/tests/verify-podiumd/conftest.py's lib*
# fixtures — rather than through this file, so this import list stays
# exactly what main() calls, no re-exports to keep in sync by hand.
from lib.dry_check import check_dry
from lib.image_digests import check_image_digests
from lib.cve_check import check_cves
from lib.dependencies import check_dependencies, ensure_repos_configured
from lib.repo_access import check_repo_access
from lib.image_upgrade_check import check_image_upgrades
from lib.image_references_check import check_image_references
from lib.node_selector_check import check_node_selector
from lib.docs_consistency import check_docs_consistency
from lib.helm_docs_check import check_helm_docs
from lib.vendored_tgz_check import check_vendored_tgz_extraction
from lib.render_scope import CHART_NAME, lint_args_for, report_errors_by_subchart, report_largest_templates
from lib.yamllint_check import check_yamllint
from lib.kubeconform_check import check_kubeconform
from lib.shellcheck_check import check_shellcheck
from lib.kube_score_check import check_kube_score

DEFAULT_CHART_DIR = SCRIPT_DIR.parent


def log(title):
    print(f"\n=== {title} ===")


def die(message):
    """Hard-stop for setup/precondition failures that happen before any
    checklist step begins (not part of the PASS/FAIL summary)."""
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def require_helm():
    if shutil.which("helm") is None:
        die("helm is not installed")


def resolve_chart_dir():
    chart_dir = DEFAULT_CHART_DIR.resolve()
    if not (chart_dir / "Chart.yaml").is_file():
        die(f"{chart_dir} does not contain a Chart.yaml")
    return chart_dir


def check_utf8_format(chart_dir):
    values_path = chart_dir / "values.yaml"
    data = values_path.read_bytes()
    if data[:len(UTF8_BOM)] == UTF8_BOM:
        return False, "BOM found — run strip-utf8-bom.py to fix (this script never writes to values.yaml)"
    print(f"OK: no BOM in {values_path.name}")
    return True, "no BOM"


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
                f'{values_path.name}:{line_no}: duplicate "{key}" under [{parent}] '
                f'(first line {scope_keys[scope_id][key]})'
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


def check_render(chart_dir, extra_args):
    result = run(["helm", "template", CHART_NAME, str(chart_dir), *extra_args],
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
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        print(f"  {name.ljust(width)} : {status} ({detail})")
    print()
    if overall_ok:
        print("All checks passed.")
    else:
        print("One or more checks failed — see details above.")


# (step name for --skip=/--include=, step name) for every skippable step,
# in the order they run. Order here also drives --help's listing.
SKIPPABLE_STEPS = [
    ("utf8-format", "UTF-8 format"),
    ("dupe-check", "Dupe check"),
    ("dry-check", "DRY check"),
    ("image-references", "Image references"),
    ("node-selector", "Node selector"),
    ("vendored-tgz", "Vendored tgz"),
    ("docs-consistency", "Docs consistency"),
    ("helm-docs-check", "Helm docs check"),
    ("repo-access", "Repo access"),
    ("dependencies", "Dependencies"),
    ("image-digests", "Image digests"),
    ("helm-lint", "Helm lint"),
    ("full-render", "Full render"),
    ("yamllint", "yamllint"),
    ("kubeconform", "kubeconform"),
    ("shellcheck", "shellcheck"),
    ("kube-score", "kube-score"),
    ("image-upgrades", "Image upgrades"),
    ("check-cves", "CVE scan"),
]

# step name -> the step(s) it needs to have actually run first, for
# --include= (see prerequisites_for). Every render-based check
# (lint/full-render/yamllint/kubeconform/shellcheck/kube-score) needs
# "Dependencies" to have populated charts/*.tgz first, or its own `helm
# template`/`helm lint` call fails on unresolved sub-charts — "Image
# upgrades" and "CVE scan" each do their own `helm template` call
# internally for the same reason. "Image digests" also needs it, but for a
# cheaper reason: a pin with no "repository:" of its own falls back to
# reading the vendored subchart's own default straight out of its .tgz
# (lib.chart.subchart_default_repository) — charts/*.tgz is gitignored, so
# on a fresh checkout it doesn't exist at all until "Dependencies" has
# actually run once. "CVE scan" additionally needs "Image upgrades" to
# have actually run: it reads that step's cache (read-only, see
# lib.cve_check) to annotate a finding "upgradable to X", and a
# --include=check-cves run with no fresh cache already on disk would
# otherwise never see one populated. "Dependencies" itself needs "Repo
# access" — not a functional data dependency like the others here, just
# so a lone --include=dependencies run still gets the fast fail lib.repo_
# access exists for, instead of only ever seeing it as part of a full run.
# A step not listed here has no prerequisite (it works standalone on
# values.yaml/the filesystem/the registry, same as it does in the normal
# full run).
STEP_PREREQUISITES = {
    "Dependencies": ("Repo access",),
    "Image digests": ("Dependencies",),
    "Helm lint": ("Dependencies",),
    "Full render": ("Dependencies",),
    "yamllint": ("Dependencies",),
    "kubeconform": ("Dependencies",),
    "shellcheck": ("Dependencies",),
    "kube-score": ("Dependencies",),
    "Image upgrades": ("Dependencies",),
    "CVE scan": ("Dependencies", "Image upgrades"),
}


def prerequisites_for(step_name):
    """Transitive closure of STEP_PREREQUISITES for step_name. Currently
    only one level deep, but resolved as a closure rather than a single
    lookup so a future chained prerequisite doesn't silently go missing —
    order doesn't matter here, since run_step() below runs steps in the
    pipeline's own fixed order regardless of this set's iteration order."""
    resolved = set()
    stack = list(STEP_PREREQUISITES.get(step_name, ()))
    while stack:
        step = stack.pop()
        if step not in resolved:
            resolved.add(step)
            stack.extend(STEP_PREREQUISITES.get(step, ()))
    return resolved


# Rendered into --help's epilog (see main()) — built from SKIPPABLE_STEPS
# rather than a hand-maintained list, so it can't drift out of sync with it.
STEPS_HELP = "\nSteps usable with --skip=/--include= (in run order):\n" + "\n".join(
    f"  {flag:<18}{step_name}" for flag, step_name in SKIPPABLE_STEPS
) + "\n"

REQUIRED_TOOLS_HELP = """
Required external tools (each is only needed for the check(s) noted; a
missing tool makes that check fail with a clear message — add its step to
--skip= to bypass it instead, e.g. if it's not installed locally):
  helm         required to run at all — checked once up front, before any
               step (even a pure-filesystem one like utf8-format), so a
               --skip=/--include= selection that avoids every helm-using
               step still needs it installed
  helm-docs    Helm docs check             (https://github.com/norwoodj/helm-docs — single static binary)
  yamllint     yamllint check              (apt/pip package "yamllint")
  kubeconform  kubeconform check           (https://github.com/yannh/kubeconform — single static binary)
  shellcheck   shellcheck check            (apt package "shellcheck", or https://www.shellcheck.net)
  kube-score   kube-score check            (https://github.com/zegl/kube-score — single static binary)
  docker       CVE scan (pulls trivy + every pinned image — the one exception
               to "missing tool fails the check": no docker just reports the
               scan as skipped, since it was already designed to never block
               a run over infrastructure it can't assume everyone has)
  az           optional, Dependencies only — used solely to tell an Azure
               auth problem apart from a network blip when `helm dependency
               update` fails against an *.azurecr.io repo; missing/unused az
               just falls back to the plain retry-with-backoff behavior
"""


def main():
    parser = argparse.ArgumentParser(description="Verify the podiumd chart.",
                                     epilog=STEPS_HELP + REQUIRED_TOOLS_HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", default=None,
                        help="baseline release to also check the upgrade doc's SOURCE versions "
                             "against — a bare version (e.g. 4.8.5) is resolved to the podiumd-4.8.5 "
                             "tag, falling back to the feature/podiumd-4.8.5 branch; anything else is "
                             "used as a literal git ref")
    parser.add_argument("--detail-cve-check", action="store_true",
                        help="CVE scan: itemize CRITICAL/HIGH findings per affected package for "
                             "EVERY image bucket (own, partner-vendor, AND other-vendor), not just "
                             "the terse per-image severity totals a normal run prints")
    parser.add_argument("--skip", default=None, metavar="STEP1,STEP2,...",
                        help="comma-separated (no spaces) list of steps to skip (e.g. to iterate "
                             "faster, or work around a known-broken step) — shown as SKIP in the "
                             "summary, never counted as a failure. Cannot combine with --include. "
                             "See the step list below")
    parser.add_argument("--include", default=None, metavar="STEP1,STEP2,...",
                        help="comma-separated (no spaces) list of steps to run — plus any step(s) "
                             "each one needs as a prerequisite (see STEP_PREREQUISITES). Every step "
                             "not included (directly or as a prerequisite of an included step) shows "
                             "as SKIP. Cannot combine with --skip. See the step list below")
    args = parser.parse_args()

    valid_flags = {flag for flag, _ in SKIPPABLE_STEPS}

    def parse_step_list(raw, option_name):
        if not raw:
            return []
        flags = [f for f in raw.split(",") if f]
        unknown = [f for f in flags if f not in valid_flags]
        if unknown:
            parser.error(f"{option_name}: unknown step(s): {', '.join(unknown)} — valid steps: "
                          f"{', '.join(flag for flag, _ in SKIPPABLE_STEPS)}")
        return flags

    skip_flags = parse_step_list(args.skip, "--skip")
    include_flags = parse_step_list(args.include, "--include")

    if include_flags and skip_flags:
        parser.error("--include cannot be combined with --skip")

    if include_flags:
        target_steps = {dict(SKIPPABLE_STEPS)[flag] for flag in include_flags}
        runnable = set(target_steps)
        for step in target_steps:
            runnable |= prerequisites_for(step)
        skipped_steps = {step_name for _, step_name in SKIPPABLE_STEPS if step_name not in runnable}
    else:
        skipped_steps = {dict(SKIPPABLE_STEPS)[flag] for flag in skip_flags}

    require_helm()

    log("Resolving chart source")
    chart_dir = resolve_chart_dir()
    print(f"Using local chart source: {chart_dir}")

    results = []

    def run_step(name, title, func, *fargs):
        log(title)
        if name in skipped_steps:
            if include_flags:
                print(f"SKIPPED (not included via --include={','.join(include_flags)})")
            else:
                print(f"SKIPPED (--skip={','.join(skip_flags)})")
            results.append((name, None, "skipped"))
            return
        ok, detail = func(*fargs)
        results.append((name, ok, detail))
        if not ok:
            print_summary(results, overall_ok=False)
            sys.exit(1)

    run_step("UTF-8 format", "UTF-8 format check", check_utf8_format, chart_dir)
    run_step("Dupe check", "Duplicate key scan", check_duplicate_keys, chart_dir)
    run_step("DRY check", "Template duplication scan", check_dry, chart_dir)
    run_step("Image references", "Checking image: fields use the podiumd.image helper",
             check_image_references, chart_dir)
    run_step("Node selector", "Checking workloads expose a nodeSelector field",
             check_node_selector, chart_dir)
    run_step("Vendored tgz", "Checking for extracted dirs shadowing a pinned .tgz",
             check_vendored_tgz_extraction, chart_dir)
    run_step("Docs consistency", "Checking versions against upgrade docs",
             check_docs_consistency, chart_dir, args.baseline)
    run_step("Helm docs check", "Checking README.md against values.yaml (helm-docs)",
             check_helm_docs, chart_dir)

    run_step("Repo access", "Checking access to Chart.yaml's dependency repos and values.yaml's image registries",
             check_repo_access, chart_dir)

    log("Ensuring dependency repos are configured")
    ok, msg = ensure_repos_configured()
    if not ok:
        die(msg)

    run_step("Dependencies", "Resolving dependencies (helm dependency update)", check_dependencies, chart_dir)

    run_step("Image digests", "Checking image digests against upstream registries",
             check_image_digests, chart_dir)

    extra_args = lint_args_for(chart_dir)
    run_step("Helm lint", "helm lint", check_lint, chart_dir, extra_args)
    run_step("Full render", "Full render", check_render, chart_dir, extra_args)
    run_step("yamllint", "yamllint (rendered output)", check_yamllint, chart_dir, extra_args)
    run_step("kubeconform", "kubeconform (rendered output)", check_kubeconform, chart_dir, extra_args)
    run_step("shellcheck", "shellcheck (embedded shell scripts)", check_shellcheck, chart_dir, extra_args)
    run_step("kube-score", "kube-score (resource requests/limits)", check_kube_score, chart_dir, extra_args)
    run_step("Image upgrades", "Checking for newer published tags", check_image_upgrades, chart_dir, extra_args)
    run_step("CVE scan", "Scanning pinned images for known CVEs (trivy)", check_cves, chart_dir, extra_args,
              args.detail_cve_check)

    print_summary(results, overall_ok=True)


if __name__ == "__main__":
    main()
