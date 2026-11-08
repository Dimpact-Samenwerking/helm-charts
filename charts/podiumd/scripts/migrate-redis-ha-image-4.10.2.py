#!/usr/bin/env python3
"""Point the redis-ha image override at library/redis in gemeente values (PodiumD 4.10.2).

PodiumD 4.10.2 runs redis-ha on the official docker.io/library/redis
8.10.3-alpine (pinned by digest) instead of quay.io/opstree/redis v8.10.1. The
chart sets only the tag; an environment that overrides

  redis-operator.redis-ha.image.repository

with its mirror of opstree/redis keeps that repository and gets the new tag:
<mirror>/opstree/redis:8.10.3-alpine@sha256:..., which does not exist. The
redis-ha pods then fail to pull.

This script rewrites such a repository to the same registry's library/redis:

  opstree/redis (registry in a registry: key)     ->  library/redis
  acrprodmgmt.azurecr.io/opstree/redis            ->  acrprodmgmt.azurecr.io/library/redis
  quay.io/opstree/redis                           ->  docker.io/library/redis
  redis (only with a registry: key)               ->  library/redis

The last form is an ACR mirror of opstree/redis under the flat name "redis"
(gene accp, dim1 accp, dim2 ontw, dim3 ontw). Without a registry: key, "redis"
already means Docker Hub's library/redis and is left alone.

A repository that already ends in library/redis, or names another image, is
left alone. The script does not change a tag. A redis-ha.image.tag override
with opstree's "v" prefix (e.g. v8.10.1) is an error: library/redis has no
such tag, so the file is not written and must be fixed by hand (remove the tag,
the chart pins 8.10.3-alpine by digest). Any other tag than 8.10.3-alpine is
reported. The registry must hold library/redis:8.10.3-alpine by digest.

The file is edited line by line: only the repository value changes, so
comments, quoting and REP_..._REP placeholders stay as they are. Before
writing, the script checks that the edited file parses to exactly the original
values with only that value changed; it refuses to write a file that does not.
Running it twice is safe: the second run changes nothing.

Exit code: 1 when a file has an error, or under --check when a file needs
migrating; else 0.

Usage:
  pip install ruamel.yaml
  python3 migrate-redis-ha-image-4.10.2.py --dry-run --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-redis-ha-image-4.10.2.py --gemeenten-dir <SSCHostingSync>/applications/gemeenten
  python3 migrate-redis-ha-image-4.10.2.py path/to/podiumd.yml ...
"""

from __future__ import annotations

import argparse
import re
import sys

from migrate_common import migrate_image_repository
from migrate_common import run

IMAGE_PATH = ("redis-operator", "redis-ha", "image")
NEW_IMAGE = "library/redis"
# The version values.yaml pins (redis-operator.redis-ha.image), digest left out.
CHART_VERSION = "8.10.3-alpine"
# [<registry>/]opstree/redis
OLD_REPO = re.compile(r"^(?P<registry>(?:[^/]+/)*?)opstree/redis$")


def new_repository(repo: str, image: dict) -> str | None:
    """The library/redis repository for an old opstree/redis one, or None when nothing changes."""
    if repo.strip() == "redis" and image.get("registry"):
        return NEW_IMAGE
    m = OLD_REPO.match(repo.strip())
    if not m:
        return None
    registry = m.group("registry")
    # quay.io holds no library/redis; Docker Hub does.
    if registry == "quay.io/":
        return f"docker.io/{NEW_IMAGE}"
    return f"{registry}{NEW_IMAGE}"


def migrate_text(text: str, _args: argparse.Namespace | None = None) -> tuple[str, list[str]]:
    return migrate_image_repository(text, IMAGE_PATH, new_repository, "opstree/redis", NEW_IMAGE, CHART_VERSION)


if __name__ == "__main__":
    sys.exit(run(__doc__, migrate_text))
