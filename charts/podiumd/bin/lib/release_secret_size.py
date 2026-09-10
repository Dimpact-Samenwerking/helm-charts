"""Estimate the size of the Helm release Secret a chart would produce.

Helm persists every release revision as a Kubernetes Secret whose payload is
base64(gzip(json.Marshal(release))) — see encodeRelease() in
helm.sh/helm/v4/pkg/storage/driver/util.go (unchanged since Helm 3). Kubernetes
hard-caps Secret/ConfigMap objects at 1 MiB; go far enough over and
`helm install`/`upgrade` fails with an apiserver "request entity too large"
(or etcd "too large") error.

Subchart trees do NOT count towards that payload: chart.Chart.dependencies is
an unexported Go field, so json.Marshal never serializes nested charts. What
DOES count is the chart's own Metadata/Values/Templates/Files, the values
override passed at install time (Config), and the fully rendered manifest
(which *does* include every subchart's rendered output, since `helm template`
concatenates everything into one string). build_release() reconstructs that
same JSON shape for the chart under test; encoded_secret_size() gzips/base64-
encodes it the same way, to flag charts approaching the limit before a real
cluster does.

This is an estimate, not a byte-exact reproduction: it doesn't split hook
resources out of the manifest into a separate `hooks` array the way a real
`helm install` does (small metadata overhead is under-counted), it doesn't
account for `Release.Info.Notes` (rendered NOTES.txt — podiumd has a root
templates/NOTES.txt, so this is a live, current under-count for it, not
just a theoretical gap; monitoring-logging has none, so it's unaffected
there) — see build_release()'s own NOTES.txt warning for why this can't
be fixed by rendering it here (confirmed: even `helm install --dry-run=
client` on Helm 3.13+ still requires a reachable cluster for this command
specifically — helm/helm#12740 — so there's no offline path to a real,
Helm-rendered NOTES.txt at all, not just a version gap) — and Python's
gzip vs Go's may differ by a small amount for the same input. Treat the
percentage as directionally accurate, not to the byte.

The JSON shape built by build_release() is a hand-reimplementation of
encodeRelease()'s Go structs (helm.sh/helm/v4/pkg/release + pkg/chart),
not generated from them — it was cross-checked once against a Go-SDK-based
reference implementation at authoring time, but nothing here re-verifies
that match automatically. If a future Helm major version changes Release/
Chart struct shape or json tags, this can silently drift out of sync with
no signal other than the reported percentage looking wrong. Re-diff against
encodeRelease() in helm.sh/helm/v4/pkg/storage/driver/util.go after any
Helm major-version bump in this repo's tooling.

Chart.yaml/values.yaml/Chart.lock are parsed with lib.chart.load_yaml
(PyYAML) rather than shelling out to a YAML-to-JSON converter (the
original standalone version of this tool used mikefarah/yq's `-o=json`,
with its own guard against this repo's OTHER, incompatible `yq`) — this
repo already trusts yaml.safe_load for these exact same files in every
other correctness-sensitive check (digest pinning, lockstep, doc-
consistency), and this is already a documented estimate with an accepted
small tolerance, so there's no reason to trust it less here.

Two callers build on this module:
  - bin/verify-helm-secret-size — the standalone CLI (any chart, arbitrary
    release name via --name, `--record` writes/updates <chart>/docs/
    release-secret-size.md). Renders its own `helm template <name>
    <chart_dir> ...` (an arbitrary name, so it can't go through render_
    chart, which is hardcoded to lib.render_scope.CHART_NAME) and reads
    its own -f/--values file, then hands the resulting manifest string
    and parsed values dict to build_release().
  - check_release_secret_size (below) — the verify-podiumd integration:
    renders via lib.render_scope.render_chart (the shared podiumd-render
    primitive, name always CHART_NAME) and reuses verify-podiumd's own
    already-computed lint_args_for(chart_dir) result (extra_args) instead
    of re-deriving a values-file path — a REAL pass/fail check, unlike
    the CLI (which only fails via its own sys.exit, never called from
    here): fails at pct >= WARN_THRESHOLD, matching the standalone
    script's own exit-1 semantics. Never writes docs/release-secret-
    size.md — only the standalone CLI's own --record does that (this
    codebase's checks are read-only; only dedicated writer scripts touch
    generated docs)."""
