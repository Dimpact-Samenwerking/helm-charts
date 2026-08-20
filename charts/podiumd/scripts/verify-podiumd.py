#!/usr/bin/env python3
"""
Verifies the podiumd chart:
  1. values.yaml is valid UTF-8 with no BOM (a BOM breaks YAML tooling if present)
  2. all Chart.yaml dependencies actually resolve and bundle (helm dependency update)
  3. values.yaml has no duplicate keys silently overwriting earlier values
  4. every digest-pinned image in values.yaml still matches its live
     upstream registry digest
  5. component versions in Chart.yaml + values.yaml match the matching
     docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and docs/images/images-<version>.yaml
     (any component the doc lists, not a hardcoded set) — and, given --baseline,
     every component that actually changed vs the baseline (chart version,
     app/image tag, added, or removed) has a row in that upgrade.md, a
     mention in the matching values-deltas.md, and — if its image tag
     changed — an entry in images-<version>.yaml, even if no doc mentions
     it yet
  6. the chart lints cleanly with the CI placeholder values
  7. the chart renders cleanly with `helm template` using the CI placeholder values

Stops at the first failing step and prints a PASS/FAIL summary table, mirroring
the /helm-precommit workflow (BOM check, dupe check, lint, full render) plus
this script's own dependency-resolution, image-digest, and docs-consistency checks.

Always verifies charts/podiumd next to this script — there is no way to point
it at a different chart source.

Usage:
    verify-podiumd.py
    verify-podiumd.py --baseline 4.8.5
        # also check the doc's SOURCE (left-hand) versions for each changed
        # component against the actual baseline release — resolved to the
        # `podiumd-4.8.5` tag, falling back to the `feature/podiumd-4.8.5` /
        # `origin/feature/podiumd-4.8.5` branch if the tag doesn't exist yet.
        # Pass an explicit git ref instead of a bare version to use it as-is.

Exit code is non-zero if any check fails — safe to use as a CI gate.
"""
import argparse
import re
import shutil
import sys
import tempfile
import urllib.error
from collections import Counter
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.procutil import run
from lib.registry import parse_repo, registry_tag_exists
from lib.upgradedoc import (
    actual_app_version, compute_changed_components, diff_keys, extract_mentioned_dependency_keys,
    extract_source_version, extract_target_version, find_image_tag_paths, find_preceding_comment,
    flatten_leaf_keys, image_tag, match_dependency, normalize_name, normalize_version, pair_renames,
    parse_changes_block, resolve_entry_path, words_of,
)
from lib.upgradedoc import parse_upgrade_doc_rows as _parse_upgrade_doc_rows

DEFAULT_CHART_DIR = SCRIPT_DIR.parent
CHART_NAME = "podiumd"

# One "tag: <version>@sha256:<digest>" pin per match, quoted or bare.
DIGEST_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*"?(?P<version>[\w][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "repository:" key.
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
# A commented-out "#repository: <value>" key, left as a hint for components
# whose real repository is overridden at the gemeente/deployment level.
COMMENTED_REPO_RE = re.compile(
    r'^\s*#\s*repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*$'
)
# A one-line "# host/repo:tag[@sha256:...]" reference comment, placed above
# the "image:" block for the same override components. Tolerates a stray
# "@" right after the colon, seen on one existing comment in values.yaml.
REF_COMMENT_RE = re.compile(
    r'^\s*#\s*(?P<repo>[a-zA-Z0-9][\w.\-]*(?:/[\w.\-]+)*):@?[\w][\w.\-]*(?:@sha256:[0-9a-f]{64})?\s*$'
)

# name -> repo URL, for every Chart.yaml dependency that uses a named/alias
# repository (not a plain https:// URL and not an oci:// registry — those
# don't need `helm repo add`).
REQUIRED_REPOS = {
    "adfinis": "https://charts.adfinis.com",
    "wiremind": "https://wiremind.github.io/wiremind-helm-charts",
    "dimpact": "https://Dimpact-Samenwerking.github.io/helm-charts/",
    "maykinmedia": "https://maykinmedia.github.io/charts/",
    "kiss-elastic": "https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic",
    "zac": "https://infonl.github.io/dimpact-zaakafhandelcomponent/",
    "zgw-office-addin": "https://infonl.github.io/zgw-office-addin",
    "worth-nl": "https://worth-nl.github.io/helm-charts",
    "opstree": "https://ot-container-kit.github.io/helm-charts/",
}

TOP_N_TEMPLATES = 5


def log(title):
    print(f"\n=== {title} ===")


def die(message):
    """Hard-stop for setup/precondition failures that happen before any
    checklist step begins (not part of the PASS/FAIL summary)."""
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def require_helm():
    if shutil.which("helm") is None:
        die("helm is not installed")


