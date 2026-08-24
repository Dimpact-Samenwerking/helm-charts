"""Validates the full `helm template` render against real Kubernetes API
schemas — catches unknown fields, wrong types, and missing required fields
that neither `helm lint` nor yamllint check (those only validate chart
structure / YAML syntax, not API conformance)."""
import json
import shutil
from collections import Counter

from lib.procutil import run
from lib.render_scope import (
    CHART_NAME, OWN_TEMPLATES_PREFIX, chart_name_from_source, friendly_vendor_charts,
    print_grouped_findings, split_rendered_by_source, supports_skip_schema_validation,
)

KUBECONFORM_ARGS = [
    "-strict",  # also catch unknown/duplicate fields, not just type mismatches
    "-ignore-missing-schemas",  # this chart's many CRDs (Keycloak, ECK, Redis, ...) have no
                                 # schema in kubeconform's registry — skip them, don't error
    "-verbose",
    "-summary",
    "-output", "json",
    "-",
]

# statusError covers both "resource couldn't even be parsed" (e.g. the
# frankgateway duplicate-key bug — a real, structural problem) and, in
# theory, a schema-fetch network failure. statusInvalid is a genuine schema
# violation. Both are non-cosmetic; statusSkipped (no schema, expected for
# CRDs) and statusValid are not findings at all.
KUBECONFORM_FAILING_STATUSES = {"statusError", "statusInvalid"}


def run_kubeconform(yaml_text):
    """Validate a YAML stream with kubeconform, returning the parsed
    "resources" list (each a dict with at least kind/name/version/status/
    msg) — or None if kubeconform's own output couldn't be parsed as JSON
    (a kubeconform bug/crash, not a chart problem)."""
    result = run(["kubeconform", *KUBECONFORM_ARGS], input=yaml_text, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)["resources"]
    except (json.JSONDecodeError, KeyError):
        return None


def _kubeconform_group_key(entry):
    _chart, r = entry
    message = r.get("msg") or "(no message)"
    return r["status"], message.splitlines()[0]


def _kubeconform_group_label(key):
    status, first_line = key
    label = "ERROR" if status == "statusError" else "INVALID"
    return f"[{label:7s}] {first_line}"


def check_kubeconform(chart_dir, extra_args):
    """Validates the full `helm template` render against real Kubernetes
    API schemas — catches unknown fields, wrong types, and missing
    required fields that neither `helm lint` nor yamllint check (those
    only validate chart structure / YAML syntax, not API conformance).

    Same scope split as check_yamllint: this chart's OWN templates/ vs. a
    vendored sub-chart bundled under charts/podiumd/charts/*. A
    dependency's content isn't ours to fix, so a vendored finding never
    fails — but a FRIENDLY_VENDOR_KEYWORDS/local dependency (see
    friendly_vendor_charts) is printed per-resource; every other vendored
    sub-chart only ever gets a one-line aggregate count (kubeconform's own
    JSON output carries no per-resource source info, so — unlike
    check_yamllint — each vendored sub-chart is validated as its own
    separate kubeconform run, to know which chart a finding belongs to).

    Only an own+real finding (a genuine schema violation, or a resource
    kubeconform's own YAML parser couldn't even load — e.g. the
    frankgateway duplicate-key bug) fails the check; a CRD with no known
    schema (Keycloak, ECK, Redis, ...) is skipped, not an error."""
    if shutil.which("kubeconform") is None:
        return False, "kubeconform is not installed (see --skip-kubeconform to bypass)"

    template_args = list(extra_args)
    if supports_skip_schema_validation():
        template_args.append("--skip-schema-validation")

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *template_args],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return False, "helm template failed to render"

    docs = split_rendered_by_source(result.stdout)
    vendor_map = friendly_vendor_charts(chart_dir)

    own_text = "".join(text for source, text in docs if source.startswith(OWN_TEMPLATES_PREFIX))
    own_resources = run_kubeconform(own_text)
    if own_resources is None:
        return False, "kubeconform produced unparseable output"
    own_real = [r for r in own_resources if r.get("status") in KUBECONFORM_FAILING_STATUSES]

    vendored_by_chart = {}
    for source, text in docs:
        if not source.startswith(OWN_TEMPLATES_PREFIX):
            vendored_by_chart.setdefault(chart_name_from_source(source), []).append(text)

    vendored_friendly, vendored_other = [], []
    for chart, texts in vendored_by_chart.items():
        resources = run_kubeconform("".join(texts))
        if resources is None:
            return False, "kubeconform produced unparseable output"
        for r in resources:
            if r.get("status") not in KUBECONFORM_FAILING_STATUSES:
                continue
            (vendored_friendly if chart in vendor_map else vendored_other).append((chart, r))

    if own_real:
        print(f"Found {len(own_real)} real kubeconform issue(s) in this chart's own templates "
              f"(not cosmetic — these fail the check):")
        print_grouped_findings(
            [(None, r) for r in own_real],
            key_fn=_kubeconform_group_key,
            item_fn=lambda entry: f"{entry[1].get('kind')}/{entry[1].get('name')}",
            label_fn=_kubeconform_group_label,
            items_label="resource(s)",
        )
        print()

    if vendored_friendly:
        print(f"Found {len(vendored_friendly)} kubeconform issue(s) in partner-maintained "
              f"vendored sub-chart(s) (reported for visibility, never a failure):")
        print_grouped_findings(
            vendored_friendly,
            key_fn=lambda entry: (entry[0],) + _kubeconform_group_key(entry),
            item_fn=lambda entry: f"{entry[1].get('kind')}/{entry[1].get('name')}",
            label_fn=lambda k: f"{_kubeconform_group_label(k[1:])} — {k[0]} ({vendor_map[k[0]]})",
            items_label="resource(s)",
        )
        print()

    if vendored_other:
        by_chart = Counter(chart for chart, _ in vendored_other)
        print(f"{len(vendored_other)} kubeconform finding(s) across {len(by_chart)} other "
              f"vendored sub-chart(s) (outside this repo's scope, not shown, never a failure)")

    if not (own_real or vendored_friendly or vendored_other):
        print("OK: no kubeconform findings in the rendered chart")

    detail = (f"{len(own_real)} real (own), {len(vendored_friendly)} partner-vendor, "
              f"{len(vendored_other)} other-vendor")
    if own_real:
        return False, detail
    return True, detail