import base64
import datetime
import gzip
import io
import json
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import yaml

from lib.chart import load_yaml
from lib.procutil import run
from lib.render_scope import CHART_NAME, render_chart

SECRET_LIMIT = 1024 * 1024
WARN_THRESHOLD = 0.90


def b64(data):
    return base64.b64encode(data).decode()


def packaged_files(chart_dir):
    """`helm package` (no dependency update) applies .helmignore exactly the
    way `helm install`/`template` loading does — this repo's podiumd chart
    relies on that to keep docs/ci/scripts out of the release Secret (see
    charts/podiumd/.helmignore). Reading the resulting tgz, rather than
    walking the raw directory, is what makes the file set match reality."""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(["helm", "package", str(chart_dir), "-d", tmp], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"helm package failed: {result.stderr.strip()}")
        tgz_path = next(Path(tmp).glob("*.tgz"))
        out = {}
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                # strip the leading "<chartname>/" the archive wraps everything in
                rel = PurePosixPath(member.name)
                rel = PurePosixPath(*rel.parts[1:]) if len(rel.parts) > 1 else rel
                out[str(rel)] = tar.extractfile(member).read()
    return out


def check_subchart_freshness(chart_dir, metadata):
    """`helm package` (as used by packaged_files()) bundles whatever is
    already vendored under <chart_dir>/charts/ as-is — it does NOT run
    `helm dependency update` first. If Chart.yaml's declared dependency
    version was just bumped but `helm dependency update` wasn't re-run,
    the estimate silently reflects the stale, still-vendored subchart
    tree instead of the version actually being released.

    Returns a list of ready-to-print warning strings (no "WARNING: "
    prefix — each caller adds its own, printed to stderr by the
    standalone CLI or stdout by check_release_secret_size, whichever
    fits that caller's own report) — [] if nothing looks stale. Never
    prints directly itself: this is pure computation, reusable by both
    callers regardless of where they want a warning to land."""
    charts_subdir = chart_dir / "charts"
    vendored = list(charts_subdir.glob("*.tgz")) if charts_subdir.is_dir() else []
    warnings = []
    for dep in metadata.get("dependencies") or []:
        name, version = dep.get("name"), dep.get("version")
        if not name or not version:
            continue
        matches = [p for p in vendored if p.name.startswith(f"{name}-")]
        if not matches:
            continue  # not vendored locally (e.g. condition-disabled) — nothing to compare
        if not any(p.name == f"{name}-{version}.tgz" for p in matches):
            found = ", ".join(sorted(p.name for p in matches))
            warnings.append(
                f"Chart.yaml declares {name}@{version}, but the vendored charts/ directory has "
                f"{found} — run `helm dependency update` before trusting this estimate; it may be "
                "sized against a stale subchart."
            )
    return warnings


def bucket_files(paths):
    """Mirror helm's loader.LoadFiles bucketing: everything under charts/ is
    a subchart (excluded — dependencies is an unexported Go field, never
    serialized), templates/ files go to Templates, the rest to Files —
    except the specially-parsed Chart.yaml/Chart.lock/values.yaml/
    values.schema.json, which the caller handles separately."""
    special = {"Chart.yaml", "Chart.lock", "values.yaml", "values.schema.json"}
    templates, files = [], []
    for rel in sorted(paths):
        if rel.startswith("charts/") or rel in special:
            continue
        entry = {"name": rel, "data": b64(paths[rel])}
        if rel.startswith("templates/"):
            templates.append(entry)
        else:
            files.append(entry)
    return templates, files