def resolve_chart_dir():
    chart_dir = DEFAULT_CHART_DIR.resolve()
    if not (chart_dir / "Chart.yaml").is_file():
        die(f"{chart_dir} does not contain a Chart.yaml")
    return chart_dir


def check_utf8_format(chart_dir):
    values_path = chart_dir / "values.yaml"
    data = values_path.read_bytes()
    if data[:3] == b"\xef\xbb\xbf":
        return False, "BOM found — run strip-utf8-bom.py to fix (this script never writes to values.yaml)"
    print(f"OK: no BOM in {values_path.name}")
    return True, "no BOM"


def ensure_repos_configured():
    for name, url in REQUIRED_REPOS.items():
        result = run(["helm", "repo", "add", name, url, "--force-update"],
                      capture_output=True, text=True)
        if result.returncode != 0:
            die(f"helm repo add {name} failed\n{result.stderr.strip()}")
    result = run(["helm", "repo", "update"], capture_output=True, text=True)
    if result.returncode != 0:
        die(f"helm repo update failed\n{result.stderr.strip()}")


def check_dependencies(chart_dir):
    shutil.rmtree(chart_dir / "charts", ignore_errors=True)
    (chart_dir / "Chart.lock").unlink(missing_ok=True)
    result = run(["helm", "dependency", "update", str(chart_dir)])
    if result.returncode != 0:
        return False, "helm dependency update failed"

    result = run(["helm", "dependency", "list", str(chart_dir)], capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"helm dependency list failed: {result.stderr.strip()}"
    print(result.stdout, end="")

    rows = [line for line in result.stdout.splitlines()[1:] if line.strip()]
    bad_rows = [line for line in rows if line.split()[-1] != "ok"]
    if bad_rows:
        return False, "one or more dependencies did not resolve (STATUS != ok above)"

    dep_count = len(rows)
    chart_count = len(list((chart_dir / "charts").glob("*.tgz")))
    if dep_count != chart_count:
        return False, f"expected {dep_count} bundled dependencies, found {chart_count} in charts/"
    detail = f"{dep_count} dependencies bundled"
    print(f"OK: all {detail} in charts/")
    return True, detail


def check_duplicate_keys(chart_dir):
    """Scan values.yaml for duplicate keys that would silently overwrite an
    earlier value. Each YAML sequence item gets its own scope (tagged by the
    line its "-" appears on) so that unrelated list items sharing a key name
    (e.g. every item in a list having its own "value:" or "mountPath:") are
    never treated as duplicates of each other."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines(keepends=True)

    stack = []
    scope_keys = {}
    duplicates = []
    key_re = re.compile(r"^(\s*)([a-zA-Z0-9_\-][^:#\n]*?)\s*:")
    dash_re = re.compile(r"^(\s*)-\s*(.*)$")

    def register(scope_id, key, line_no):
        scope_keys.setdefault(scope_id, {})
        if key in scope_keys[scope_id]:
            parent = " > ".join(scope_id) if scope_id else "(root)"
            duplicates.append(
                f'Line {line_no}: duplicate "{key}" under [{parent}] (first line {scope_keys[scope_id][key]})'
            )
        else:
            scope_keys[scope_id][key] = line_no

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        if stripped.startswith("-"):
            dash_m = dash_re.match(line)
            list_indent = len(dash_m.group(1))
            rest = dash_m.group(2)
            while stack and stack[-1][0] >= list_indent:
                stack.pop()
            # unique per occurrence, so sibling list items never share a scope
            stack.append((list_indent, f"<item:{i}>"))

            km = key_re.match(rest)
            if km:
                key = km.group(2).strip()
                scope_id = tuple(k for _, k in stack)
                register(scope_id, key, i)
                stack.append((list_indent + 2, key))
            continue

        m = key_re.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        key = m.group(2).strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        scope_id = tuple(k for _, k in stack)
        register(scope_id, key, i)
        stack.append((indent, key))

    if duplicates:
        print(f"FOUND {len(duplicates)} duplicate(s):")
        for d in duplicates:
            print(" ", d)
        return False, f"{len(duplicates)} duplicate(s) found"
    print(f"OK: no duplicate keys in {values_path.name}")
    return True, "0 duplicates"


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse_upgrade_doc_rows(doc_path):
    return _parse_upgrade_doc_rows(doc_path.read_text(encoding="utf-8"))


def resolve_pin_repo(lines, tag_line_index, tag_indent):
    """Resolve the upstream repository for a "tag:" pin at tag_line_index.
    Most pins have an active sibling "repository:" key. A minority of
    components (e.g. office_converter, opa, solr-operator) deliberately
    comment their "repository:" out so gemeente-level ACR-mirror overrides
    take precedence — for those, fall back to the "# host/repo:tag" style
    reference comment placed above the "image:" block, or a commented-out
    "#repository: <value>" key at the same indent."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = ACTIVE_REPO_RE.match(raw)
        if m and indent == tag_indent:
            return m.group("repo")
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = REF_COMMENT_RE.match(lines[i])
        if m:
            return m.group("repo")
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = COMMENTED_REPO_RE.match(lines[i])
        if m:
            return m.group("repo")
    return None


def scan_digest_pins(lines):
    """Yield one record per "tag: <version>@sha256:<digest>" pin in
    values.yaml, with its resolved upstream repository. A single image (e.g.
    nginx-unprivileged) is typically pinned many times across the file."""
    pins = []
    for i, raw in enumerate(lines):
        m = DIGEST_PIN_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        pins.append({
            "line": i + 1,
            "version": m.group("version"),
            "digest": m.group("digest"),
            "repository": resolve_pin_repo(lines, i, indent),
        })
    return pins


def check_image_digests(chart_dir):
    """Report-only: verify every digest-pinned image in values.yaml against
    its live upstream registry digest, to catch pins that are stale (tag
    unchanged, but upstream re-published it with new base/security layers).
    One network request per unique (repository, version) pair. Never writes
    to values.yaml — use set-image-digests.py to fix confirmed-stale pins."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(lines)

    unresolved = [p for p in pins if not p["repository"]]
    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), []).append(p)

    print(f"Found {len(pins)} digest-pinned image(s), {len(targets)} unique image:tag to check "
          f"({len(unresolved)} unresolved, skipped)")

    matched = 0
    mismatches = []
    fetch_errors = []

    for (repository, version), group in sorted(targets.items()):
        host, repo_path = parse_repo(repository)
        pinned_digest = group[0]["digest"]
        lines_str = ", ".join(str(p["line"]) for p in group)

        digest, error = None, None
        for _attempt in range(2):
            try:
                exists, digest = registry_tag_exists(host, repo_path, version)
                error = None if exists else "tag not found upstream"
                break
            except (urllib.error.URLError, OSError) as e:
                error = str(e)

        if error:
            fetch_errors.append((repository, version, error, lines_str))
            print(f"  [FETCH-ERR] {host}/{repo_path}:{version}  {error}  (lines {lines_str})")
        elif digest and digest != f"sha256:{pinned_digest}":
            mismatches.append((repository, version, pinned_digest, digest, lines_str))
            print(f"  [MISMATCH ] {host}/{repo_path}:{version}")
            print(f"      pinned:   sha256:{pinned_digest}")
            print(f"      upstream: {digest}")
            print(f"      lines:    {lines_str}")
        else:
            matched += 1

    print()
    if unresolved:
        print(f"{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
        for p in unresolved:
            print(f"  line {p['line']}: {p['version']}")
        print()

    if mismatches:
        print(f"Run set-image-digests.py to refresh the {len(mismatches)} stale digest(s) above.")

    detail = f"{matched}/{len(targets)} matched, {len(mismatches)} stale, {len(fetch_errors)} fetch error(s)"
    if mismatches or fetch_errors:
        return False, detail
    return True, detail


def check_doc_title(doc_path, baseline, podiumd_version):
    """Verify a doc's first line states the "<baseline> → <podiumd_version>"
    pair — catches a doc that was renamed without updating its own heading."""
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    first_line = lines[0] if lines else ""
    if not re.search(rf"{re.escape(baseline)}\s*(?:→|->)\s*{re.escape(podiumd_version)}", first_line):
        return [f'{doc_path.name} title line "{first_line}" does not read '
                f'"{baseline} → {podiumd_version}"']
    return []


def check_companion_doc(doc_dir, baseline, podiumd_version, suffix):
    """When a bare-version baseline is given, verify the matching
    <baseline>-to-<podiumd_version>-<suffix>.md exists and its title line
    states the same "<baseline> → <podiumd_version>" pair."""
    name = f"{baseline}-to-{podiumd_version}-{suffix}.md"
    doc_path = doc_dir / name
    if not doc_path.is_file():
        return name, [f'expected "{name}" does not exist']
    return name, check_doc_title(doc_path, baseline, podiumd_version)


def check_markdown_format(doc_path):
    """Minimal sanity check that a doc is well-formed markdown, before trying
    to parse anything out of it: non-empty, opens with a level-1 heading, and
    any fenced code blocks are balanced (an unclosed ``` silently swallows
    the rest of the file when rendered)."""
    text = doc_path.read_text(encoding="utf-8")
    if not text.strip():
        return ["file is empty"]

    issues = []
    first_line = text.splitlines()[0]
    if not first_line.startswith("# "):
        issues.append(f'first line "{first_line}" is not a level-1 heading ("# ...")')

    fence_count = len(re.findall(r"^```", text, re.MULTILINE))
    if fence_count % 2 != 0:
        issues.append(f"{fence_count} fenced code block markers (```) — unbalanced")

    return issues


def check_baseline_doc_set(doc_dir, baseline, podiumd_version):
    """Existence + markdown-format precheck for all three baseline docs,
    run BEFORE any content-based check on them — a doc that's missing or
    malformed makes every downstream check on it meaningless."""
    issues = []
    for suffix in ("upgrade", "gemeente-specific", "values-deltas"):
        name = f"{baseline}-to-{podiumd_version}-{suffix}.md"
        doc_path = doc_dir / name
        if not doc_path.is_file():
            issues.append(f'expected "{name}" does not exist')
            continue
        issues.extend(f"{name}: {issue}" for issue in check_markdown_format(doc_path))
    return issues


SIBLING_DOC_RE = re.compile(
    r"(\d+\.\d+\.\d+)-to-(\d+\.\d+\.\d+)-(upgrade|gemeente-specific|values-deltas)\.md")
IMAGES_REF_RE = re.compile(r"images-(\d+\.\d+\.\d+)\.yaml")


def check_pointer_consistency(doc_path, baseline, podiumd_version, doc_dir, images_dir):
    """Every reference to a sibling <X>-to-<Y>-*.md doc or an images-<Z>.yaml
    manifest found anywhere in this doc — comment, prose, or markdown link.
    A reference whose target release (Y or Z) isn't podiumd_version is about
    some other historical hop and is left alone; one that targets the current
    release must have the current baseline as its source, and must actually
    exist (catches a reference left stale after a rename)."""
    text = doc_path.read_text(encoding="utf-8")
    issues = []

    for m in SIBLING_DOC_RE.finditer(text):
        from_v, to_v, suffix = m.groups()
        if normalize_version(to_v) != normalize_version(podiumd_version):
            continue
        if normalize_version(from_v) != normalize_version(baseline):
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" targets podiumd '
                           f'{podiumd_version} but its baseline is "{from_v}", expected "{baseline}"')
        elif not (doc_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    for m in IMAGES_REF_RE.finditer(text):
        version = m.group(1)
        if normalize_version(version) != normalize_version(podiumd_version):
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" targets podiumd '
                           f'{version}, expected "{podiumd_version}"')
        elif not (images_dir / m.group(0)).is_file():
            issues.append(f'{doc_path.name}: reference "{m.group(0)}" does not exist')

    return issues


def check_images_manifest_format(images_path, baseline, podiumd_version, deps, values, baseline_values):
    """Existence + YAML-validity + header-comment-accuracy precheck for the
    images manifest, run BEFORE the entry-by-entry content checks — mirrors
    check_baseline_doc_set for the three markdown docs."""
    if not images_path.is_file():
        return [f'expected "{images_path.name}" does not exist']

    text = images_path.read_text(encoding="utf-8")
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"{images_path.name} is not valid YAML: {e}"]
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return [f"{images_path.name} does not contain a YAML list of mappings"]
    for i, entry in enumerate(entries):
        missing = [k for k in ("name", "url", "version", "digest") if k not in entry]
        if missing:
            return [f'{images_path.name} entry #{i + 1} is missing key(s): {", ".join(missing)}']

    issues = []

    baseline_m = re.search(r"Baseline:\s*podiumd\s+([\w.\-]+)", text)
    if not baseline_m:
        issues.append(f'{images_path.name}: no "Baseline: podiumd <version>" line found')
    elif normalize_version(baseline_m.group(1)) != normalize_version(baseline):
        issues.append(f'{images_path.name}: baseline line says "{baseline_m.group(1)}", expected "{baseline}"')

    vs_m = re.search(r"podiumd\s+([\w.\-]+)\s+vs\s+([\w.\-]+)", text)
    if not vs_m:
        issues.append(f'{images_path.name}: no "podiumd <target> vs <baseline>" line found')
    else:
        vs_target, vs_baseline = vs_m.group(1).rstrip("."), vs_m.group(2).rstrip(".")
        if normalize_version(vs_target) != normalize_version(podiumd_version):
            issues.append(f'{images_path.name}: "... vs ..." line says target "{vs_target}", '
                           f'expected "{podiumd_version}"')
        if normalize_version(vs_baseline) != normalize_version(baseline):
            issues.append(f'{images_path.name}: "... vs ..." line says baseline "{vs_baseline}", '
                           f'expected "{baseline}"')

    for item in parse_changes_block(text):
        dep = match_dependency(item["name"], deps)
        if not dep:
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" — '
                           f'no matching Chart.yaml dependency')
            continue
        values_key = dep.get("alias", dep["name"])
        actual_app = actual_app_version(values, values_key)
        actual_chart = dep["version"]
        baseline_app = actual_app_version(baseline_values, values_key) if baseline_values else None

        if item["app"] and actual_app and normalize_version(item["app"]) != normalize_version(actual_app):
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" target app '
                           f'"{item["app"]}" != values.yaml "{actual_app}"')
        if item["chart"] and normalize_version(item["chart"]) != normalize_version(actual_chart):
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" target chart '
                           f'"{item["chart"]}" != Chart.yaml "{actual_chart}"')
        if item["app_source"] and baseline_app and \
                normalize_version(item["app_source"]) != normalize_version(baseline_app):
            issues.append(f'{images_path.name}: Changes item "{item["name"]}" source app '
                           f'"{item["app_source"]}" != baseline "{baseline_app}"')

    lines = text.splitlines()
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    current_paths = dict(find_image_tag_paths(values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}

    for entry, line_idx in zip(entries, entry_line_indices):
        comment = find_preceding_comment(lines, line_idx)
        if not comment:
            issues.append(f'{images_path.name}: entry "{entry["name"]}" has no preceding comment')
            continue

        target = extract_target_version(comment)
        if target and normalize_version(target) != normalize_version(entry["version"]):
            issues.append(f'{images_path.name}: entry "{entry["name"]}" comment says target '
                           f'"{target}", entry version is "{entry["version"]}"')

        if baseline_paths:
            path = resolve_entry_path(entry["name"], current_paths.keys())
            baseline_tag = baseline_paths.get(path) if path else None
            baseline_version = baseline_tag.split("@")[0] if baseline_tag else None
            source = extract_source_version(comment)
            if source and baseline_version and \
                    normalize_version(source) != normalize_version(baseline_version):
                issues.append(f'{images_path.name}: entry "{entry["name"]}" comment says source '
                               f'"{source}", baseline actually has "{baseline_version}"')

    return issues


def check_values_deltas_content(doc_path, changed_component_keys, baseline_values, values):
    """Verify every top-level component key that was added, removed, or
    renamed between the baseline and now is actually mentioned (backtick-
    quoted, matching the doc convention) in values-deltas.md."""
    text = doc_path.read_text(encoding="utf-8")
    backtick_spans = re.findall(r"`([^`]+)`", text)
    no_changes_claimed = bool(re.search(
        r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", text, re.IGNORECASE))

    issues = []
    all_added, all_removed, all_renamed = [], [], []
    for values_key in sorted(changed_component_keys):
        baseline_subtree = baseline_values.get(values_key, {}) if isinstance(baseline_values, dict) else {}
        current_subtree = values.get(values_key, {}) if isinstance(values, dict) else {}
        diffs = list(diff_keys(baseline_subtree, current_subtree, (values_key,)))
        added = [p for kind, p in diffs if kind == "added"]
        removed = [p for kind, p in diffs if kind == "removed"]
        renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)
        all_added.extend(added)
        all_removed.extend(removed)
        all_renamed.extend(renamed)

    def mentioned(dotted):
        return any(dotted in span or span in dotted for span in backtick_spans)

    for path in all_added:
        dotted = ".".join(path)
        if not mentioned(dotted):
            issues.append(f'{doc_path.name}: key "{dotted}" was added but is not mentioned '
                           f'(backtick-quoted) anywhere in the doc')
    for path in all_removed:
        dotted = ".".join(path)
        if not mentioned(dotted):
            issues.append(f'{doc_path.name}: key "{dotted}" was removed but is not mentioned '
                           f'(backtick-quoted) anywhere in the doc')
    for old_path, new_path in all_renamed:
        old_dotted, new_dotted = ".".join(old_path), ".".join(new_path)
        if not (mentioned(old_dotted) and mentioned(new_dotted)):
            issues.append(f'{doc_path.name}: key "{old_dotted}" appears renamed to "{new_dotted}" '
                           f'but this rename is not mentioned (backtick-quoted, both sides) in the doc')

    if issues and no_changes_claimed:
        issues.insert(0, f'{doc_path.name}: claims "No gemeente podiumd.yml changes are required" '
                          f'but {len(issues)} key change(s) were found — see below')
    return issues


def check_docs_consistency(chart_dir, baseline=None):
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    podiumd_version = str(chart_yaml["version"])
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}

    mismatches = []
    checked = []
    changed_component_keys = set()

    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    is_bare_version = bool(baseline and re.match(r"^\d+\.\d+\.\d+", baseline))

    if is_bare_version:
        precheck_issues = check_baseline_doc_set(doc_dir, baseline, podiumd_version)
        if precheck_issues:
            print(f"FOUND {len(precheck_issues)} issue(s) with the baseline doc set "
                  f"(checked before any other check on these documents):")
            for issue in precheck_issues:
                print(" ", issue)
            return False, f"{len(precheck_issues)} baseline doc issue(s)"

        images_dir = chart_dir / "docs" / "images"
        pointer_docs = [doc_dir / f"{baseline}-to-{podiumd_version}-{suffix}.md"
                        for suffix in ("upgrade", "gemeente-specific", "values-deltas")]
        images_path_for_pointers = images_dir / f"images-{podiumd_version}.yaml"
        if images_path_for_pointers.is_file():
            pointer_docs.append(images_path_for_pointers)
        pointer_issues = [issue for doc in pointer_docs
                           for issue in check_pointer_consistency(doc, baseline, podiumd_version,
                                                                   doc_dir, images_dir)]
        if pointer_issues:
            print(f"FOUND {len(pointer_issues)} pointer issue(s) "
                  f"(checked before any other check on these documents):")
            for issue in pointer_issues:
                print(" ", issue)
            return False, f"{len(pointer_issues)} pointer issue(s)"

    if is_bare_version:
        doc_glob = f"{baseline}-to-{podiumd_version}-upgrade.md"
    else:
        doc_glob = f"*-to-{podiumd_version}-upgrade.md"
    doc_matches = sorted(doc_dir.glob(doc_glob))

    if baseline:
        if is_bare_version:
            for suffix in ("gemeente-specific", "values-deltas"):
                doc_name, doc_mismatches = check_companion_doc(doc_dir, baseline, podiumd_version, suffix)
                checked.append(doc_name)
                mismatches.extend(doc_mismatches)
        else:
            print(f'WARNING: --baseline "{baseline}" is not a bare version — cannot check '
                  f'for matching gemeente-specific / values-deltas docs')

    baseline_ref, baseline_chart_yaml, baseline_values = None, None, {}
    if baseline:
        repo_root = find_repo_root(chart_dir)
        candidates = baseline_ref_candidates(baseline)
        if not repo_root:
            mismatches.append(f'baseline "{baseline}": {chart_dir} is not inside a git repository')
        else:
            baseline_ref = resolve_git_ref(repo_root, candidates)
            if not baseline_ref:
                mismatches.append(f'baseline "{baseline}": could not resolve to a git ref '
                                   f'(tried {", ".join(candidates)})')
            else:
                rel_chart_dir = chart_dir.relative_to(repo_root)
                baseline_chart_yaml = git_show_yaml(repo_root, baseline_ref, f"{rel_chart_dir}/Chart.yaml")
                baseline_values = git_show_yaml(repo_root, baseline_ref, f"{rel_chart_dir}/values.yaml") or {}
                if baseline_chart_yaml is None:
                    mismatches.append(f'baseline "{baseline}" (ref {baseline_ref}): '
                                       f'could not read Chart.yaml at that ref')
                    baseline_ref = None

    baseline_deps = baseline_chart_yaml.get("dependencies", []) if baseline_chart_yaml else []
    # Ground truth for "did this component actually change" — independent of
    # what the docs currently say, so it also catches a component that
    # changed but was never added to any doc at all.
    actual_changed_keys = (
        compute_changed_components(deps, baseline_deps, values, baseline_values)
        if baseline_ref else set()
    )

    if not doc_matches:
        print(f"WARNING: no upgrade doc matches {doc_glob} — skipping doc check")
    else:
        if len(doc_matches) > 1:
            print(f"WARNING: multiple upgrade docs match {doc_glob}: "
                  f"{', '.join(p.name for p in doc_matches)} — using {doc_matches[-1].name}")
        doc_path = doc_matches[-1]
        checked.append(doc_path.name)
        if is_bare_version:
            mismatches.extend(check_doc_title(doc_path, baseline, podiumd_version))
        if baseline_ref:
            checked.append(f"baseline {baseline_ref}")

        for row in parse_upgrade_doc_rows(doc_path):
            dep = match_dependency(row["name"], deps)
            if not dep:
                print(f'  (doc row "{row["name"]}" — no matching Chart.yaml dependency, skipped)')
                continue
            values_key = dep.get("alias", dep["name"])
            changed_component_keys.add(values_key)
            actual_chart = dep["version"]
            actual_app = actual_app_version(values, values_key)

            if row["chart"] and normalize_version(row["chart"]) != normalize_version(actual_chart):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") target chart: Chart.yaml has "{actual_chart}", '
                    f'{doc_path.name} says "{row["chart"]}"'
                )
            if row["app"] and actual_app and \
                    normalize_version(row["app"]) != normalize_version(actual_app):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") target app: values.yaml image tag is "{actual_app}", '
                    f'{doc_path.name} says "{row["app"]}"'
                )

            if not baseline_ref:
                continue
            baseline_dep = match_dependency(row["name"], baseline_deps)
            baseline_chart_actual = baseline_dep["version"] if baseline_dep else None
            baseline_app_actual = actual_app_version(baseline_values, values_key)

            if row["chart_source"] and baseline_chart_actual and \
                    normalize_version(row["chart_source"]) != normalize_version(baseline_chart_actual):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") source chart: {baseline_ref} has '
                    f'"{baseline_chart_actual}", {doc_path.name} says "{row["chart_source"]}"'
                )
            if row["app_source"] and baseline_app_actual and \
                    normalize_version(row["app_source"]) != normalize_version(baseline_app_actual):
                mismatches.append(
                    f'{values_key} ("{row["name"]}") source app: {baseline_ref} has '
                    f'"{baseline_app_actual}", {doc_path.name} says "{row["app_source"]}"'
                )

        if baseline_ref:
            for key in sorted(actual_changed_keys - changed_component_keys):
                mismatches.append(
                    f'{doc_path.name}: component "{key}" changed vs {baseline_ref} but has no row '
                    f'in the "Component versions" table'
                )

    current_paths = dict(find_image_tag_paths(values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_ref else {}

    images_path = chart_dir / "docs" / "images" / f"images-{podiumd_version}.yaml"

    if is_bare_version:
        format_issues = check_images_manifest_format(
            images_path, baseline, podiumd_version, deps, values,
            baseline_values if baseline_ref else {}
        )
        if format_issues:
            print(f"FOUND {len(format_issues)} issue(s) with the images manifest "
                  f"(checked before any other check on it):")
            for issue in format_issues:
                print(" ", issue)
            return False, f"{len(format_issues)} images-manifest issue(s)"

    if not images_path.is_file():
        print(f"WARNING: no images manifest at {images_path.name} — skipping images-manifest check")
    else:
        checked.append(images_path.name)
        covered_paths = set()
        for entry in (load_yaml(images_path) or []):
            name = entry.get("name")
            if not name:
                continue
            path = resolve_entry_path(name, current_paths.keys())
            if not path:
                print(f'  (images-manifest entry "{name}" — no matching image in values.yaml, skipped)')
                continue
            covered_paths.add(path)

            expected_tag = f'{entry["version"]}@{entry["digest"]}'
            actual_tag = current_paths[path]
            if actual_tag != expected_tag:
                mismatches.append(
                    f'{name}: values.yaml tag is "{actual_tag}", '
                    f'{images_path.name} says "{expected_tag}"'
                )

            if baseline_ref and baseline_paths.get(path) == expected_tag:
                mismatches.append(
                    f'{name}: listed in {images_path.name} as new/changed, but {baseline_ref} '
                    f'already has this exact tag ("{expected_tag}") — did it actually change?'
                )

        if baseline_ref and actual_changed_keys:
            for path, current_tag in current_paths.items():
                if path[0] not in actual_changed_keys or path in covered_paths:
                    continue
                if baseline_paths.get(path) != current_tag:
                    mismatches.append(
                        f'{"/".join(path)}: tag changed ("{baseline_paths.get(path)}" -> '
                        f'"{current_tag}") between {baseline_ref} and now, but has no entry '
                        f'in {images_path.name}'
                    )

    if baseline_ref and is_bare_version and actual_changed_keys:
        values_deltas_path = doc_dir / f"{baseline}-to-{podiumd_version}-values-deltas.md"
        mentioned_keys = extract_mentioned_dependency_keys(
            values_deltas_path.read_text(encoding="utf-8"), deps)
        for key in sorted(actual_changed_keys - mentioned_keys):
            mismatches.append(
                f'{values_deltas_path.name}: component "{key}" changed vs {baseline_ref} but is '
                f'not mentioned anywhere in the doc'
            )
        mismatches.extend(check_values_deltas_content(
            values_deltas_path, actual_changed_keys, baseline_values, values))

    if not checked:
        return True, "no matching docs found — skipped"

    if mismatches:
        print(f"FOUND {len(mismatches)} mismatch(es) vs {', '.join(checked)}:")
        for m in mismatches:
            print(" ", m)
        return False, f"{len(mismatches)} mismatch(es)"
    print(f"OK: chart versions match {', '.join(checked)}")
    return True, f"matches {', '.join(checked)}"


def lint_args_for(chart_dir):
    lint_values = chart_dir / "ci" / "lint-values.yaml"
    if lint_values.is_file():
        return ["-f", str(lint_values)]
    print("WARNING: no ci/lint-values.yaml found — linting with bare defaults only")
    return []


def check_lint(chart_dir, extra_args):
    result = run(["helm", "lint", str(chart_dir), *extra_args], capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output, end="" if output.endswith("\n") else "\n")

    error_count = len(re.findall(r"^\[ERROR\]", output, re.MULTILINE))
    warning_count = len(re.findall(r"^\[WARNING\]", output, re.MULTILINE))
    detail = f"{error_count} error(s), {warning_count} warning(s)"

    if result.returncode != 0 or error_count > 0:
        return False, detail
    return True, detail


def supports_skip_schema_validation():
    result = run(["helm", "template", "--help"], capture_output=True, text=True)
    return "--skip-schema-validation" in result.stdout


def report_largest_templates(rendered_text):
    source_re = re.compile(r"^# Source: (.+)$")
    counts = Counter()
    current = None
    for line in rendered_text.splitlines():
        m = source_re.match(line)
        if m:
            current = m.group(1)
        elif current:
            counts[current] += 1

    if not counts:
        return
    print("Largest rendered templates (by line count):")
    for path, n in counts.most_common(TOP_N_TEMPLATES):
        print(f"  {n:6d}  {path}")


def report_errors_by_subchart(error_text):
    chart_re = re.compile(r"([A-Za-z0-9_.\-]+)/templates/")
    counts = Counter(chart_re.findall(error_text))
    if not counts:
        return
    print("Errors by sub-chart:")
    for chart, n in counts.most_common():
        print(f"  {chart}: {n}")


def check_render(chart_dir, extra_args):
    template_args = list(extra_args)
    if supports_skip_schema_validation():
        template_args.append("--skip-schema-validation")
    else:
        print(
            "WARNING: this helm version does not support --skip-schema-validation "
            "(needed for the KISS sub-chart's JSON schema) — CI uses a newer helm "
            "(azure/setup-helm@v5.0.1) where this works; consider upgrading your "
            "local helm to match. Rendering without it, may fail on schema validation."
        )

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *template_args],
                 capture_output=True, text=True)

    if result.returncode != 0:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        report_errors_by_subchart(result.stdout + result.stderr)
        return False, "helm template failed to render"

    doc_count = sum(1 for line in result.stdout.splitlines() if line.startswith("---"))
    if doc_count <= 0:
        return False, "rendered 0 manifests"

    report_largest_templates(result.stdout)
    detail = f"{doc_count} manifests"
    print(f"OK: rendered {detail}")
    return True, detail


