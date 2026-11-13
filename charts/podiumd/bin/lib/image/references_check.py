"""Check that every `image:` in this chart's templates/*.yaml uses the `podiumd.image` helper.

Scans template source, not a render: after rendering a helper call can't be
told apart from hand-interpolation. Vendored sub-charts are not scanned.
"""

import re

from pathlib import Path

from lib.chart.paths import files_under

IMAGE_LINE_RE = re.compile(r"^\s*image:\s*(.+)$")
HELPER_CALL_RE = re.compile(r'include\s+"podiumd\.image"')


def scan_image_references(templates_dir: Path) -> list[tuple[Path, int, str]]:
    """(path, line_no, value) for every templates/*.yaml `image:` line not calling podiumd.image."""
    return [finding for path in files_under(templates_dir, "*.yaml") for finding in _template_violations(path)]


def _template_violations(path: Path) -> list[tuple[Path, int, str]]:
    """scan_image_references' findings in one template file."""
    findings: list[tuple[Path, int, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        image_match = IMAGE_LINE_RE.match(line)
        value = image_match.group(1).strip() if image_match else None
        if value is not None and not HELPER_CALL_RE.search(value):
            findings.append((path, line_no, value))
    return findings


def check_image_references(chart_dir: Path):
    """verify-podiumd check: print each `image:` line not using podiumd.image; fail if any."""
    findings = scan_image_references(chart_dir / "templates")

    if not findings:
        print("OK: every image: field in templates/*.yaml calls the podiumd.image helper")
        return True, "0 violation(s)"

    print(
        f"Found {len(findings)} image: field(s) not using the podiumd.image helper "
        f'(.github/copilot-instructions.md "Image References"):'
    )
    for path, line_no, value in findings:
        rel = path.relative_to(chart_dir)
        print(f"  {rel}:{line_no}  {value}")

    return False, f"{len(findings)} violation(s)"
