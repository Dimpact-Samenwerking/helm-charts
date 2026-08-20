"""Verifies every container `image:` field in this chart's OWN
templates/*.yaml goes through the shared `podiumd.image` helper, per
.github/copilot-instructions.md's "Image References" convention: "All
images in podiumd templates use `{{ include "podiumd.image" <image> }}`
... NEVER embed plain repo:tag strings in templates."

Scans the raw template source, not a `helm template` render — by the time
an image string is rendered, there is no way to tell whether it went
through the helper or was hand-interpolated (e.g.
`"{{ .repository }}:{{ .tag }}"`) or hardcoded outright. This also means
the check only ever covers this chart's own templates; a vendored
sub-chart's templates aren't this repo's source to scan."""
import re

IMAGE_LINE_RE = re.compile(r"^\s*image:\s*(.+)$")
HELPER_CALL_RE = re.compile(r'include\s+"podiumd\.image"')


def scan_image_references(templates_dir):
    """Returns a list of (path, line_no, value) for every `image:` line in
    templates/*.yaml whose value doesn't call the podiumd.image helper."""
    findings = []
    for path in sorted(templates_dir.rglob("*.yaml")):
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = IMAGE_LINE_RE.match(line)
            if not m:
                continue
            value = m.group(1).strip()
            if HELPER_CALL_RE.search(value):
                continue
            findings.append((path, i, value))
    return findings


def check_image_references(chart_dir):
    findings = scan_image_references(chart_dir / "templates")

    if not findings:
        print('OK: every image: field in templates/*.yaml calls the podiumd.image helper')
        return True, "0 violation(s)"

    print(f'Found {len(findings)} image: field(s) not using the podiumd.image helper '
          f'(.github/copilot-instructions.md "Image References"):')
    for path, line_no, value in findings:
        rel = path.relative_to(chart_dir)
        print(f"  {rel}:{line_no}  {value}")

    return False, f"{len(findings)} violation(s)"
