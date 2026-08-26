#!/usr/bin/env python3
"""
Render the podiumd chart to a file — the same `helm template` invocation
verify-podiumd.py's checks run internally (via lib.render_scope.render_chart),
so the rendered output matches exactly what a failing check saw. Useful for
debugging the cause of a failed verify-podiumd.py check: render to a file
and inspect the manifest that check was actually looking at.

Usage:
    render-podiumd.py [output-file] [extra helm template args...]
    render-podiumd.py --stdout [extra helm template args...]

With no output-file, writes to charts/podiumd/rendered-helm.yaml (next to
this script). With --stdout instead of a file, the rendered manifest goes
to stdout — every other message (including report_largest_templates'
summary) goes to stderr instead, so stdout stays pure YAML and can be
piped/redirected (e.g. `render-podiumd.py --stdout | less`).

With no extra args, renders using the default CI values
(charts/podiumd/ci/lint-values.yaml, if present) — the same defaults every
verify-podiumd.py check step renders against. Passing any extra args
replaces that default entirely (they are passed to `helm template` as-is),
e.g. to render with different --set overrides or to target a single
template with -s. Always announces which of the two applies before
rendering — a custom-args render can fail for reasons (missing values,
disabled sub-charts) that have nothing to do with any verify-podiumd.py
check, so don't mistake one for "the standard check just failed".

Examples:
    render-podiumd.py
        # writes charts/podiumd/rendered-helm.yaml, default CI values
    render-podiumd.py /tmp/podiumd.yaml
    render-podiumd.py /tmp/frankgateway.yaml -s templates/frankgateway.yaml --set kiss.enabled=false
    render-podiumd.py --stdout | grep -A5 'kind: Deployment'
"""
import contextlib
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.render_scope import (
    lint_args_for, render_chart, report_errors_by_subchart, report_largest_templates,
)

CHART_DIR = SCRIPT_DIR.parent
DEFAULT_OUTPUT = CHART_DIR / "rendered-helm.yaml"


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    args = sys.argv[1:]
    to_stdout = bool(args) and args[0] == "--stdout"
    if to_stdout:
        args = args[1:]
        output_path = None
    else:
        output_path = Path(args[0]) if args else DEFAULT_OUTPUT
        args = args[1:] if args else []

    # In --stdout mode, stdout is the data channel (the rendered YAML) —
    # every status/diagnostic message must go to stderr instead, or it
    # would corrupt a pipe/redirect of stdout.
    def status(*a, **kw):
        print(*a, file=sys.stderr if to_stdout else None, **kw)

    if args:
        extra_args = args
        status(f"Rendering with custom args (default -f ci/lint-values.yaml NOT applied): "
               f"{' '.join(extra_args)}")
    else:
        extra_args = lint_args_for(CHART_DIR)
        status(f"Rendering with default CI values: {' '.join(extra_args) or '(none found)'}")

    result = render_chart(CHART_DIR, extra_args)
    if result.returncode != 0:
        status(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if to_stdout:
            with contextlib.redirect_stdout(sys.stderr):
                report_errors_by_subchart(result.stdout + result.stderr)
        else:
            report_errors_by_subchart(result.stdout + result.stderr)
        dest = "stdout" if to_stdout else str(output_path)
        status(f"error: helm template failed to render (nothing written to {dest})")
        sys.exit(1)

    doc_count = sum(1 for line in result.stdout.splitlines() if line.startswith("---"))
    if to_stdout:
        status(f"OK: rendered {doc_count} manifest(s) to stdout")
        with contextlib.redirect_stdout(sys.stderr):
            report_largest_templates(result.stdout)
        sys.stdout.write(result.stdout)
    else:
        output_path.write_text(result.stdout)
        status(f"OK: rendered {doc_count} manifest(s) to {output_path}")
        report_largest_templates(result.stdout)


if __name__ == "__main__":
    main()
