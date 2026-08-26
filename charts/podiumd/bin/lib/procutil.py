"""Tiny subprocess wrappers shared across scripts."""
import subprocess
import sys


def run(cmd, **kwargs):
    """For `helm`/`git`/etc. calls that capture output — never raises on a
    non-zero exit, so callers decide what a failure means for them."""
    return subprocess.run(cmd, check=False, **kwargs)


def run_script(cmd, **kwargs):
    """For delegating to a sibling script (`[sys.executable, "other.py",
    ...]`) that inherits stdout/stderr, so its output interleaves with the
    caller's own prints in real time. Flushes the caller's stdout first —
    when stdout isn't a tty (piped, redirected, captured), prints made
    before this call are otherwise still sitting in Python's own buffer
    and can appear AFTER the child's output once that buffer finally
    flushes at process exit."""
    sys.stdout.flush()
    return subprocess.run(cmd, **kwargs)
