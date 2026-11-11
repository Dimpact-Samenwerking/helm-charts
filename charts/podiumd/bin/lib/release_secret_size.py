"""Estimate the size of the Helm release Secret a chart would produce.

Helm stores each revision as a Secret holding base64(gzip(json(release)))
(encodeRelease() in helm.sh/helm/v4/pkg/storage/driver/util.go); Kubernetes
caps Secrets at 1 MiB. Subcharts are not serialized (unexported Go field),
but their rendered output is part of the manifest, which is.

An estimate: hooks aren't split out, NOTES.txt isn't rendered (no offline way,
helm/helm#12740), and Python's gzip may differ slightly from Go's. The JSON
shape hand-mirrors Helm's Release/Chart structs; re-check it against
encodeRelease() after a Helm major-version bump.

Used by bin/verify-helm-secret-size (any chart and release name; --record
writes docs/release-secret-size.md) and by check_release_secret_size
(verify-podiumd; read-only, fails at warn_at_fraction_of_limit)."""

import base64
import datetime as dt
import gzip
import io
import json
import tarfile
import tempfile

from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

from lib.chart.chart_yaml import chart_dependency_problem
from lib.chart.chart_yaml import dependencies_problem
from lib.chart.chart_yaml import is_chart_dependency_list
from lib.chart.values_tree_primitives import text_at
from lib.checks.vendored_tgz import other_vendored_versions
from lib.procutil import run
from lib.render_scope import CHART_NAME
from lib.render_scope import render_chart
from lib.settings import release_secret_limit_bytes
from lib.settings import release_secret_warn_fraction
from lib.settings import render_report_output_file
from lib.upgradedoc.string_and_parsing_basics import table_data_cells
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlShapeError
from lib.yaml_types import load_yaml_mapping
from lib.yaml_types import parse_yaml_mapping


def b64(data: bytes) -> str:
    """`data` base64-encoded to str, as Helm stores file contents."""
    return base64.b64encode(data).decode()


