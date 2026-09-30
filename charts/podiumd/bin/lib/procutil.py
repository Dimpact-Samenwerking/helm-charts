"""Subprocess wrappers shared across scripts."""

# Sole subprocess entry point; callers pass fixed argv lists, never shell strings.
import subprocess  # nosec B404
import sys

from pathlib import Path
from typing import Literal
from typing import Required
from typing import TextIO
from typing import TypedDict
from typing import Unpack

RunResult = subprocess.CompletedProcess[str]


class RunOptions(TypedDict, total=False):
    """The subprocess.run keywords run() passes on. Always text mode."""

    text: Required[Literal[True]]
    capture_output: bool
    input: str
    cwd: Path
    stdout: TextIO


def run(cmd: list[str], **kwargs: Unpack[RunOptions]) -> RunResult:
    """Run cmd; never raises on a non-zero exit, so callers decide what failure means."""
    # Fixed argv list from the caller, no shell.
    return subprocess.run(cmd, check=False, **kwargs)  # nosec B603  # noqa: S603


def run_script(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Run a sibling script that inherits stdout/stderr.

    Flushes stdout first: when it isn't a tty, earlier prints would otherwise
    appear after the child's output."""
    sys.stdout.flush()
    return subprocess.run(cmd, check=check)  # nosec B603  # noqa: S603
