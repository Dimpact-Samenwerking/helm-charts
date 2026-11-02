#!/usr/bin/env python3
"""QA deploy statistics for the release-notes skill.

qa_deploys.py <version> <out.json> [--context CTX] [--namespace NS] [--since YYYY-MM-DD] [--until YYYY-MM-DD]

Reads the env-coordination ledger of a QA environment (ConfigMap
agent-env-ledger, key ledger.json; default context podiumd-johnb00-aks,
namespace podiumd) and counts the podiumd Helm deploys recorded in it
(kind deploy, target helm/podiumd) between --since and --until (dates of the
ledger entry, UTC, both inclusive). Writes one JSON bundle and prints a
summary. Counts only; the notes decide what to show.

- revisions: every "rev <n>" a deploy entry names; first and last revision.
- failed: revisions an entry reports as failed ("rev <n> FAILED", "rev <n>
  failed"); a retry the deploy script made is a revision of its own.
- prs: PR numbers ("#<n>") named in the deploy entries that are helm-charts
  PRs into feature/podiumd-<version> or feature/podiumd-<version>-* (checked
  with `gh pr view`), i.e. the PRs that were on QA in that period. Numbers of
  other repositories (podiumd-infra, the ZAC chart) are listed under other_refs.
- sessions: deploy entries per session (agent).

Helm itself keeps only the last 10 revisions of a release, so the ledger is
the only full record. It covers what the sessions recorded since the ledger
exists (12 October 2026 on johnb00); deploys before that are not counted.
"""

import argparse
import collections
import json
import re
import subprocess
import sys

REV = re.compile(r"\brev (\d+)\b")
FAILED_REV = re.compile(r"\brev (\d+) (?:FAILED|failed)\b")
PR = re.compile(r"#(\d{3,4})\b")


def ledger(context, namespace):
    out = subprocess.run(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "configmap",
            "agent-env-ledger",
            "-o",
            "jsonpath={.data.ledger\\.json}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode:
        sys.exit(f"cannot read the ledger: {out.stderr.strip()}")
    data = json.loads(out.stdout or "[]")
    return data.get("entries", []) if isinstance(data, dict) else data


def helm_charts_pr(number, version):
    out = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            "Dimpact-Samenwerking/helm-charts",
            "--json",
            "baseRefName",
            "-q",
            ".baseRefName",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    base = out.stdout.strip()
    return out.returncode == 0 and (
        base == f"feature/podiumd-{version}"
        or base.startswith(f"feature/podiumd-{version}-")
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version")
    ap.add_argument("out")
    ap.add_argument("--context", default="podiumd-johnb00-aks")
    ap.add_argument("--namespace", default="podiumd")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="9999-12-31")
    a = ap.parse_args()

    deploys = [
        e
        for e in ledger(a.context, a.namespace)
        if e.get("kind") == "deploy"
        and e.get("target") == "helm/podiumd"
        and a.since <= (e.get("at") or "")[:10] <= a.until
    ]
    revs, failed, prs = set(), set(), set()
    for e in deploys:
        text = e.get("summary", "")
        revs.update(int(n) for n in REV.findall(text))
        failed.update(int(n) for n in FAILED_REV.findall(text))
        prs.update(int(n) for n in PR.findall(text))
    ours = sorted(n for n in prs if helm_charts_pr(n, a.version))
    dates = sorted((e.get("at") or "")[:10] for e in deploys)
    bundle = {
        "context": a.context,
        "since": dates[0] if dates else None,
        "until": dates[-1] if dates else None,
        "deploy_entries": len(deploys),
        "first_revision": min(revs, default=None),
        "last_revision": max(revs, default=None),
        "revisions": (max(revs) - min(revs) + 1) if revs else 0,
        "failed_revisions": sorted(failed),
        "prs": ours,
        "other_refs": sorted(prs - set(ours)),
        "sessions": dict(
            collections.Counter(e.get("agent") for e in deploys).most_common()
        ),
    }
    with open(a.out, "w") as f:
        json.dump(bundle, f, indent=1)
    print(
        f"{bundle['deploy_entries']} deploy entries, {bundle['since']} to {bundle['until']}: "
        f"revisions {bundle['first_revision']}-{bundle['last_revision']} "
        f"({bundle['revisions']}), {len(failed)} failed {sorted(failed)}, {len(ours)} PRs into feature/podiumd-{a.version}"
    )


if __name__ == "__main__":
    main()
