"""Read one file out of a dependency's vendored
charts/<name>-<version>.tgz, without extracting the archive."""

import tarfile

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency


def vendored_chart_file(chart_dir: Path, dep: ChartDependency, member: str, version: str | None = None) -> bytes | None:
    """The bytes of <name>/<member> inside dep's vendored .tgz under
    chart_dir/charts/ at version (default: dep["version"]). None if that
    version isn't vendored or the archive has no such file."""
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{version or dep['version']}.tgz"
    if not tgz_path.is_file():
        return None
    try:
        with tarfile.open(tgz_path) as tar:
            member_file = tar.extractfile(f"{dep['name']}/{member}")
            return None if member_file is None else member_file.read()
    except (KeyError, tarfile.TarError):
        return None