def build_release(chart_dir, values_override, manifest, name, namespace):
    """(release, version, warnings) for the chart under test.

    values_override: an already-parsed dict (becomes Release.Config), or
    None — this function never reads a values file itself; each caller
    resolves its own override however fits (the standalone CLI's own
    -f/--values path, or check_release_secret_size's reuse of verify-
    podiumd's own already-computed lint_args_for result) and passes the
    parsed dict straight in.

    manifest: the ALREADY-rendered `helm template` output string — this
    function never shells out to render anything itself either, for the
    same reason: the standalone CLI needs an arbitrary release --name
    (lib.render_scope.render_chart is hardcoded to CHART_NAME), so each
    caller renders its own manifest however fits its own naming needs.

    warnings: every check_subchart_freshness finding, plus one more if
    this chart has a root templates/NOTES.txt (rendering it into
    Release.Info.Notes the way `helm install` does requires Go template
    evaluation this doesn't perform, so the estimate below omits it
    entirely — an under-count for that chart) — ready-to-print strings,
    no prefix, same convention as check_subchart_freshness's own return."""
    paths = packaged_files(chart_dir)
    metadata = load_yaml_bytes(paths["Chart.yaml"])
    values = load_yaml_bytes(paths["values.yaml"]) if "values.yaml" in paths else {}
    schema_b64 = b64(paths["values.schema.json"]) if "values.schema.json" in paths else None
    lock = load_yaml_bytes(paths["Chart.lock"]) if "Chart.lock" in paths else None
    templates, files = bucket_files(paths)

    warnings = list(check_subchart_freshness(chart_dir, metadata))
    if "templates/NOTES.txt" in paths:
        warnings.append(
            "this chart has a root templates/NOTES.txt, which isn't rendered into the estimate "
            "below — treat the reported size as an under-count for this chart."
        )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    release = {
        "name": name,
        "info": {
            "first_deployed": now,
            "last_deployed": now,
            "description": "Install complete",
            "status": "deployed",
            "notes": None,
        },
        "chart": {
            "metadata": metadata,
            "lock": lock,
            "templates": templates,
            "values": values,
            "schema": schema_b64,
            "schemamodtime": "0001-01-01T00:00:00Z",
            "files": files,
        },
        "manifest": manifest,
        "version": 1,
        "namespace": namespace,
    }
    if values_override is not None:
        release["config"] = values_override
    return release, metadata.get("version", "unknown"), warnings


def load_yaml_bytes(data):
    """yaml.safe_load applied to a vendored-tgz member's raw bytes (see
    packaged_files) — the same parse load_yaml itself does for a real
    file, just against bytes already read out of the tar archive rather
    than a path, so this doesn't need a temp file on disk for each one."""
    return yaml.safe_load(data.decode("utf-8")) or {}


def encoded_secret_size(release):
    """(raw_json_len, gzipped_len, encoded_len, pct) for `release` (see
    build_release) — the actual base64(gzip(json)) byte counts Helm would
    store, and encoded_len's fraction of SECRET_LIMIT."""
    raw = json.dumps(release, separators=(",", ":")).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw)
    gzipped = buf.getvalue()
    encoded = base64.b64encode(gzipped)
    size = len(encoded)
    return len(raw), len(gzipped), size, size / SECRET_LIMIT


def format_report(chart_name, version, raw_len, gzipped_len, size, pct):
    """The standard multi-line report both the standalone CLI and
    check_release_secret_size print — identical content, since it's the
    same estimate either way; only what surrounds it (report framing,
    PASS/FAIL, --record) differs per caller."""
    return (
        f"chart:          {chart_name} {version}\n"
        f"release json:   {raw_len:,} bytes\n"
        f"gzipped:        {gzipped_len:,} bytes\n"
        f"secret payload: {size:,} bytes  (estimate)\n"
        f"1 MiB limit:    {SECRET_LIMIT:,} bytes\n"
        f"used:           {pct * 100:.2f}%"
    )


def over_limit_warning(chart_name, version, size, pct):
    """The shared "approaching the 1 MiB limit" warning text (no prefix —
    same convention as check_subchart_freshness's own warnings) — printed
    by the standalone CLI (stderr, before sys.exit(1)) and by
    check_release_secret_size (stdout, as part of its own FAIL detail)
    whenever pct >= WARN_THRESHOLD."""
    return (
        f'estimated release Secret payload is at {pct * 100:.1f}% of the Kubernetes 1 MiB Secret '
        f"limit ({size:,}/{SECRET_LIMIT:,} bytes) for {chart_name} {version}. This chart is at real "
        'risk of `helm install`/`upgrade` failing with an apiserver "request entity too large" '
        "error. Investigate before releasing (trim CRDs/dashboards/values, or split the chart)."
    )


