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
from lib.render_scope import (
    CHART_NAME, OWN_TEMPLATES_PREFIX, build_resource_locations, chart_name_from_source,
    friendly_vendor_charts, print_grouped_findings, resource_line, split_rendered_by_source,
)

# Any container invoking one of these as its `command`, with "-c" somewhere
# in command+args, is treated as an embedded shell script — matches this
# chart's own convention (command: ["/bin/sh", "-c"] / ["sh", "-c"], args:
# the script) as well as vendored sub-charts using the same shape.
SHELLCHECK_SHELL_NAMES = {"sh", "bash", "dash", "ksh"}

# error/warning are shellcheck's own "likely a real bug" tiers (syntax
# problems, quoting that will actually break, undefined-option portability
# issues); info/style are suggestions/preferences — cosmetic, not reported
# at all, same policy as check_yamllint's cosmetic findings.
SHELLCHECK_FAILING_LEVELS = {"error", "warning"}


def _shell_name(token):
    return token.rsplit("/", 1)[-1] if isinstance(token, str) else None


def find_shell_scripts(obj, source, path=""):
    """Recursively walk a parsed manifest (dict/list/scalar) looking for a
    container-shaped dict with a command/args pair that invokes a shell
    with "-c" (in either list, in either order — this chart uses both
    `command: [".../sh", "-c"], args: [<script>]` and
    `command: [...], args: ["-c", <script>]`). Returns (source, path,
    shell, script_text) tuples."""
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
            combined = (command if isinstance(command, list) else []) + \
                       (args if isinstance(args, list) else [])
            shell = _shell_name(combined[0]) if combined else None
            if shell in SHELLCHECK_SHELL_NAMES:
                for i, tok in enumerate(combined):
                    if tok == "-c" and i + 1 < len(combined) and isinstance(combined[i + 1], str):
                        found.append((source, path, shell, combined[i + 1]))
                        break
        for key, value in obj.items():
            found.extend(find_shell_scripts(value, source, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(find_shell_scripts(item, source, f"{path}[{i}]"))
    return found


def extract_shell_scripts(docs):
    """docs: list of (source, doc_text) pairs, e.g. from
    split_rendered_by_source. Parses each doc_text as YAML and returns
    every embedded shell script found in it, tagged with its source plus
    the containing resource's own (kind, namespace, name) — constant for
    every script found within the same doc, one resource per doc — so a
    finding can later be resolved back to a rendered-output line via
    lib.render_scope.resource_line."""
    scripts = []
    for source, doc_text in docs:
        try:
            parsed = yaml.safe_load(doc_text)
        except yaml.YAMLError:
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
        for found_source, path, shell, script_text in find_shell_scripts(parsed, source):
            scripts.append((found_source, path, shell, script_text, kind, namespace, name))
    return scripts


def run_shellcheck(shell, script_text):
    """Lint one embedded script, returning shellcheck's "comments" list (each
    a dict with level/code/line/message) — or None if shellcheck's own
    output couldn't be parsed as JSON (a shellcheck bug/crash, not a chart
    problem)."""
    result = run(["shellcheck", "-s", shell, "-f", "json1", "-"],
                 input=script_text, capture_output=True, text=True)
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
    """"<source> (<path>) — script line <N>[:<col>] (rendered line M)" for
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
    fails — but a FRIENDLY_VENDOR_KEYWORDS/local dependency (see
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

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *extra_args],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return False, "helm template failed to render"

    locations = build_resource_locations(result.stdout)
    docs = split_rendered_by_source(result.stdout)
    vendor_map = friendly_vendor_charts(chart_dir)
    own_docs = [(s, t) for s, t in docs if s.startswith(OWN_TEMPLATES_PREFIX)]
    vendored_docs = [(s, t) for s, t in docs if not s.startswith(OWN_TEMPLATES_PREFIX)]

    own_real, vendored_friendly, vendored_other = [], [], []
    for source, path, shell, script_text, kind, namespace, name in extract_shell_scripts(own_docs):
        comments = run_shellcheck(shell, script_text)
        if comments is None:
            return False, "shellcheck produced unparseable output"
        for c in comments:
            if c.get("level") in SHELLCHECK_FAILING_LEVELS:
                own_real.append((source, path, c, kind, namespace, name))

    for source, path, shell, script_text, kind, namespace, name in extract_shell_scripts(vendored_docs):
        comments = run_shellcheck(shell, script_text)
        if comments is None:
            return False, "shellcheck produced unparseable output"
        chart = chart_name_from_source(source)
        for c in comments:
            if c.get("level") in SHELLCHECK_FAILING_LEVELS:
                finding = (source, path, c, kind, namespace, name)
                (vendored_friendly if chart in vendor_map else vendored_other).append(finding)

    if own_real:
        print(f"Found {len(own_real)} real shellcheck issue(s) in this chart's own templates "
              f"(not cosmetic — these fail the check):")
        print_grouped_findings(
            own_real,
            key_fn=_shellcheck_group_key,
            item_fn=lambda f: _shellcheck_location(f, locations),
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if vendored_friendly:
        print(f"Found {len(vendored_friendly)} shellcheck issue(s) in partner-maintained "
              f"vendored sub-chart(s) (reported for visibility, never a failure):")
        print_grouped_findings(
            vendored_friendly,
            key_fn=_shellcheck_group_key,
            item_fn=lambda f: f"{_shellcheck_location(f, locations)} [{vendor_map[chart_name_from_source(f[0])]}]",
            label_fn=_shellcheck_group_label,
            items_label="location(s)",
        )
        print()

    if vendored_other:
        by_chart = Counter(chart_name_from_source(source) for source, *_rest in vendored_other)
        print(f"{len(vendored_other)} shellcheck finding(s) across {len(by_chart)} other "
              f"vendored sub-chart(s) (outside this repo's scope, not shown, never a failure)")

    if not (own_real or vendored_friendly or vendored_other):
        print("OK: no shellcheck findings in the rendered chart")

    detail = (f"{len(own_real)} real (own), {len(vendored_friendly)} partner-vendor, "
              f"{len(vendored_other)} other-vendor")
    if own_real:
        return False, detail
    return True, detail
