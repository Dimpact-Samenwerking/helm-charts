#!/usr/bin/env python3
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
concatenates everything into one string). This script reconstructs that same
JSON shape for the chart under test and gzips/base64-encodes it the same way,
to flag charts approaching the limit before a real cluster does.

This is an estimate, not a byte-exact reproduction: it doesn't split hook
resources out of the manifest into a separate `hooks` array the way a real
`helm install` does (small metadata overhead is under-counted), and Python's
gzip vs Go's may differ by a small amount for the same input. Treat the
percentage as directionally accurate, not to the byte.

Usage:
    helm-release-secret-size.py --chart charts/podiumd -f charts/podiumd/ci/lint-values.yaml --record
    helm-release-secret-size.py --chart charts/monitoring-logging --record

Requires: helm, yq (https://github.com/mikefarah/yq) on PATH.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import gzip
import io
import json
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile

SECRET_LIMIT = 1024 * 1024
WARN_THRESHOLD = 0.90


def run_yq_json(path: pathlib.Path):
    result = subprocess.run(
        ["yq", "-o=json", str(path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"yq failed on {path}: {result.stderr.strip()}")
    text = result.stdout.strip()
    return json.loads(text) if text else {}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def packaged_files(chart_dir: pathlib.Path) -> dict[str, bytes]:
    """`helm package` (no dependency update) applies .helmignore exactly the
    way `helm install`/`template` loading does — this repo's podiumd chart
    relies on that to keep docs/ci/scripts out of the release Secret (see
    charts/podiumd/.helmignore). Reading the resulting tgz, rather than
    walking the raw directory, is what makes the file set match reality."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["helm", "package", str(chart_dir), "-d", tmp],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"helm package failed: {result.stderr.strip()}")
        tgz_path = next(pathlib.Path(tmp).glob("*.tgz"))
        out = {}
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                # strip the leading "<chartname>/" the archive wraps everything in
                rel = pathlib.PurePosixPath(member.name)
                rel = pathlib.PurePosixPath(*rel.parts[1:]) if len(rel.parts) > 1 else rel
                out[str(rel)] = tar.extractfile(member).read()
    return out


def bucket_files(paths: dict[str, bytes]):
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


def yq_json_bytes(data: bytes):
    result = subprocess.run(["yq", "-o=json", "-"], input=data, capture_output=True)
    text = result.stdout.strip()
    return json.loads(text) if text else {}


def build_release(chart_dir: pathlib.Path, values_file: pathlib.Path | None, manifest: str, name: str, namespace: str):
    paths = packaged_files(chart_dir)
    metadata = yq_json_bytes(paths["Chart.yaml"])
    values = yq_json_bytes(paths["values.yaml"]) if "values.yaml" in paths else {}
    schema_b64 = b64(paths["values.schema.json"]) if "values.schema.json" in paths else None
    lock = yq_json_bytes(paths["Chart.lock"]) if "Chart.lock" in paths else None
    templates, files = bucket_files(paths)
    config = run_yq_json(values_file) if values_file else None

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    release = {
        "name": name,
        "info": {
            "first_deployed": now,
            "last_deployed": now,
            "description": "Install complete",
            "status": "deployed",
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
    if config is not None:
        release["config"] = config
    return release, metadata.get("version", "unknown")


def record_result(chart_dir: pathlib.Path, chart_name: str, version: str, encoded_bytes: int, pct: float):
    doc_path = chart_dir / "docs" / "release-secret-size.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    row = f"| {version} | {encoded_bytes:,} | {pct * 100:.1f}% | {date} |"

    header = (
        f"# {chart_name} — release Secret size tracking\n\n"
        "Estimated size of the base64(gzip(json)) payload Helm stores in the\n"
        f"`sh.helm.release.v1.*` Secret for this chart, versus the Kubernetes\n"
        f"1 MiB (1,048,576 byte) Secret/ConfigMap hard limit. Generated by\n"
        "`scripts/helm-release-secret-size.py`; one row per released version.\n\n"
        "| Version | Encoded bytes | % of 1 MiB limit | Date |\n"
        "|---|---|---|---|\n"
    )

    if doc_path.exists():
        text = doc_path.read_text()
        pattern = re.compile(rf"^\|\s*{re.escape(version)}\s*\|.*\|$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(row, text)
        else:
            text = text.rstrip("\n") + "\n" + row + "\n"
    else:
        text = header + row + "\n"

    doc_path.write_text(text)
    return doc_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chart", required=True, help="path to the chart directory")
    parser.add_argument("-f", "--values", help="values override file, e.g. ci/lint-values.yaml (becomes Release.Config)")
    parser.add_argument("--name", help="release name for `helm template` (defaults to chart dir name)")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--record", action="store_true", help="append/update a row in <chart>/docs/release-secret-size.md")
    args = parser.parse_args()

    chart_dir = pathlib.Path(args.chart).resolve()
    name = args.name or chart_dir.name

    helm_cmd = ["helm", "template", name, str(chart_dir), "--skip-schema-validation"]
    values_path = pathlib.Path(args.values).resolve() if args.values else None
    if values_path:
        helm_cmd += ["-f", str(values_path)]

    rendered = subprocess.run(helm_cmd, capture_output=True, text=True)
    if rendered.returncode != 0:
        print(rendered.stderr, file=sys.stderr)
        sys.exit(1)

    release, version = build_release(chart_dir, values_path, rendered.stdout, name, args.namespace)

    raw = json.dumps(release, separators=(",", ":")).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw)
    encoded = base64.b64encode(buf.getvalue())

    size = len(encoded)
    pct = size / SECRET_LIMIT

    print(f"chart:          {chart_dir.name} {version}")
    print(f"release json:   {len(raw):,} bytes")
    print(f"gzipped:        {buf.tell():,} bytes")
    print(f"secret payload: {size:,} bytes  (estimate)")
    print(f"1 MiB limit:    {SECRET_LIMIT:,} bytes")
    print(f"used:           {pct * 100:.2f}%")

    if args.record:
        doc_path = record_result(chart_dir, chart_dir.name, str(version), size, pct)
        print(f"recorded:       {doc_path}")

    if pct >= WARN_THRESHOLD:
        print(
            f"\n⚠️  WARNING: estimated release Secret payload is at {pct * 100:.1f}% "
            f"of the Kubernetes 1 MiB Secret limit ({size:,}/{SECRET_LIMIT:,} bytes) for "
            f"{chart_dir.name} {version}. This chart is at real risk of `helm install`/"
            "`upgrade` failing with an apiserver \"request entity too large\" error. "
            "Investigate before releasing (trim CRDs/dashboards/values, or split the chart).",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
