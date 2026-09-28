"""Argument and input handling for the scripts: help and argument-count
checks for the scripts that read sys.argv directly instead of using
argparse, and one-line errors instead of tracebacks for user-named files,
output paths and network failures."""

import http.client
import sys
import urllib.error

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def exit_on_help(doc: str | None) -> None:
    """Print doc and exit 0 when the only argument is -h or --help."""
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(doc)
        sys.exit(0)


def positional_args(doc: str | None, count: int) -> list[str]:
    """sys.argv[1:], which must hold exactly count arguments. Prints doc and
    exits 0 for -h/--help (see exit_on_help), or exits 1 for any other
    argument count."""
    exit_on_help(doc)
    if len(sys.argv) != count + 1:
        print(doc)
        sys.exit(1)
    return sys.argv[1:]


def read_user_file(path: Path, what: str) -> str:
    """The text of a file the user named (`what` says which, e.g.
    "--token-file"). Raises SystemExit when it doesn't exist, isn't a
    file, can't be read or isn't UTF-8."""
    if not path.is_file():
        msg = f"error: {what} {path} does not exist or is not a file"
        raise SystemExit(msg)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        msg = f"error: {what} {path} can't be read: {e}"
        raise SystemExit(msg) from e


def check_output_path(path: Path, what: str) -> None:
    """Raises SystemExit when a file the user named for output (`what`
    says which, e.g. "--output") can't be written: it is a directory, or
    its parent directory doesn't exist. Call it before any slow work, so
    a wrong path fails before that work is done."""
    if path.is_dir():
        msg = f"error: {what} {path} is a directory"
        raise SystemExit(msg)
    if not path.parent.is_dir():
        msg = f"error: {what} {path}: directory {path.parent} does not exist"
        raise SystemExit(msg)


@contextmanager
def network_errors(what: str) -> Generator[None]:
    """Turns a failed network request inside the block into a one-line
    SystemExit naming `what` (e.g. "container registry"): an HTTP error
    status, an unreachable host (DNS, SSL, refused, offline), a timeout
    or reset, or a URL http.client refuses (e.g. a version with a space
    in it)."""
    try:
        yield
    except urllib.error.HTTPError as e:
        msg = f"error: {what} request failed: HTTP {e.code} {e.reason} ({e.url})"
        raise SystemExit(msg) from e
    except urllib.error.URLError as e:
        msg = f"error: could not reach {what}: {e.reason}"
        raise SystemExit(msg) from e
    except (TimeoutError, ConnectionError) as e:
        msg = f"error: connection to {what} failed: {e}"
        raise SystemExit(msg) from e
    except http.client.InvalidURL as e:
        msg = f"error: invalid {what} URL: {e}"
        raise SystemExit(msg) from e
