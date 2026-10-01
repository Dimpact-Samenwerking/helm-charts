"""The closing fix-doc-consistency run of update-component-version and update-image-version, which writes their docs."""

import sys

from pathlib import Path

from lib.cli import print_section
from lib.procutil import run_script

FIX_DOC_CONSISTENCY_SCRIPT = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


def complete_docs_and_finish() -> None:
    """Run fix-doc-consistency on the chart's docs, then print the closing
    reminder to re-render before committing."""
    print_section("Completing the docs (fix-doc-consistency)")
    run_script([sys.executable, str(FIX_DOC_CONSISTENCY_SCRIPT)])
    print()
    print("Done. Re-render the chart to confirm (verify-podiumd or /helm-render-all) before committing.")
