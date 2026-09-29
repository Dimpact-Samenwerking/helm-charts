"""Regenerate images-baseline.yaml from a chart render; the last step of every image-pin writer."""

import sys

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.image.docs import regenerate_images_baseline_manifest
from lib.render_scope import lint_args_for
from lib.render_scope import render_chart
from lib.render_scope import rendered_chart_paths
from lib.yaml_types import YamlMapping


def refresh_images_baseline(
    chart_dir: Path, deps: list[ChartDependency], values: YamlMapping, images_baseline_path: Path
) -> None:
    """Regenerate images_baseline_path from a chart render, which also catches subchart-default images.

    Needs vendored sub-charts in sync with `deps`. Exits 1 when the render fails.
    """
    print()
    print("=== Regenerating images-baseline.yaml ===")
    # ci/lint-values.yaml: a bare values.yaml render fails on sub-charts' required fields.
    render_result = render_chart(chart_dir, lint_args_for(chart_dir))
    if render_result.returncode != 0:
        print(
            "  error: helm template failed to render — can't check for images defined only "
            "in a vendored sub-chart's own default values.yaml (see check_subchart_image_"
            "visibility); fix the render first"
        )
        print(render_result.stderr)
        sys.exit(1)
    rendered_paths = rendered_chart_paths(render_result.stdout)

    written, skipped, changed = regenerate_images_baseline_manifest(
        chart_dir, deps, values, images_baseline_path, rendered_paths
    )
    if changed:
        print(f"  wrote {written} entr{'y' if written == 1 else 'ies'}")
    else:
        print(f"  unchanged ({written} entr{'y' if written == 1 else 'ies'})")
    if skipped:
        print(
            f"  could not resolve a full url/digest for {len(skipped)} repositor{'y' if len(skipped) == 1 else 'ies'} "
            f"— review by hand:"
        )
        for repo in skipped:
            print(f"    {repo}")