def packaged_files(chart_dir: Path) -> dict[str, bytes]:
    """The chart's files as `helm package` bundles them, so .helmignore applies as on install.

    render-podiumd's default output file is dropped: a local, gitignored artifact
    (~1.4 MB) that a clean release checkout never contains."""
    rendered_output_name = render_report_output_file(chart_dir)
    with tempfile.TemporaryDirectory() as tmp:
        result = run(["helm", "package", str(chart_dir), "-d", tmp], capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"helm package failed: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return _archive_files(next(Path(tmp).glob("*.tgz")), rendered_output_name)


def _archive_files(tgz_path: Path, skipped_name: str) -> dict[str, bytes]:
    """{chart-relative path: content} of every regular file in a packaged chart, except `skipped_name`."""
    out: dict[str, bytes] = {}
    with tarfile.open(tgz_path, "r:gz") as tar:
        for member in tar.getmembers():
            rel = _chart_relative(member.name)
            extracted = tar.extractfile(member) if member.isfile() and rel != skipped_name else None
            if extracted is not None:
                out[rel] = extracted.read()
    return out


def _chart_relative(member_name: str) -> str:
    """An archive member's path without the leading "<chartname>/" the archive wraps everything in."""
    rel = PurePosixPath(member_name)
    if len(rel.parts) > 1:
        rel = PurePosixPath(*rel.parts[1:])
    return str(rel)


CHART_YAML_SOURCE = "Chart.yaml"


def check_subchart_freshness(chart_dir: Path, metadata: YamlMapping):
    """Warnings for Chart.yaml dependencies whose vendored .tgz has a different version.

    `helm package` bundles charts/ as-is, so a stale vendor skews the estimate.
    Returns unprefixed strings; callers choose where to print them."""
    deps = metadata.get("dependencies")
    if deps is not None and not is_chart_dependency_list(deps):
        problem = dependencies_problem(metadata, chart_dependency_problem, required=False) or "invalid dependencies"
        raise YamlShapeError(CHART_YAML_SOURCE, problem)
    warnings = [_stale_vendor_warning(chart_dir / "charts", dep["name"], dep["version"]) for dep in deps or []]
    return [warning for warning in warnings if warning is not None]


def _stale_vendor_warning(charts_dir: Path, name: str, version: str) -> str | None:
    """check_subchart_freshness' warning for one dependency, or None."""
    if not name or not version:
        return None
    others = other_vendored_versions(charts_dir, name, version)
    # Not vendored locally (e.g. condition-disabled): nothing to compare.
    if not others:
        return None
    found = ", ".join(f"{name}-{other}.tgz" for other in others)
    return (
        f"Chart.yaml declares {name}@{version}, but the vendored charts/ directory has "
        f"{found} — run `helm dependency update` before trusting this estimate; it may be "
        "sized against a stale subchart."
    )


# {"name": path, "data": base64 content} of one chart file, as Helm serializes it.
type SerializedFile = dict[str, str]


def bucket_files(paths: dict[str, bytes]) -> tuple[list[SerializedFile], list[SerializedFile]]:
    """(templates, files) as Helm's loader.LoadFiles buckets them.

    Skips charts/ (never serialized) and Chart.yaml/Chart.lock/values.yaml/
    values.schema.json, which the caller handles separately."""
    special = {"Chart.yaml", "Chart.lock", "values.yaml", "values.schema.json"}
    templates: list[SerializedFile] = []
    files: list[SerializedFile] = []
    for rel in sorted(paths):
        if rel.startswith("charts/") or rel in special:
            continue
        entry = {"name": rel, "data": b64(paths[rel])}
        if rel.startswith("templates/"):
            templates.append(entry)
        else:
            files.append(entry)
    return templates, files


def build_release(chart_dir: Path, values_override: YamlMapping | None, manifest: str, name: str, namespace: str):
    """(release, version, warnings) for the chart under test.

    values_override (parsed, becomes Release.Config, or None) and the rendered
    `manifest` come from the caller, since the CLI needs an arbitrary release
    name that render_chart doesn't support. warnings: check_subchart_freshness
    findings, plus one when a root templates/NOTES.txt makes this an under-count."""
    paths = packaged_files(chart_dir)
    metadata = load_yaml_bytes(paths["Chart.yaml"], "Chart.yaml")
    values = load_yaml_bytes(paths["values.yaml"], "values.yaml") if "values.yaml" in paths else {}
    schema_b64 = b64(paths["values.schema.json"]) if "values.schema.json" in paths else None
    lock = load_yaml_bytes(paths["Chart.lock"], "Chart.lock") if "Chart.lock" in paths else None
    templates, files = bucket_files(paths)

    warnings = list(check_subchart_freshness(chart_dir, metadata))
    if "templates/NOTES.txt" in paths:
        warnings.append(
            "this chart has a root templates/NOTES.txt, which isn't rendered into the estimate "
            "below — treat the reported size as an under-count for this chart."
        )

    now = dt.datetime.now(dt.UTC).isoformat()
    release: dict[str, object] = {
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
    return release, text_at(metadata, "version") or "unknown", warnings


def load_yaml_bytes(data: bytes, source: str) -> YamlMapping:
    """parse_yaml_mapping of a packaged member's raw bytes."""
    return parse_yaml_mapping(data.decode("utf-8"), source)


@dataclass
class SecretSizeEstimate:
    """Byte counts Helm would store for a release and their fraction of the Secret limit."""

    raw_len: int
    gzipped_len: int
    size: int
    pct: float
    secret_limit: int


def encoded_secret_size(release: dict[str, object], secret_limit: int):
    """SecretSizeEstimate for `release` against `secret_limit`."""
    raw = json.dumps(release, separators=(",", ":")).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw)
    gzipped = buf.getvalue()
    encoded = base64.b64encode(gzipped)
    size = len(encoded)
    return SecretSizeEstimate(len(raw), len(gzipped), size, size / secret_limit, secret_limit)


def format_report(chart_name: str, version: str, estimate: SecretSizeEstimate):
    """The multi-line size report both callers print."""
    return (
        f"chart:          {chart_name} {version}\n"
        f"release json:   {estimate.raw_len:,} bytes\n"
        f"gzipped:        {estimate.gzipped_len:,} bytes\n"
        f"secret payload: {estimate.size:,} bytes  (estimate)\n"
        f"1 MiB limit:    {estimate.secret_limit:,} bytes\n"
        f"used:           {estimate.pct * 100:.2f}%"
    )


def over_limit_warning(chart_name: str, version: str, estimate: SecretSizeEstimate):
    """The unprefixed "approaching the 1 MiB limit" warning text."""
    return (
        f"estimated release Secret payload is at {estimate.pct * 100:.1f}% of the Kubernetes 1 MiB "
        f"Secret limit ({estimate.size:,}/{estimate.secret_limit:,} bytes) for {chart_name} "
        f"{version}. This chart is at real risk of `helm install`/`upgrade` failing with an "
        'apiserver "request entity too large" error. Investigate before releasing (trim CRDs/'
        "dashboards/values, or split the chart)."
    )


def _doc_header(chart_name: str):
    """Header for a new release-secret-size.md; column order must match record_result's rows."""
    return (
        f"# {chart_name} — release Secret size tracking\n\n"
        "Estimated size of the base64(gzip(json)) payload Helm stores in the\n"
        f"`sh.helm.release.v1.*` Secret for this chart, versus the Kubernetes\n"
        f"1 MiB (1,048,576 byte) Secret/ConfigMap hard limit. Generated by\n"
        "`charts/podiumd/bin/verify-helm-secret-size`; one row per released version.\n\n"
        "| Version | Encoded bytes | % of 1 MiB limit | Date |\n"
        "|---|---|---|---|\n"
    )


def _merge_row(doc_path: Path, lines: list[str], version: str, row: str):
    """Replace `version`'s table row with `row`, or append it; warns when duplicates already exist."""
    replaced = False
    for index, line in enumerate(lines):
        if _row_version(line) != version:
            continue
        if replaced:
            print(
                f"WARNING: {doc_path} already had more than one row for version {version} "
                "before this update — leaving the extras in place, only the first match "
                "was replaced. Clean up duplicates by hand."
            )
            continue
        lines[index] = row
        replaced = True
    if not replaced:
        lines.append(row)
    return lines


def _row_version(line: str) -> str | None:
    """The version cell of a table data row; None for any other line."""
    cells = table_data_cells(line)
    return cells[0] if cells else None


def record_result(chart_dir: Path, chart_name: str, version: str, encoded_bytes: int, pct: float):
    """Add or update `version`'s row in <chart_dir>/docs/release-secret-size.md (CLI --record only)."""
    doc_path = chart_dir / "docs" / "release-secret-size.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    date = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    row = f"| {version} | {encoded_bytes:,} | {pct * 100:.1f}% | {date} |"

    if doc_path.exists():
        lines = _merge_row(doc_path, doc_path.read_text().splitlines(), version, row)
        text = "".join(f"{line}\n" for line in lines)
    else:
        text = f"{_doc_header(chart_name)}{row}\n"

    doc_path.write_text(text)
    return doc_path


def values_file_from_extra_args(extra_args: list[str]) -> Path | None:
    """The path after "-f" in lint_args_for's extra_args, or None.

    Reusing it avoids calling lint_args_for again and repeating its warning."""
    if "-f" in extra_args:
        return Path(extra_args[extra_args.index("-f") + 1])
    return None


def check_release_secret_size(chart_dir: Path, extra_args: list[str]):
    """verify-podiumd check: fails when the estimate reaches warn_at_fraction_of_limit.

    Renders via render_chart with `extra_args` (lint_args_for's result), which
    also locates the values override. Never writes the doc."""
    secret_limit = release_secret_limit_bytes(chart_dir)
    warn_threshold = release_secret_warn_fraction(chart_dir)

    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"

    values_path = values_file_from_extra_args(extra_args)
    values_override = load_yaml_mapping(values_path) if values_path else None

    release, version, warnings = build_release(chart_dir, values_override, result.stdout, CHART_NAME, CHART_NAME)
    for warning in warnings:
        print(f"WARNING: {warning}")

    estimate = encoded_secret_size(release, secret_limit)
    print(format_report(chart_dir.name, version, estimate))

    detail = f"{estimate.size:,} bytes ({estimate.pct * 100:.1f}% of 1 MiB limit)"
    if estimate.pct >= warn_threshold:
        print(f"WARNING: {over_limit_warning(chart_dir.name, version, estimate)}")
        return False, detail
    return True, detail