def record_result(chart_dir, chart_name, version, encoded_bytes, pct):
    """Append/update `version`'s own row in <chart_dir>/docs/release-
    secret-size.md — the standalone CLI's own --record, never called by
    check_release_secret_size (verify-podiumd's checks are read-only;
    only a dedicated writer script ever touches a generated doc, the same
    rule fix-doc-consistency/export-confluence-release-table already
    follow)."""
    doc_path = chart_dir / "docs" / "release-secret-size.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    row = f"| {version} | {encoded_bytes:,} | {pct * 100:.1f}% | {date} |"

    header = (
        f"# {chart_name} — release Secret size tracking\n\n"
        "Estimated size of the base64(gzip(json)) payload Helm stores in the\n"
        f"`sh.helm.release.v1.*` Secret for this chart, versus the Kubernetes\n"
        f"1 MiB (1,048,576 byte) Secret/ConfigMap hard limit. Generated by\n"
        "`charts/podiumd/bin/verify-helm-secret-size`; one row per released version.\n\n"
        "| Version | Encoded bytes | % of 1 MiB limit | Date |\n"
        "|---|---|---|---|\n"
    )

    if doc_path.exists():
        lines = doc_path.read_text().splitlines()
        replaced = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("|") or stripped.startswith("|---"):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if cells and cells[0] == version:
                if replaced:
                    print(
                        f"WARNING: {doc_path} already had more than one row for version {version} "
                        "before this update — leaving the extras in place, only the first match "
                        "was replaced. Clean up duplicates by hand."
                    )
                    continue
                lines[i] = row
                replaced = True
        if not replaced:
            lines.append(row)
        text = "\n".join(lines) + "\n"
    else:
        text = header + row + "\n"

    doc_path.write_text(text)
    return doc_path


def values_file_from_extra_args(extra_args):
    """The values file path lib.render_scope.lint_args_for(chart_dir)
    encodes into extra_args as ["-f", "<path>"] (or [] if it found none)
    — reused here by check_release_secret_size instead of re-deriving/
    re-checking ci/lint-values.yaml a second time (which would also
    print lint_args_for's own "no ci/lint-values.yaml found" warning a
    second time, since it was already called once in main() to build
    extra_args in the first place). None if extra_args has no "-f"."""
    if "-f" in extra_args:
        return Path(extra_args[extra_args.index("-f") + 1])
    return None


def check_release_secret_size(chart_dir, extra_args):
    """Verify-podiumd integration: renders podiumd via lib.render_scope.
    render_chart (the shared release-name-"podiumd" primitive, not a
    second inline `helm template` call), reuses `extra_args` (verify-
    podiumd's own already-computed lint_args_for(chart_dir) result) for
    both the render AND to locate podiumd's own values override (see
    values_file_from_extra_args) — never re-derives a values-file path
    itself. A REAL pass/fail check, unlike the standalone CLI's own
    report (which only ever fails via its own sys.exit, never through
    this function): fails at pct >= WARN_THRESHOLD, the exact same
    threshold the standalone script's own exit-1 uses. Never writes
    docs/release-secret-size.md (see record_result's own docstring for
    why) — --record stays exclusive to the standalone CLI."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"

    values_path = values_file_from_extra_args(extra_args)
    values_override = load_yaml(values_path) if values_path else None

    release, version, warnings = build_release(chart_dir, values_override, result.stdout, CHART_NAME, CHART_NAME)
    for warning in warnings:
        print(f"WARNING: {warning}")

    raw_len, gzipped_len, size, pct = encoded_secret_size(release)
    print(format_report(chart_dir.name, version, raw_len, gzipped_len, size, pct))

    detail = f"{size:,} bytes ({pct * 100:.1f}% of 1 MiB limit)"
    if pct >= WARN_THRESHOLD:
        print(f"WARNING: {over_limit_warning(chart_dir.name, version, size, pct)}")
        return False, detail
    return True, detail
