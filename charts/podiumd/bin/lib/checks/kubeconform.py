"""Validates the full `helm template` render against real Kubernetes API
schemas — catches unknown fields, wrong types, and missing required fields
that neither `helm lint` nor yamllint check (those only validate chart
structure / YAML syntax, not API conformance).

Every kubeconform invocation passes -cache (see kubeconform_cache_dir) so
schemas fetched over HTTP are reused across runs instead of re-fetched —
own templates + one run per distinct vendored chart is several
kubeconform invocations per check_kubeconform call, all hitting largely
the same set of Kubernetes API kinds/versions."""

import json
import shutil

from collections import Counter
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

from lib.procutil import run
from lib.render_scope import VendorBucketScan
from lib.render_scope import chart_name_from_source
from lib.render_scope import print_grouped_findings
from lib.render_scope import print_other_vendor_summary
from lib.render_scope import print_own_findings_heading
from lib.render_scope import print_partner_findings_heading
from lib.render_scope import resource_line
from lib.render_scope import scan_outcome
from lib.render_scope import scan_rendered_chart
from lib.settings import quality_gates_kubeconform_failing_statuses
from lib.yaml_types import shape_problem

KUBECONFORM_BASE_ARGS = [
    "-strict",  # also catch unknown/duplicate fields, not just type mismatches
    "-ignore-missing-schemas",  # this chart's many CRDs (Keycloak, ECK, Redis, ...) have no
    # schema in kubeconform's registry — skip them, don't error
    "-verbose",
    "-summary",
    "-output",
    "json",
]


# One entry of kubeconform's JSON "resources" list (kind/name/version/
# status/msg), and a finding as (vendored chart or None for own, resource).
class KubeconformResource(TypedDict):
    """One entry of kubeconform's JSON "resources" list: the fields this
    module reads (kubeconform always writes all of them; the optional ones
    are read with a fallback)."""

    status: str
    kind: NotRequired[str]
    name: NotRequired[str]
    msg: NotRequired[str]


_RESOURCE_LIST_SHAPE = [{"status": str, "kind?": str, "name?": str, "msg?": str}]


def _is_resource_list(value: object) -> TypeGuard[list[KubeconformResource]]:
    return shape_problem(value, _RESOURCE_LIST_SHAPE) is None


def parse_kubeconform_output(stdout: str) -> list[KubeconformResource] | None:
    """The "resources" of kubeconform's JSON output, or None when it isn't
    JSON of that shape (a kubeconform bug/crash, not a chart problem)."""
    try:
        data: object = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    resources = data.get("resources") if isinstance(data, dict) else None
    return resources if _is_resource_list(resources) else None


KubeconformEntry = tuple[str | None, KubeconformResource]


def kubeconform_cache_dir():
    """Where kubeconform's own -cache flag stores every Kubernetes API
    schema it fetches over HTTP. Shared across every chart/branch/worktree
    (not scoped under chart_dir) since schemas are keyed by Kubernetes
    version, not by this chart's content — there's no reason to
    re-download the same schemas per checkout. kubeconform requires the
    directory to already exist (it errors out rather than creating it),
    hence the mkdir in run_kubeconform below."""
    return Path.home() / ".cache" / "podiumd-kubeconform-schemas"


def run_kubeconform(yaml_text: str) -> list[KubeconformResource] | None:
    """Validate a YAML stream with kubeconform, returning the parsed
    "resources" list (each a dict with at least kind/name/version/status/
    msg) — or None if kubeconform's own output couldn't be parsed as JSON
    (a kubeconform bug/crash, not a chart problem)."""
    cache_dir = kubeconform_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    args = [*KUBECONFORM_BASE_ARGS, "-cache", str(cache_dir), "-"]
    result = run(["kubeconform", *args], input=yaml_text, capture_output=True, text=True)
    return parse_kubeconform_output(result.stdout)


def _kubeconform_group_key(entry: KubeconformEntry) -> tuple[str, str]:
    _chart, r = entry
    message = r.get("msg") or "(no message)"
    return r["status"], message.splitlines()[0]


def _kubeconform_group_label(key: tuple[str, ...]):
    status, first_line = key
    label = "ERROR" if status == "statusError" else "INVALID"
    return f"[{label:7s}] {first_line}"


def _kubeconform_item(entry: KubeconformEntry, locations: dict):
    """ "<kind>/<name>" plus a "(rendered line N)" hint when
    build_resource_locations can locate exactly this kind+name
    unambiguously (kubeconform's own JSON has no namespace field, so a
    kind+name that renders more than once — in different namespaces —
    can't be resolved to one line; the hint is just omitted then rather
    than risk pointing at the wrong resource)."""
    _chart, r = entry
    kind, name = r.get("kind"), r.get("name")
    base = f"{kind}/{name}"
    line = resource_line(locations, kind, name)
    return f"{base} (rendered line {line})" if line else base


def _own_kubeconform_findings(
    own_docs: list[tuple[str, str]], failing_statuses: set[str]
) -> tuple[list[KubeconformResource] | None, str | None]:
    """(own_real, None) — this chart's own templates validated with
    kubeconform in one run — or (None, error) on unparseable output."""
    own_resources = run_kubeconform("".join(text for _source, text in own_docs))
    if own_resources is None:
        return None, "kubeconform produced unparseable output"
    return [r for r in own_resources if r.get("status") in failing_statuses], None


