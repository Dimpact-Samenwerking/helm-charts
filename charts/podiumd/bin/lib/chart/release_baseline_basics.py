"""Release-baseline basics: chart_dir/etc/release-baseline.yaml
read/write (upgrade_docs_baseline, release_table_baseline,
write_release_baselines) and the two plain YAML readers
(load_yaml/chart_version) every other lib.chart.* module shares."""

import yaml


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def chart_version(chart_yaml_path):
    return str(load_yaml(chart_yaml_path)["version"])


RELEASE_BASELINES_FILE_NAME = "etc/release-baseline.yaml"


def _release_baselines(chart_dir):
    """The parsed contents of chart_dir/etc/release-baseline.yaml — upgrade_
    docs (the incremental baseline _UPGRADE_PATHS/*.md and docs/images/
    images-<target>.yaml are written against) and release_table (the
    cumulative baseline release-table.csv was last generated against;
    see upgrade_docs_baseline/release_table_baseline below for why
    podiumd needs two baselines instead of one) — or {} if the file
    doesn't exist yet. Not a public accessor itself: callers want
    upgrade_docs_baseline/release_table_baseline below, which each read
    one specific key."""
    path = chart_dir / RELEASE_BASELINES_FILE_NAME
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def upgrade_docs_baseline(chart_dir):
    """The incremental baseline _UPGRADE_PATHS/*.md and docs/images/
    images-<target>.yaml are written against — the immediately
    preceding release, advanced on every release cycle (see
    create-podiumd-version). None if release-baseline.yaml or this key
    doesn't exist yet."""
    return _release_baselines(chart_dir).get("upgrade_docs")


def release_table_baseline(chart_dir):
    """The cumulative baseline release-table.csv (the Confluence
    release-notes export) was last generated against — advanced only on
    a minor version bump (see create-podiumd-version), left untouched by
    a patch bump. None if release-baseline.yaml or this key doesn't
    exist yet."""
    return _release_baselines(chart_dir).get("release_table")


def write_release_baselines(chart_dir, upgrade_docs=None, release_table=None):
    """Read-modify-write chart_dir/etc/release-baseline.yaml, updating only
    whichever of upgrade_docs/release_table is given (None leaves that
    key untouched, whatever it already was) — the single write path
    shared by create-podiumd-version (writes upgrade_docs on every
    release cycle, release_table only on a minor bump) and
    change-podiumd-baseline (writes upgrade_docs only, never
    release_table), so neither script risks clobbering the other's own
    key by writing a fresh two-key file from scratch.

    Creates the etc/ directory first if it doesn't exist yet — true on
    the real chart (etc/ is a permanent fixture there), but a synthetic
    test chart_dir has no reason to pre-create a directory this is the
    only thing that ever writes into.

    Each value is written double-quoted (e.g. `upgrade_docs: "4.9.1"`),
    matching this codebase's own established YAML-writing convention
    (e.g. images-<version>.yaml's own `version: "3.1.1"`) — plain
    yaml.safe_dump(data, ...) only quotes a scalar when it's ambiguous
    with another YAML type (int/float/bool/null); a version string like
    "4.9.1" (two dots, never a valid number) is never ambiguous, so it
    would otherwise come out bare. Composed key-by-key (keys stay bare,
    never quoted — only the values are) rather than dumping the whole
    dict at once, since yaml.safe_dump has no "quote every string
    scalar" option of its own to ask for directly. Each value's own
    quoted-and-escaped form comes from yaml.safe_dump(value,
    default_style='"') itself (stripped of the single trailing
    newline it always appends) — never hand-rolled string
    interpolation: a value containing a literal backslash or an
    embedded double-quote character needs YAML's own backslash-escape
    rules applied correctly (the same general idea most languages'
    double-quoted string escaping already uses), which only PyYAML's
    own scalar emitter can be trusted to get right."""
    path = chart_dir / RELEASE_BASELINES_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _release_baselines(chart_dir)
    if upgrade_docs is not None:
        data["upgrade_docs"] = upgrade_docs
    if release_table is not None:
        data["release_table"] = release_table
    lines = []
    for key, value in data.items():
        quoted_value = yaml.safe_dump(value, default_style='"').rstrip("\n")
        lines.append(f"{key}: {quoted_value}\n")
    path.write_text("".join(lines), encoding="utf-8")
