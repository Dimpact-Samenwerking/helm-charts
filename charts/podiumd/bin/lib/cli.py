"""Script argument handling: help/argument-count checks for scripts that
read sys.argv directly, and one-line errors instead of tracebacks for bad
user input and network failures."""

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
    """sys.argv[1:], which must hold exactly count arguments. Exits 0 for
    -h/--help, or prints doc and exits 1 on a wrong count."""
    exit_on_help(doc)
    if len(sys.argv) != count + 1:
        print(doc)
        sys.exit(1)
    return sys.argv[1:]


def read_user_file(path: Path, what: str) -> str:
    """Text of a user-named file (`what`, e.g. "--token-file"). SystemExit
    when it is missing, not a file, unreadable or not UTF-8."""
    if not path.is_file():
        msg = f"error: {what} {path} does not exist or is not a file"
        raise SystemExit(msg)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        msg = f"error: {what} {path} can't be read: {e}"
        raise SystemExit(msg) from e


def check_output_path(path: Path, what: str) -> None:
    """SystemExit when output path `what` (e.g. "--output") is a directory
    or its parent doesn't exist. Call before slow work to fail fast."""
    if path.is_dir():
        msg = f"error: {what} {path} is a directory"
        raise SystemExit(msg)
    if not path.parent.is_dir():
        msg = f"error: {what} {path}: directory {path.parent} does not exist"
        raise SystemExit(msg)


@contextmanager
def network_errors(what: str) -> Generator[None]:
    """Turn a failed network request in the block (HTTP error, unreachable
    host, timeout/reset, invalid URL) into a one-line SystemExit naming
    `what` (e.g. "container registry")."""
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
