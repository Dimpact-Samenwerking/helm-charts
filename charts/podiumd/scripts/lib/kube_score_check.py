"""Checks that every container in the rendered chart declares CPU/memory
requests AND limits — this repo's own documented convention
(.github/copilot-instructions.md's "Resource Requests and Limits"), not a
generic kube-score opinion (see KUBE_SCORE_CHECK_ID)."""
import json
import shutil

from lib.procutil import run
from lib.render_scope import (
    CHART_NAME, OWN_TEMPLATES_PREFIX, chart_name_from_source, print_grouped_findings,
    split_rendered_by_source, supports_skip_schema_validation,
)

# The one kube-score check this repo actually has a documented, existing
# policy for — .github/copilot-instructions.md's "Resource Requests and
# Limits" convention: "Every container in every template MUST declare
# requests + limits for CPU/memory ... Sub-chart components wired via
# values.yaml". Every other kube-score check (NetworkPolicy coverage,
# ImagePullPolicy, SecurityContext UID/GID, PodDisruptionBudgets, anti-
# affinity, ...) is a generic best-practice opinion this repo has never
# claimed to enforce — running the full default rule set would produce a
# wall of unrelated findings (67+ on this repo's own real render), so only
# this one check is used.
KUBE_SCORE_CHECK_ID = "container-resources"


def run_kube_score(yaml_text):
    """Score a YAML stream with kube-score, returning the parsed list of
    scored objects (kube-score's own JSON schema — each a dict with
    object_name/checks/...) — or None if kube-score's own output couldn't
    be parsed as JSON (a kube-score bug/crash, not a chart problem).

    kube-score prints the JSON value "null" (not "[]") when a stream has
    no scoreable objects at all — e.g. a vendored sub-chart consisting
    entirely of CRDs, like eck-operator-crds. json.loads("null") returns
    None, which would otherwise be indistinguishable from "unparseable" —
    normalize it to [] so a CRD-only chart doesn't look like a crash."""
    result = run(["kube-score", "score", "-o", "json", "-"],
                 input=yaml_text, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data or []


def extract_resource_findings(kube_score_objects):
    """From a kube-score run's scored objects, pull every non-skipped,
    below-full-grade KUBE_SCORE_CHECK_ID finding as (object_name,
    container, summary) — object_name is kube-score's own
    "Kind/apiVersion/namespace/name" identifier, container is the comment's
    "path" (the container the missing request/limit belongs to)."""
    findings = []
    for obj in kube_score_objects or []:
        object_name = obj.get("object_name", "?")
        for c in obj.get("checks", []):
            if c["check"]["id"] != KUBE_SCORE_CHECK_ID or c.get("skipped") or c["grade"] >= 10:
                continue
            for comment in c.get("comments") or []:
                findings.append((object_name, comment.get("path", ""), comment.get("summary", "")))
    return findings


def check_kube_score(chart_dir, extra_args):
    """Checks that every container in the rendered chart declares CPU/
    memory requests AND limits — this repo's own documented convention
    (.github/copilot-instructions.md's "Resource Requests and Limits"),
    not a generic kube-score opinion (see KUBE_SCORE_CHECK_ID).

    Scope split, but NOT the same fail policy as check_yamllint/
    check_kubeconform/check_shellcheck: a missing resource on a vendored
    sub-chart's container is still this repo's job to fix (wired via that
    sub-chart's values.yaml key, per the same documented convention) — it
    is not an upstream-code problem the way a YAML-style or shell-script
    issue is. So, unlike those three checks' partner-vendor/other-vendor
    split (only a partner chart's findings get individual detail), EVERY
    vendored finding here is printed individually regardless of vendor —
    partner and other alike, one flat "vendored sub-charts" bucket, no
    friendlier treatment for a partner chart than any other vendor (grouped
    per container, by chart — kube-score's own JSON carries no per-
    resource source info, so — like check_kubeconform — each vendored
    sub-chart is scored as its own separate kube-score run). It still does
    NOT fail the check yet, though: the current backlog is untriaged, and
    some gaps are upstream-blocked (the sub-chart's own template exposes no
    resources field at all for a given container — nothing to wire). Only
    an OWN finding fails; promoting vendored to failing is a deliberate
    future step once the backlog is resolved or written into
    docs/misc/resource-overview.md as an accepted/upstream-blocked gap."""
    if shutil.which("kube-score") is None:
        return False, "kube-score is not installed (see --skip-kube-score to bypass)"

    template_args = list(extra_args)
    if supports_skip_schema_validation():
        template_args.append("--skip-schema-validation")

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *template_args],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return False, "helm template failed to render"

    docs = split_rendered_by_source(result.stdout)
    own_text = "".join(text for source, text in docs if source.startswith(OWN_TEMPLATES_PREFIX))
    own_objects = run_kube_score(own_text)
    if own_objects is None:
        return False, "kube-score produced unparseable output"
    own_real = extract_resource_findings(own_objects)

    vendored_by_chart_docs = {}
    for source, text in docs:
        if not source.startswith(OWN_TEMPLATES_PREFIX):
            vendored_by_chart_docs.setdefault(chart_name_from_source(source), []).append(text)

    vendored = []
    for chart, texts in vendored_by_chart_docs.items():
        objects = run_kube_score("".join(texts))
        if objects is None:
            return False, "kube-score produced unparseable output"
        for object_name, container, summary in extract_resource_findings(objects):
            vendored.append((chart, object_name, container, summary))

    if own_real:
        print(f"Found {len(own_real)} real kube-score issue(s) in this chart's own templates "
              f"(missing resources.requests/.limits — required by "
              f".github/copilot-instructions.md — these fail the check):")
        print_grouped_findings(
            own_real,
            key_fn=lambda f: (f[0], f[1]),
            item_fn=lambda f: f[2],
            label_fn=lambda k: f"{k[0]} ({k[1]})",
            items_label="issue(s)",
        )
        print()

    if vendored:
        print(f"Found {len(vendored)} kube-score issue(s) across all vendored sub-charts — "
              f"partner and other alike (missing resources.requests/.limits — wireable via this "
              f"repo's values.yaml per the same convention, but not yet triaged — reported, does "
              f"not fail the check):")
        print_grouped_findings(
            vendored,
            key_fn=lambda f: (f[0], f[1], f[2]),
            item_fn=lambda f: f[3],
            label_fn=lambda k: f"[{k[0]}] {k[1]} ({k[2]})",
            items_label="issue(s)",
        )
        print()

    if not (own_real or vendored):
        print("OK: no kube-score container-resources findings in the rendered chart")

    detail = (f"{len(own_real)} real (own, fails), {len(vendored)} across all vendored sub-charts "
              f"— partner+other (reported, not enforced)")
    if own_real:
        return False, detail
    return True, detail
