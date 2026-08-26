"""Runs yamllint against the full `helm template` render (never against raw
templates/*.yaml — those contain Go template syntax that isn't valid YAML
on its own)."""
import re
import shutil
from collections import Counter

from lib.procutil import run
from lib.render_scope import (
    CHART_NAME, OWN_TEMPLATES_PREFIX, build_line_sources, chart_name_from_source,
    friendly_vendor_charts, print_grouped_findings, supports_skip_schema_validation,
)

# yamllint config, tuned against this repo's own real findings (not
# guessed): line-length and document-start are disabled because they're
# pure noise for rendered k8s manifests (long image refs/URLs routinely
# exceed 80 chars; a lone manifest doesn't need a "---" header).
# indent-sequences: whatever accepts this chart's established convention of
# unindented list items (e.g. "initContainers:\n- name: ..."), which is a
# deliberate, consistent style choice here, not a mistake.
YAMLLINT_CONFIG = """
extends: default
rules:
  line-length: disable
  document-start: disable
  indentation:
    indent-sequences: whatever
"""

# Rules whose violation means the rendered YAML is structurally broken or
# ambiguous, not just differently styled — see check_yamllint. Every other
# yamllint rule (trailing-spaces, comments, colons, ...) is cosmetic: real
# findings worth fixing eventually, but never worth failing the build over.
YAMLLINT_FAILING_RULES = {"key-duplicates", "syntax"}

YAMLLINT_FINDING_RE = re.compile(
    r"^\s*(?P<line>\d+):(?P<col>\d+)\s+(?P<level>error|warning)\s+"
    r"(?P<message>.*?)\s*\((?P<rule>[a-z0-9-]+)\)\s*$",
    re.MULTILINE,
)


def check_yamllint(chart_dir, extra_args):
    """Runs yamllint against the full `helm template` render (never against
    raw templates/*.yaml — those contain Go template syntax that isn't
    valid YAML on its own) and buckets every finding several ways:

    - scope: this chart's OWN templates/ (Source starts with
      "podiumd/templates/") vs. a vendored sub-chart bundled under
      charts/podiumd/charts/*. A dependency's content isn't something this
      repo controls or can fix, so a vendored finding never fails — but a
      FRIENDLY_VENDOR_KEYWORDS/local ("file://") dependency (Maykin,
      Info(NL), ICATT, Worth, WeAreFrank, Dimpact, or this monorepo's own
      mi-data) is close/collaborative enough to be worth seeing
      individually; every other vendored sub-chart (elastic,
      redis-operator, keycloak-operator, openbao, ...) only ever gets a
      one-line aggregate count (there can be hundreds).
    - rule: YAMLLINT_FAILING_RULES (a structurally broken/ambiguous
      document — duplicate keys, a real syntax error) vs. everything else,
      which is cosmetic style — not reported at all, too noisy to be worth
      surfacing right now, and never fails regardless of scope.

    Only an OWN + non-cosmetic finding fails the check. Same-root-cause
    repeats in one file are grouped into a single line (an occurrence
    count + line list) rather than one line per hit, both for OWN findings
    and for partner-vendor findings."""
    if shutil.which("yamllint") is None:
        return False, "yamllint is not installed (see --skip-yamllint to bypass)"

    template_args = list(extra_args)
    if supports_skip_schema_validation():
        template_args.append("--skip-schema-validation")

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *template_args],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return False, "helm template failed to render"

    rendered = result.stdout
    sources = build_line_sources(rendered)
    vendor_map = friendly_vendor_charts(chart_dir)

    lint_result = run(["yamllint", "-d", YAMLLINT_CONFIG, "-"],
                       input=rendered, capture_output=True, text=True)
    output = lint_result.stdout + lint_result.stderr

    own_real, vendored_friendly, vendored_other = [], [], []
    for m in YAMLLINT_FINDING_RE.finditer(output):
        line_no = int(m.group("line"))
        rule = m.group("rule")
        source = sources.get(line_no)
        if rule not in YAMLLINT_FAILING_RULES:
            continue  # cosmetic — never reported, own or vendored
        finding = (line_no, source, m.group("level"), m.group("message"), rule)
        if source and source.startswith(OWN_TEMPLATES_PREFIX):
            own_real.append(finding)
        elif chart_name_from_source(source) in vendor_map:
            vendored_friendly.append(finding)
        else:
            vendored_other.append(finding)

    if own_real:
        print(f"Found {len(own_real)} real yamllint issue(s) in this chart's own templates "
              f"(not cosmetic — these fail the check):")
        print_grouped_findings(
            own_real,
            key_fn=lambda f: (f[1], f[2], f[3], f[4]),
            item_fn=lambda f: str(f[0]),
            label_fn=lambda k: f"[{k[1].upper():7s}] {k[0]}  {k[2]}  ({k[3]})",
            items_label="rendered line(s)",
        )
        print()

    if vendored_friendly:
        print(f"Found {len(vendored_friendly)} yamllint issue(s) in partner-maintained "
              f"vendored sub-chart(s) (reported for visibility, never a failure):")
        print_grouped_findings(
            vendored_friendly,
            key_fn=lambda f: (f[1], f[2], f[3], f[4]),
            item_fn=lambda f: str(f[0]),
            label_fn=lambda k: (f"[{k[1].upper():7s}] {k[0]} ({vendor_map[chart_name_from_source(k[0])]})"
                                 f"  {k[2]}  ({k[3]})"),
            items_label="rendered line(s)",
        )
        print()

    if vendored_other:
        by_chart = Counter(chart_name_from_source(source) for _, source, _, _, _ in vendored_other)
        print(f"{len(vendored_other)} yamllint finding(s) across {len(by_chart)} other vendored "
              f"sub-chart(s) (outside this repo's scope, not shown, never a failure)")

    if not (own_real or vendored_friendly or vendored_other):
        print("OK: no yamllint findings in the rendered chart")

    detail = (f"{len(own_real)} real (own), {len(vendored_friendly)} partner-vendor, "
              f"{len(vendored_other)} other-vendor")
    if own_real:
        return False, detail
    return True, detail
