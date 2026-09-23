"""Lints every shell script embedded in a container's command/args (this
chart's `command: [".../sh", "-c"], args: [<script>]` /
`command: [...], args: ["-c", <script>]` convention) — catches actual
shell bugs (bad quoting, undefined variables, portability issues) that
nothing else here checks; helm lint/kubeconform/yamllint all treat the
script as an opaque string."""

import json
import shutil

from collections import Counter

import yaml

from lib.procutil import run
from lib.render_scope import OWN_TEMPLATES_PREFIX
from lib.render_scope import VendorBucketScan
from lib.render_scope import chart_name_from_source
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import print_grouped_findings
from lib.render_scope import render_chart_docs
from lib.render_scope import resource_line
from lib.render_scope import scan_outcome
from lib.settings import quality_gates_shellcheck_failing_levels
from lib.settings import quality_gates_shellcheck_shell_names


def _shell_name(token):
    return token.rsplit("/", 1)[-1] if isinstance(token, str) else None


def find_shell_scripts(obj, source, shell_names, path=""):
    """Recursively walk a parsed manifest (dict/list/scalar) looking for a
    container-shaped dict with a command/args pair that invokes a shell
    with "-c" (in either list, in either order — this chart uses both
    `command: [".../sh", "-c"], args: [<script>]` and
    `command: [...], args: ["-c", <script>]`). `shell_names` is the set of
    recognized shell binaries (see quality_gates.shellcheck_shell_names in
    lib.settings) — a container invoking anything else as its `command`
    is not treated as an embedded shell script at all. Returns (source,
    path, shell, script_text) tuples."""
    found = []
    if isinstance(obj, dict):
        command = obj.get("command")
        args = obj.get("args")
        if isinstance(command, list) or isinstance(args, list):
            # Take only the halves that are actually lists — a malformed
            # manifest where one of command/args is a scalar (a bare-rendered
            # `args: {{ .Values.x }}`, a CRD instance, a hand-written Pod)
            # would otherwise raise `list + str`; leave reporting that field
            # to yamllint/kubeconform rather than crashing the scan here.
            combined = (command if isinstance(command, list) else []) + (args if isinstance(args, list) else [])
            shell = _shell_name(combined[0]) if combined else None
            if shell in shell_names:
                for i, tok in enumerate(combined):
                    if tok == "-c" and i + 1 < len(combined) and isinstance(combined[i + 1], str):
                        found.append((source, path, shell, combined[i + 1]))
                        break
        for key, value in obj.items():
            found.extend(find_shell_scripts(value, source, shell_names, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(find_shell_scripts(item, source, shell_names, f"{path}[{i}]"))
    return found


def extract_shell_scripts(docs, shell_names):
    """docs: list of (source, doc_text) pairs, e.g. from
    split_rendered_by_source. Parses each doc_text as YAML and returns
    every embedded shell script found in it (see find_shell_scripts for
    `shell_names`), tagged with its source plus the containing resource's
    own (kind, namespace, name) — constant for every script found within
    the same doc, one resource per doc — so a finding can later be
    resolved back to a rendered-output line via lib.render_scope.
    resource_line."""
    scripts = []
    for source, doc_text in docs:
        try:
            parsed = yaml.safe_load(doc_text)
        except yaml.YAMLError:  # noqa: S112 -- not a YAML resource, holds no shell script
            continue
        if parsed is None:
            continue
        if isinstance(parsed, dict):
            metadata = parsed.get("metadata") or {}
            kind = parsed.get("kind")
            namespace = metadata.get("namespace") or ""
            name = metadata.get("name")
        else:
            kind = namespace = name = None  # not a single-object doc — no resource_line lookup possible
        for found_source, path, shell, script_text in find_shell_scripts(parsed, source, shell_names):
            scripts.append((found_source, path, shell, script_text, kind, namespace, name))
    return scripts


def run_shellcheck(shell, script_text):
    """Lint one embedded script, returning shellcheck's "comments" list (each
    a dict with level/code/line/message) — or None if shellcheck's own
    output couldn't be parsed as JSON (a shellcheck bug/crash, not a chart
    problem)."""
    result = run(["shellcheck", "-s", shell, "-f", "json1", "-"], input=script_text, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)["comments"]
    except (json.JSONDecodeError, KeyError):
        return None


def _shellcheck_group_key(finding):
    _source, _path, c, _kind, _namespace, _name = finding
    return c.get("level"), c.get("code"), c.get("message")


def _shellcheck_group_label(key):
    level, code, message = key
    return f"[{level.upper():7s}] SC{code}: {message}"


def _shellcheck_location(finding, locations):
    """ "<source> (<path>) — script line <N>[:<col>] (rendered line M)" for
    one finding (source, path, comment, kind, namespace, name). The
    script line/column are shellcheck's own, against the embedded script
    text it was fed — position within that script, NOT a line number in
    the rendered YAML or the template file (shellcheck has no notion of
    either; `path` is what locates the right container's script among
    possibly several in the same manifest). "rendered line M" is this
    finding's containing resource's own start line in the full render
    (see build_resource_locations) — omitted if it can't be resolved
    (kind/name missing, or ambiguous — see resource_line)."""
    source, path, c, kind, namespace, name = finding
    line = c.get("line")
    if not line:
        base = f"{source} ({path})"
    else:
        column = c.get("column")
        pos = f"{line}:{column}" if column else str(line)
        base = f"{source} ({path}) — script line {pos}"
    if not kind or not name:
        return base
    rendered_line = resource_line(locations, kind, name, namespace=namespace)
    return f"{base} (rendered line {rendered_line})" if rendered_line else base


def _own_shellcheck_findings(own_docs, shell_names, failing_levels):
    """Lints every embedded script found in this chart's own docs, keeping
    only failing_levels-severity comments. Returns (None, error) if any
    script's shellcheck output couldn't be parsed."""
    own_real = []
    for source, path, shell, script_text, kind, namespace, name in extract_shell_scripts(own_docs, shell_names):
        comments = run_shellcheck(shell, script_text)
        if comments is None:
            return None, "shellcheck produced unparseable output"
        own_real.extend((source, path, c, kind, namespace, name) for c in comments if c.get("level") in failing_levels)
    return own_real, None


def _vendored_script_result(entry, failing_levels):
    """One extract_shell_scripts entry -> (chart, findings, error): lints
    the entry's script, keeping only failing_levels-severity comments as
    (source, path, comment, kind, namespace, name) findings. findings is
    None (and error set) if shellcheck's own output couldn't be parsed."""
    source, path, shell, script_text, kind, namespace, name = entry
    comments = run_shellcheck(shell, script_text)
    if comments is None:
        return None, None, "shellcheck produced unparseable output"
    findings = [(source, path, c, kind, namespace, name) for c in comments if c.get("level") in failing_levels]
    return chart_name_from_source(source), findings, None


def _vendored_shellcheck_findings(vendored_docs, shell_names, failing_levels, vendor_map):
    """Lints every embedded script found in vendored docs (see
    _vendored_script_result), splitting findings into (vendored_friendly,
    vendored_other) by vendor_map membership. Returns (None, None, error)
    if any script's shellcheck output couldn't be parsed."""
    vendored_friendly, vendored_other = [], []
    for entry in extract_shell_scripts(vendored_docs, shell_names):
        chart, findings, error = _vendored_script_result(entry, failing_levels)
        if error:
            return None, None, error
        (vendored_friendly if chart in vendor_map else vendored_other).extend(findings)
    return vendored_friendly, vendored_other, None


def _scan_rendered_chart(chart_dir, extra_args, shell_names, failing_levels):
    """Renders the chart, lints its own scripts and every vendored sub-
    chart's scripts (see _own_shellcheck_findings/
    _vendored_shellcheck_findings) with shellcheck, and bundles the result
    into a VendorBucketScan. Returns (None, error) on any render/shellcheck
    failure, else (VendorBucketScan, None)."""
    rendered, error = render_chart_docs(chart_dir, extra_args)
    if rendered is None:
        return None, error
    locations, docs = rendered.locations, rendered.docs
    vendor_map = friendly_vendor_charts(chart_dir)
    own_docs = [(s, t) for s, t in docs if s.startswith(OWN_TEMPLATES_PREFIX)]
    vendored_docs = [(s, t) for s, t in docs if not s.startswith(OWN_TEMPLATES_PREFIX)]

    own_real, error = _own_shellcheck_findings(own_docs, shell_names, failing_levels)
    if error:
        return None, error

    vendored_friendly, vendored_other, error = _vendored_shellcheck_findings(
        vendored_docs, shell_names, failing_levels, vendor_map
    )
    if error:
        return None, error

    return VendorBucketScan(locations, vendor_map, own_real, vendored_friendly, vendored_other), None


def _print_shellcheck_findings(scan):
    """Prints check_shellcheck's three report sections (own/vendored-
    friendly/vendored-other) for a completed VendorBucketScan -- see
    check_shellcheck's own docstring for what each section means and why
    they're reported differently."""
    if scan.own_real:
        print(
            f"Found {len(scan.own_real)} real shellcheck issue(s) in this chart's own templates "
            f"(not cosmetic — these fail the check):"
        )
        print_grouped_findings(
            scan.own_real,
            key_fn=_shellcheck_group_key,
            item_fn=lambda f: _shellcheck_location(f, scan.locations),
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if scan.vendored_friendly:
        print(
            f"Found {len(scan.vendored_friendly)} shellcheck issue(s) in partner-maintained "
            f"vendored sub-chart(s) (reported for visibility, never a failure):"
        )
        print_grouped_findings(
            scan.vendored_friendly,
            key_fn=_shellcheck_group_key,
            item_fn=lambda f: (
                f"{_shellcheck_location(f, scan.locations)} [{scan.vendor_map[chart_name_from_source(f[0])]}]"
            ),
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if scan.vendored_other:
        by_chart = Counter(chart_name_from_source(source) for source, *_rest in scan.vendored_other)
        print(
            f"{len(scan.vendored_other)} shellcheck finding(s) across {len(by_chart)} other "
            f"vendored sub-chart(s) (outside this repo's scope, not shown, never a failure)"
        )

    if not (scan.own_real or scan.vendored_friendly or scan.vendored_other):
        print("OK: no shellcheck findings in the rendered chart")


def check_shellcheck(chart_dir, extra_args):
    """Lints every shell script embedded in a container's command/args
    (this chart's `command: [".../sh", "-c"], args: [<script>]` /
    `command: [...], args: ["-c", <script>]` convention) — catches actual
    shell bugs (bad quoting, undefined variables, portability issues) that
    nothing else here checks; helm lint/kubeconform/yamllint all treat the
    script as an opaque string.

    Same scope split as check_yamllint/check_kubeconform: this chart's OWN
    templates/ vs. a vendored sub-chart under charts/podiumd/charts/*. A
    dependency's script isn't ours to fix, so a vendored finding never
    fails — but a friendly-vendor/local dependency (see
    friendly_vendor_charts) is printed per-item; every other vendored
    sub-chart only ever gets a one-line aggregate count. Within OWN scope,
    error/warning-level findings (shellcheck's own "likely a real bug"
    tiers) fail the check; info/style (suggestions/preferences) aren't
    reported at all, same policy as check_yamllint's cosmetic findings.
    Every per-item location also gets a "(rendered line N)" hint — see
    _shellcheck_location/build_resource_locations — pointing at the
    containing resource's own start line in the full render (not the
    exact script line within it, which is a position kubeconform/
    kube-score/shellcheck's own line/column already covers separately)."""
    if shutil.which("shellcheck") is None:
        return False, "shellcheck is not installed (see --skip-shellcheck to bypass)"

    shell_names = quality_gates_shellcheck_shell_names(chart_dir)
    failing_levels = quality_gates_shellcheck_failing_levels(chart_dir)

    scan, error = _scan_rendered_chart(chart_dir, extra_args, shell_names, failing_levels)
    if error:
        return False, error

    _print_shellcheck_findings(scan)

    return scan_outcome(scan.own_real, scan.vendored_friendly, scan.vendored_other)