def print_summary(results, overall_ok):
    log("VERIFY SUMMARY")
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name.ljust(width)} : {status} ({detail})")
    print()
    if overall_ok:
        print("All checks passed.")
    else:
        print("One or more checks failed — see details above.")


def main():
    parser = argparse.ArgumentParser(description="Verify the podiumd chart.")
    parser.add_argument("--baseline", default=None,
                        help="baseline release to also check the upgrade doc's SOURCE versions "
                             "against — a bare version (e.g. 4.8.5) is resolved to the podiumd-4.8.5 "
                             "tag, falling back to the feature/podiumd-4.8.5 branch; anything else is "
                             "used as a literal git ref")
    args = parser.parse_args()

    require_helm()

    log("Resolving chart source")
    chart_dir = resolve_chart_dir()
    print(f"Using local chart source: {chart_dir}")

    results = []

    def run_step(name, title, func, *fargs):
        log(title)
        ok, detail = func(*fargs)
        results.append((name, ok, detail))
        if not ok:
            print_summary(results, overall_ok=False)
            sys.exit(1)

    run_step("UTF-8 format", "UTF-8 format check", check_utf8_format, chart_dir)

    log("Ensuring dependency repos are configured")
    ensure_repos_configured()

    run_step("Dependencies", "Resolving dependencies (helm dependency update)", check_dependencies, chart_dir)
    run_step("Dupe check", "Duplicate key scan", check_duplicate_keys, chart_dir)
    run_step("Image digests", "Checking image digests against upstream registries",
             check_image_digests, chart_dir)
    run_step("Docs consistency", "Checking versions against upgrade docs",
             check_docs_consistency, chart_dir, args.baseline)

    extra_args = lint_args_for(chart_dir)
    run_step("Lint", "helm lint", check_lint, chart_dir, extra_args)
    run_step("Full render", "helm template", check_render, chart_dir, extra_args)

    print_summary(results, overall_ok=True)


if __name__ == "__main__":
    main()
