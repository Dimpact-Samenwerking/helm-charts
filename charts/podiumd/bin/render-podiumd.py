#!/usr/bin/env python3
"""
Render the podiumd chart to a file — the same `helm template` invocation
verify-podiumd.py's checks run internally (via lib.render_scope.render_chart),
so the rendered output matches exactly what a failing check saw. Useful for
debugging the cause of a failed verify-podiumd.py check: render to a file
and inspect the manifest that check was actually looking at.

Usage:
    render-podiumd.py <output-file> [extra helm template args...]

With no extra args, renders using the default CI values
(charts/podiumd/ci/lint-values.yaml, if present) — the same defaults every
verify-podiumd.py check step renders against. Passing any extra args
replaces that default entirely (they are passed to `helm template` as-is),
e.g. to render with different --set overrides or to target a single
template with -s. Always prints which of the two applies before rendering
— a custom-args render can fail for reasons (missing values, disabled
sub-charts) that have nothing to do with any verify-podiumd.py check, so
don't mistake one for "the standard check just failed".

Examples:
    render-podiumd.py /tmp/podiumd.yaml
    render-podiumd.py /tmp/frankgateway.yaml -s templates/frankgateway.yaml --set kiss.enabled=false
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.render_scope import (
    lint_args_for, render_chart, report_errors_by_subchart, report_largest_templates,
)

CHART_DIR = SCRIPT_DIR.parent


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    output_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        extra_args = sys.argv[2:]
        print(f"Rendering with custom args (default -f ci/lint-values.yaml NOT applied): "
              f"{' '.join(extra_args)}")
    else:
        extra_args = lint_args_for(CHART_DIR)
        print(f"Rendering with default CI values: {' '.join(extra_args) or '(none found)'}")

    result = render_chart(CHART_DIR, extra_args)
    if result.returncode != 0:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        report_errors_by_subchart(result.stdout + result.stderr)
        print(f"error: helm template failed to render (nothing written to {output_path})")
        sys.exit(1)

    output_path.write_text(result.stdout)
    doc_count = sum(1 for line in result.stdout.splitlines() if line.startswith("---"))
    print(f"OK: rendered {doc_count} manifest(s) to {output_path}")
    report_largest_templates(result.stdout)


if __name__ == "__main__":
    main()
