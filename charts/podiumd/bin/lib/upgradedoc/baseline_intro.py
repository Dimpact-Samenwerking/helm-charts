"""The upgrade doc's "environments already on **<version>**" intro sentence, which names the upgrade_docs_baseline."""

import re

from lib.version_numbers import BARE_VERSION_PATTERN

# Only the first match is the intro; later prose may name other versions on purpose.
BASELINE_INTRO_RE = re.compile(rf"(?P<prefix>environments already on \*\*)(?P<baseline>{BARE_VERSION_PATTERN})\*\*")


def fix_baseline_intro(text: str, upgrade_docs_baseline: str) -> tuple[str, bool]:
    """Point the intro sentence at upgrade_docs_baseline. Returns (new_text, changed)."""
    new_text = BASELINE_INTRO_RE.sub(lambda m: f"{m['prefix']}{upgrade_docs_baseline}**", text, count=1)
    return new_text, new_text != text


def baseline_intro_mismatches(doc_name: str, text: str, upgrade_docs_baseline: str) -> list[str]:
    """The finding for an intro sentence that names another version than upgrade_docs_baseline."""
    match = BASELINE_INTRO_RE.search(text)
    if match is None or match["baseline"] == upgrade_docs_baseline:
        return []
    return [f"{doc_name} intro names baseline **{match['baseline']}**, not **{upgrade_docs_baseline}**"]