def _scan_vendored_charts(
    docs: list[tuple[str, str]], failing_statuses: set[str], vendor_map: dict[str, str]
) -> tuple[list[KubeconformEntry] | None, list[KubeconformEntry] | None, str | None]:
    """Validates each vendored sub-chart's docs (every rendered doc outside
    OWN_TEMPLATES_PREFIX) with kubeconform separately
    (kubeconform's own JSON carries no per-resource source info, so —
    unlike check_yamllint — each vendored sub-chart is its own run here),
    splitting findings into (vendored_friendly, vendored_other) by
    vendor_map membership. Returns (None, None, error) if any sub-chart's
    kubeconform output couldn't be parsed."""
    vendored_by_chart = {}
    for source, text in docs:
        vendored_by_chart.setdefault(chart_name_from_source(source), []).append(text)

    vendored_friendly: list[KubeconformEntry] = []
    vendored_other: list[KubeconformEntry] = []
    for chart, texts in vendored_by_chart.items():
        resources = run_kubeconform("".join(texts))
        if resources is None:
            return None, None, "kubeconform produced unparseable output"
        for r in resources:
            if r.get("status") not in failing_statuses:
                continue
            (vendored_friendly if chart in vendor_map else vendored_other).append((chart, r))
    return vendored_friendly, vendored_other, None


def _print_kubeconform_findings(scan: VendorBucketScan[KubeconformResource, KubeconformEntry]):
    """Prints check_kubeconform's three report sections (own/vendored-
    friendly/vendored-other) for a completed VendorBucketScan -- see
    check_kubeconform's own docstring for what each section means and why
    they're reported differently."""
    if scan.own_real:
        print_own_findings_heading("kubeconform", len(scan.own_real))
        print_grouped_findings(
            [(None, r) for r in scan.own_real],
            key_fn=_kubeconform_group_key,
            item_fn=lambda entry: _kubeconform_item(entry, scan.locations),
            label_fn=_kubeconform_group_label,
            items_label="resource(s)",
        )
        print()

    if scan.vendored_friendly:
        print_partner_findings_heading("kubeconform", len(scan.vendored_friendly))
        print_grouped_findings(
            scan.vendored_friendly,
            key_fn=lambda entry: (entry[0], *_kubeconform_group_key(entry)),
            item_fn=lambda entry: _kubeconform_item(entry, scan.locations),
            label_fn=lambda k: f"{_kubeconform_group_label(k[1:])} — {k[0]} ({scan.vendor_map[k[0]]})",
            items_label="resource(s)",
        )
        print()

    if scan.vendored_other:
        by_chart = Counter(chart for chart, _ in scan.vendored_other)
        print_other_vendor_summary("kubeconform", len(scan.vendored_other), len(by_chart))

    if not (scan.own_real or scan.vendored_friendly or scan.vendored_other):
        print("OK: no kubeconform findings in the rendered chart")


def check_kubeconform(chart_dir: Path, extra_args: list):
    """Validates the full `helm template` render against real Kubernetes
    API schemas — catches unknown fields, wrong types, and missing
    required fields that neither `helm lint` nor yamllint check (those
    only validate chart structure / YAML syntax, not API conformance).

    Same scope split as check_yamllint: this chart's OWN templates/ vs. a
    vendored sub-chart bundled under charts/podiumd/charts/*. A
    dependency's content isn't ours to fix, so a vendored finding never
    fails — but a friendly-vendor/local dependency (see
    friendly_vendor_charts) is printed per-resource; every other vendored
    sub-chart only ever gets a one-line aggregate count (kubeconform's own
    JSON output carries no per-resource source info, so — unlike
    check_yamllint — each vendored sub-chart is validated as its own
    separate kubeconform run, to know which chart a finding belongs to).
    Every per-item finding also gets a "(rendered line N)" hint when it
    can be resolved unambiguously (see build_resource_locations/
    resource_line) — pipe the render to a file (render-podiumd) and
    jump straight there.

    Only an own+real finding (a genuine schema violation, or a resource
    kubeconform's own YAML parser couldn't even load — e.g. the
    frankgateway duplicate-key bug) fails the check; a CRD with no known
    schema (Keycloak, ECK, Redis, ...) is skipped, not an error."""
    if shutil.which("kubeconform") is None:
        return False, "kubeconform is not installed (see --skip-kubeconform to bypass)"

    failing_statuses = quality_gates_kubeconform_failing_statuses(chart_dir)

    scan, error = scan_rendered_chart(
        chart_dir,
        extra_args,
        own_findings=lambda docs: _own_kubeconform_findings(docs, failing_statuses),
        vendored_findings=lambda docs, vendor_map: _scan_vendored_charts(docs, failing_statuses, vendor_map),
    )
    if scan is None:
        return False, error

    _print_kubeconform_findings(scan)

    return scan_outcome(scan.own_real, scan.vendored_friendly, scan.vendored_other)
