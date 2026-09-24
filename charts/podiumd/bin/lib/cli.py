"""Argument handling for the scripts that read sys.argv directly
instead of using argparse."""

import sys


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
