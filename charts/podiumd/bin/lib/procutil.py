"""Tiny subprocess wrappers shared across scripts."""

# The one intentional subprocess entry point for the whole codebase (helm/git
# CLI calls); every caller passes its own fixed argv list, never a shell
# string or externally-controlled command name.
import subprocess  # nosec B404
import sys

from typing import Any


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """For `helm`/`git`/etc. calls that capture output — never raises on a
    non-zero exit, so callers decide what a failure means for them."""
    # cmd is always a fixed argv list built by the caller (e.g. ["git", "mv", ...]),
    # never a shell string or user input; shell=True would be the actually unsafe
    # choice here.
    return subprocess.run(cmd, check=False, **kwargs)  # nosec B603  # noqa: S603


def run_script(cmd: list[str], *, check: bool = False, **kwargs: Any):
    """For delegating to a sibling script (`[sys.executable, "other.py",
    ...]`) that inherits stdout/stderr, so its output interleaves with the
    caller's own prints in real time. Flushes the caller's stdout first —
    when stdout isn't a tty (piped, redirected, captured), prints made
    before this call are otherwise still sitting in Python's own buffer
    and can appear AFTER the child's output once that buffer finally
    flushes at process exit."""
    sys.stdout.flush()
    # Same fixed-argv-list guarantee as run() above.
    return subprocess.run(cmd, check=check, **kwargs)  # nosec B603  # noqa: S603
