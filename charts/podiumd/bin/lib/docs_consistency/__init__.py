"""Check Chart.yaml/values.yaml component versions against the release's upgrade docs.

Covers docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and docs/images/images-<version>.yaml;
given upgrade_docs_baseline, every component changed since it must appear in the right
doc. Uses only upgrade_docs_baseline and the side paths, never release_table_baseline.
A side path's docs are checked the same way against their own baseline, except the
images manifest, which belongs to upgrade_docs_baseline.
"""
