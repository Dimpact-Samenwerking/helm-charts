"""Shared per-section output wrapper for show-component-baseline-version and show-image-baseline-version."""

from collections.abc import Callable


def show_baseline_section(label: str, baseline: str | None, resolve: Callable[[str], str | None]) -> bool:
    """Print "=== {label} baseline ===" and one section outcome; True if the section was shown.

    - `baseline` None: a "no {label} key — skipping" note (not an error).
    - `resolve(baseline)` returns a string: printed indented as-is; it carries
      its own "error: " prefix if wanted.
    - `resolve(baseline)` returns None: it already printed the success body.
    Always ends with a blank line."""
    print(f"=== {label} baseline ===")
    if baseline is None:
        print(f"  (release-baseline.yaml has no {label} key — skipping)")
        print()
        return False

    error = resolve(baseline)
    if error:
        print(f"  {error}")
        print()
        return False

    print()
    return True
