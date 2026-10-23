#!/usr/bin/env python3
"""Point the ZooKeeper operator hooks' image override at alpine/k8s in gemeente values (PodiumD 4.10.0).

PodiumD 4.10.0 runs the hooks of zac.solr-operator.zookeeper-operator with
docker.io/alpine/k8s 1.37.1 (pinned by digest) instead of the sub-chart's
lachlanevenson/k8s-kubectl v1.25.4. The chart sets only the tag; an
environment that overrides

  zac.solr-operator.zookeeper-operator.hooks.image.repository

with its mirror of k8s-kubectl keeps that repository and gets the new tag:
<mirror>/lachlanevenson/k8s-kubectl:1.37.1@sha256:..., which does not exist.
The hook Job then fails to pull, and the helm upgrade fails.

This script rewrites such a repository to the same registry's alpine/k8s:

  acrprodmgmt.azurecr.io/lachlanevenson/k8s-kubectl  ->  acrprodmgmt.azurecr.io/alpine/k8s
  acrprodmgmt.azurecr.io/k8s-kubectl                 ->  acrprodmgmt.azurecr.io/alpine/k8s
  lachlanevenson/k8s-kubectl (no registry)           ->  docker.io/alpine/k8s

A repository that already ends in alpine/k8s, or names another image, is left
alone. The script does not change a tag. A hooks.image.tag override with
k8s-kubectl's "v" prefix (e.g. v1.25.4) is an error: alpine/k8s has no such
tag, so the file is not written and must be fixed by hand (remove the tag, the
chart pins 1.37.1 by digest). Any other tag than 1.37.1 is reported. The registry must hold alpine/k8s:1.37.1 by digest: redis-ha's
label-master Job already uses the same image.

The file is edited line by line: only the repository value changes, so
comments, quoting and REP_..._REP placeholders stay as they are. Before
writing, the script checks that the edited file parses to exactly the original
values with only that value changed; it refuses to write a file that does not.
Running it twice is safe: the second run changes nothing.

Exit code: 1 when a file has an error, or under --check when a file needs
migrating; else 0.

Usage:
  pip install ruamel.yaml
  python3 migrate-zookeeper-hooks-image-4.10.0.py --dry-run --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-zookeeper-hooks-image-4.10.0.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-zookeeper-hooks-image-4.10.0.py path/to/podiumd.yml ...
"""

from __future__ import annotations

import argparse
import re
import sys

from migrate_common import MigrationError
from migrate_common import load_rt
from migrate_common import load_safe
from migrate_common import run

HOOKS_PATH = ("zac", "solr-operator", "zookeeper-operator", "hooks", "image")
NEW_IMAGE = "alpine/k8s"
# The version values.yaml pins (global.images.alpineK8s), digest left out.
CHART_VERSION = "1.37.1"
# <registry>/[lachlanevenson/]k8s-kubectl, the registry part optional.
OLD_REPO = re.compile(r"^(?P<registry>(?:[^/]+/)*?)(?:lachlanevenson/)?k8s-kubectl$")


def new_repository(repo: str) -> str | None:
    """The alpine/k8s repository for an old k8s-kubectl one, or None when nothing changes."""
    m = OLD_REPO.match(repo.strip())
    if not m:
        return None
    registry = m.group("registry")
    if not registry or registry == "docker.io/":
        return f"docker.io/{NEW_IMAGE}"
    return f"{registry}{NEW_IMAGE}"


def migrate_text(text: str, _args: argparse.Namespace | None = None) -> tuple[str, list[str]]:
    doc = load_rt(text)
    notes: list[str] = []
    node = doc
    for key in HOOKS_PATH:
        if not isinstance(node, dict) or key not in node:
            return text, notes
        node = node[key]
    if not isinstance(node, dict):
        return text, notes
    path = ".".join(HOOKS_PATH)
    tag = node.get("tag")
    if tag is not None:
        version = str(tag).split("@", 1)[0].strip()
        if version.startswith("v"):
            raise MigrationError(
                f"{path}.tag is {tag!r}, a k8s-kubectl tag that alpine/k8s does not have; "
                f"remove it (the chart pins {CHART_VERSION}) and run again; nothing written"
            )
        if version != CHART_VERSION:
            notes.append(f"CHECK {path}.tag is set ({tag!r}): it must be the chart's {CHART_VERSION} pin, or be removed")
    repo = node.get("repository")
    if not isinstance(repo, str):
        return text, notes
    new = new_repository(repo)
    if new is None:
        return text, notes

    line, col = node.lc.value("repository")
    lines = text.split("\n")
    old_line = lines[line]
    # The value starts at col; keep its quoting.
    value_text = old_line[col:]
    quote = value_text[:1] if value_text[:1] in "'\"" else ""
    if not value_text.startswith(f"{quote}{repo}{quote}"):
        raise MigrationError(
            f"{path}.repository: unexpected value layout on line {line + 1}; nothing written"
        )
    lines[line] = (
        old_line[:col]
        + f"{quote}{new}{quote}"
        + value_text[len(repo) + 2 * len(quote) :]
    )
    out = "\n".join(lines)

    want = load_safe(text)
    target = want
    for key in HOOKS_PATH:
        target = target[key]
    target["repository"] = new
    if load_safe(out) != want:
        raise MigrationError(
            "self-check failed: the edited file does not match the intended values; nothing written"
        )
    notes.append(f"{path}.repository: {repo} -> {new}")
    return out, notes


if __name__ == "__main__":
    sys.exit(run(__doc__, migrate_text))
