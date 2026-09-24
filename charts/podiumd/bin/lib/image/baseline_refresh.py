"""The images-baseline.yaml regeneration step every script that changes
an image pin ends with: render the chart, then hand the render to
lib.image.docs.regenerate_images_baseline_manifest. Shared by
fix-doc-consistency, update-component-version and update-image-version,
so a version bump never leaves images-baseline.yaml behind at the old
pin."""

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
    """Regenerates images_baseline_path for Chart.yaml's `deps` and
    values.yaml's `values`, rendering the chart first to also catch
    images defined only in a vendored sub-chart's default. Needs the
    vendored sub-charts in sync with `deps` (see lib.dependencies.
    ensure_vendored_dependencies). Exits 1 when the render fails."""
    print()
    print("=== Regenerating images-baseline.yaml ===")
    # Rendered with ci/lint-values.yaml (same convention every other
    # render-based check in this codebase already uses) — a bare
    # `values.yaml` render fails outright: several sub-charts declare
    # required fields (JSON-schema "minLength", etc.) only ever
    # satisfied by that CI overlay, which a real deploy always supplies
    # via its own environment-specific values anyway.
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
