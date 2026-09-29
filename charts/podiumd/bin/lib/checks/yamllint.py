"""Run yamllint on the `helm template` render (raw templates aren't valid YAML)."""

import re
import shutil

from collections import Counter
from pathlib import Path

from lib.procutil import run
from lib.render_scope import OWN_TEMPLATES_PREFIX
from lib.render_scope import build_line_sources
from lib.render_scope import chart_name_from_source
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import print_grouped_findings
from lib.render_scope import print_other_vendor_summary
from lib.render_scope import print_own_findings_heading
from lib.render_scope import print_partner_findings_heading
from lib.render_scope import render_chart
from lib.render_scope import scan_outcome
from lib.settings import quality_gates_yamllint_failing_rules

# line-length and document-start are noise for rendered manifests; indent-sequences
# accepts this chart's deliberate unindented list items.
YAMLLINT_CONFIG = """
extends: default
rules:
  line-length: disable
  document-start: disable
  indentation:
    indent-sequences: whatever
"""

YAMLLINT_FINDING_RE = re.compile(
    r"^\s*(?P<line>\d+):(?P<col>\d+)\s+(?P<level>error|warning)\s+"
    r"(?P<message>.*?)\s*\((?P<rule>[a-z0-9-]+)\)\s*$",
    re.MULTILINE,
)

# A finding as (rendered line, source, level, message, rule).
YamllintFinding = tuple[int, str | None, str, str, str]


def _classify_yamllint_findings(
    output: str, sources: dict[int, str | None], vendor_map: dict[str, str], failing_rules: set[str]
):
    """Bucket every non-cosmetic finding into (own_real, vendored_friendly, vendored_other)."""
    own_real: list[YamllintFinding] = []
    vendored_friendly: list[YamllintFinding] = []
    vendored_other: list[YamllintFinding] = []
    for m in YAMLLINT_FINDING_RE.finditer(output):
        line_no = int(m.group("line"))
        rule = m.group("rule")
        source = sources.get(line_no)
        if rule not in failing_rules:
            continue  # cosmetic — never reported, own or vendored
        finding = (line_no, source, m.group("level"), m.group("message"), rule)
        if source and source.startswith(OWN_TEMPLATES_PREFIX):
            own_real.append(finding)
        elif chart_name_from_source(source) in vendor_map:
            vendored_friendly.append(finding)
        else:
            vendored_other.append(finding)
    return own_real, vendored_friendly, vendored_other


def check_yamllint(chart_dir: Path, extra_args: list[str]):
    """Run yamllint on the render and report findings by scope.

    Only quality_gates.yamllint_failing_rules findings (duplicate keys, syntax errors)
    are reported; the rest is cosmetic. Own findings fail. Friendly-vendor findings
    (lib.render_scope.friendly_vendor_charts) are listed; other vendored charts get one
    count line. Repeats per file are grouped into one line with a line list.
    """
    if shutil.which("yamllint") is None:
        return False, "yamllint is not installed (see --skip-yamllint to bypass)"

    failing_rules = quality_gates_yamllint_failing_rules(chart_dir)

    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"

    rendered = result.stdout
    sources = build_line_sources(rendered)
    vendor_map = friendly_vendor_charts(chart_dir)

    lint_result = run(["yamllint", "-d", YAMLLINT_CONFIG, "-"], input=rendered, capture_output=True, text=True)
    output = lint_result.stdout + lint_result.stderr

    own_real, vendored_friendly, vendored_other = _classify_yamllint_findings(
        output, sources, vendor_map, failing_rules
    )

    if own_real:
        print_own_findings_heading("yamllint", len(own_real))
        print_grouped_findings(
            own_real,
            key_fn=lambda f: (f[1], f[2], f[3], f[4]),
            item_fn=lambda f: str(f[0]),
            label_fn=lambda k: f"[{k[1].upper():7s}] {k[0]}  {k[2]}  ({k[3]})",
            items_label="rendered line(s)",
        )
        print()

    if vendored_friendly:
        print_partner_findings_heading("yamllint", len(vendored_friendly))
        print_grouped_findings(
            vendored_friendly,
            key_fn=lambda f: (f[1], f[2], f[3], f[4]),
            item_fn=lambda f: str(f[0]),
            label_fn=lambda k: (
                f"[{k[1].upper():7s}] {k[0]} ({vendor_map[chart_name_from_source(k[0])]})  {k[2]}  ({k[3]})"
            ),
            items_label="rendered line(s)",
        )
        print()

    if vendored_other:
        by_chart = Counter(chart_name_from_source(source) for _, source, _, _, _ in vendored_other)
        print_other_vendor_summary("yamllint", len(vendored_other), len(by_chart))

    if not (own_real or vendored_friendly or vendored_other):
        print("OK: no yamllint findings in the rendered chart")

    return scan_outcome(own_real, vendored_friendly, vendored_other)
