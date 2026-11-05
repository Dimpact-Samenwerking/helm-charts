#!/usr/bin/env python3
"""Git metrics of the repositories around a PodiumD release, for the release-notes skill.

repo_metrics.py <version> <out.json> [--baseline B] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                [--clones-dir DIR] [--tests-results DIR] [--context CTX] [--namespace NS]

The work for a release is not only in helm-charts. This script counts, for the
same period, the work in the repositories around it:

| key | repository | visibility | extra |
| --- | --- | --- | --- |
| podiumd-tests | infonl/podiumd-tests | public | tests added and removed, test runs per chart version |
| podiumd-minikube | infonl/podiumd-minikube | public | - |
| known-issues | infonl/podiumd-known-issues | private | reports added, issues per state in the index |
| qa-infra | ICATT-Menselijk-Digitaal/podiumd-infra | private | - |
| review-tooling | infonl/podiumd-local-review | private | local-LLM reviews of release PRs (review ledger) |

Per repository: commits (no merges) on all branches of origin, each counted
once, so work on feature branches that is not merged yet counts too (the QA
infrastructure works on long-lived branches); authors; lines added and
deleted; merged PRs (from the commit subjects: "Merge pull request #N" or
"... (#N)"). The test and report counts use the default branch.

Period: from the date of the tag podiumd-<baseline> (baseline from
charts/podiumd/etc/release-baseline.yaml, or --baseline) to the date of the tag
podiumd-<version>, or today while the release is not tagged. --since/--until
override both (dates, UTC, inclusive).

Clones: <clones-dir>/<repo name> (default ~/IdeaProjects) when it exists and
has the remote; otherwise a blobless clone in a temporary directory. Every
clone is fetched first; nothing is pushed or changed.

Test runs: podiumd-tests writes results/<YYYY-MM>/<run>/run.json locally and
does not commit them, so only the runs on this machine are counted (the
machine of the testing session). --tests-results points at another copy.

Visibility matters for the notes, which are public: the private repositories
are described by role (the internal known-issues overview, the QA
infrastructure, the review tooling) and only with counts. This script writes
the keys above, never a private repository's name, into the "notes" fields.
"""

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

REPOS = [
    # key, slug, public, role for the notes (Dutch)
    ("podiumd-tests", "infonl/podiumd-tests", True, "podiumd-tests (testset)"),
    ("podiumd-minikube", "infonl/podiumd-minikube", True, "podiumd-minikube (lokale testomgeving)"),
    ("known-issues", "infonl/podiumd-known-issues", False, "het interne overzicht van bekende problemen"),
    ("qa-infra", "ICATT-Menselijk-Digitaal/podiumd-infra", False, "de QA-infrastructuur"),
    ("review-tooling", "infonl/podiumd-local-review", False, "de reviewtooling (lokale LLM-reviews)"),
]
PR_SUBJECT = re.compile(r"Merge pull request #(\d+)|\(#(\d+)\)\s*$")
TEST_DEF = re.compile(r"^[+-]\s*(?:async\s+)?def test_\w+", re.M)


def run(args, cwd=None, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"{' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def tag_date(tag):
    """Date of a helm-charts tag (from GitHub), or None when it does not exist."""
    p = subprocess.run(["gh", "api", f"repos/Dimpact-Samenwerking/helm-charts/commits/{tag}",
                        "--jq", ".commit.committer.date"], capture_output=True, text=True)
    return p.stdout.strip()[:10] if p.returncode == 0 and p.stdout.strip() else None


def baseline_version():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "..", "charts", "podiumd", "etc", "release-baseline.yaml")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r"^\s*upgrade_docs:\s*\"?([\d.]+)", text, re.M)
    return m and m[1]


def clone(slug, clones_dir, tmp):
    name = slug.split("/")[1]
    path = os.path.join(clones_dir, name)
    if os.path.isdir(os.path.join(path, ".git")):
        remotes = run(["git", "remote", "-v"], cwd=path, check=False)
        if slug.lower() in remotes.lower():
            run(["git", "fetch", "-q", "origin"], cwd=path)
            return path
    path = os.path.join(tmp, name)
    run(["gh", "repo", "clone", slug, path, "--", "-q", "--filter=blob:none"])
    return path


def default_ref(path):
    out = run(["git", "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], cwd=path, check=False).strip()
    return out or "origin/main"


def git_metrics(path, ref, since, until):
    window = [f"--since={since}T00:00:00Z", f"--until={until}T23:59:59Z"]
    commits, authors, prs, added, deleted = 0, set(), set(), 0, 0
    log = run(["git", "log", ref, *window, "--no-merges", "--format=%x00%H%x09%an%x09%s", "--numstat"], cwd=path)
    for block in log.split("\x00")[1:]:
        head, _, stats = block.partition("\n")
        _, author, subject = head.split("\t", 2)
        commits += 1
        authors.add(author)
        for m in PR_SUBJECT.finditer(subject):
            prs.add(int(m[1] or m[2]))
        for line in stats.splitlines():
            a, d, *_ = line.split("\t") + ["", ""]
            if a.isdigit() and d.isdigit():
                added, deleted = added + int(a), deleted + int(d)
    merges = run(["git", "log", ref, *window, "--merges", "--format=%s"], cwd=path)
    for subject in merges.splitlines():
        for m in PR_SUBJECT.finditer(subject):
            prs.add(int(m[1] or m[2]))
    return {"commits": commits, "authors": len(authors), "merged_prs": len(prs),
            "lines_added": added, "lines_deleted": deleted}


def window_base(path, ref, since):
    """The last commit before the period, or the root when there is none."""
    base = run(["git", "rev-list", "-1", f"--before={since}T00:00:00Z", ref], cwd=path).strip()
    return base or run(["git", "rev-list", "--max-parents=0", ref], cwd=path).split()[0]


def window_head(path, ref, until):
    return run(["git", "rev-list", "-1", f"--before={until}T23:59:59Z", ref], cwd=path).strip()


def tests_added(path, ref, since, until):
    head = window_head(path, ref, until)
    if not head:  # the repository has no commit yet at the end of the period
        return {"test_functions_added": 0, "test_functions_removed": 0, "test_files_added": 0}
    base = window_base(path, ref, since)
    diff = run(["git", "diff", base, head, "--", "tests", "unit_tests"], cwd=path)
    plus = sum(1 for m in TEST_DEF.finditer(diff) if m[0].startswith("+"))
    minus = sum(1 for m in TEST_DEF.finditer(diff) if m[0].startswith("-"))
    files = run(["git", "diff", "--diff-filter=A", "--name-only", base, head, "--", "tests"], cwd=path)
    return {"test_functions_added": plus, "test_functions_removed": minus,
            "test_files_added": len([f for f in files.splitlines() if f.endswith(".py")])}


def test_runs(results_dir, version, since, until):
    runs, tiers, envs = 0, collections.Counter(), collections.Counter()
    totals = collections.Counter()
    for path in glob.glob(os.path.join(results_dir, "*", "*", "run.json")):
        try:
            r = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        day = str(r.get("started", ""))[:10]
        if str(r.get("chart_version")) != version or not since <= day <= until:
            continue
        runs += 1
        tiers[r.get("tier") or "?"] += 1
        envs[r.get("env") or "?"] += 1
        for k, v in (r.get("counts") or {}).items():
            if isinstance(v, int):
                totals[k] += v
    return {"runs": runs, "by_tier": dict(tiers), "by_env": dict(envs), "test_results": dict(totals)}


def known_issue_counts(path, ref, since, until):
    head = window_head(path, ref, until)
    if not head:  # the repository has no commit yet at the end of the period
        return {"reports_added": 0, "issues_per_state": {}}
    base = window_base(path, ref, since)
    added = run(["git", "diff", "--diff-filter=A", "--name-only", base, head, "--", "issues"], cwd=path)
    readme = run(["git", "show", f"{head}:README.md"], cwd=path, check=False)
    states = {}
    for m in re.finditer(r"^\| \[([^\]]+)\]\(#[^)]+\) \|.*\| (\d+) \|$", readme, re.M):
        states[m[1]] = int(m[2])
    return {"reports_added": len([f for f in added.splitlines() if f.endswith(".md")]), "issues_per_state": states}


def review_ledger(context, namespace, since, until):
    p = subprocess.run(["kubectl", "--context", context, "-n", namespace, "get", "configmap",
                        "agent-review-ledger", "-o", "jsonpath={.data.ledger\\.json}"],
                       capture_output=True, text=True)
    if p.returncode:
        return {"error": p.stderr.strip()[:200]}
    jobs = json.loads(p.stdout or "{}").get("jobs", {})
    reviewed, minutes, posted, prs = 0, 0.0, 0, set()
    for job in jobs.values():
        day = str(job.get("reviewed_at") or "")[:10]
        if not day or not since <= day <= until or job.get("repo") != "helm-charts":
            continue
        reviewed += 1
        minutes += float(job.get("minutes") or 0)
        posted += job.get("state") == "posted"
        prs.add(job.get("pr"))
    return {"reviews": reviewed, "prs": len(prs), "posted": posted, "minutes": round(minutes, 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("version")
    ap.add_argument("out")
    ap.add_argument("--baseline")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--clones-dir", default=os.path.expanduser("~/IdeaProjects"))
    ap.add_argument("--tests-results")
    ap.add_argument("--context", default="podiumd-johnb00-aks")
    ap.add_argument("--namespace", default="podiumd")
    a = ap.parse_args()

    # With an explicit --since the baseline is only a label: don't guess it.
    baseline = a.baseline or (None if a.since else baseline_version())
    since = a.since or (baseline and tag_date(f"podiumd-{baseline}"))
    until = a.until or tag_date(f"podiumd-{a.version}") or dt.date.today().isoformat()
    if not since:
        sys.exit("no start date: pass --since or --baseline (tag podiumd-<baseline> not found)")

    out = {"target": a.version, "baseline": baseline, "since": since, "until": until, "repos": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for key, slug, public, role in REPOS:
            entry = {"public": public, "notes_name": role}
            try:
                path = clone(slug, a.clones_dir, tmp)
                ref = default_ref(path)
                entry.update(git_metrics(path, "--remotes=origin", since, until))
                if key == "podiumd-tests":
                    entry.update(tests_added(path, ref, since, until))
                    entry["test_runs"] = test_runs(a.tests_results or os.path.join(path, "results"),
                                                   a.version, since, until)
                if key == "known-issues":
                    entry.update(known_issue_counts(path, ref, since, until))
                if key == "review-tooling":
                    entry["review_ledger"] = review_ledger(a.context, a.namespace, since, until)
            except RuntimeError as e:
                entry["error"] = str(e)[:300]
            out["repos"][key] = entry

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"{since} to {until} (baseline {baseline}, target {a.version})")
    for key, e in out["repos"].items():
        if "error" in e:
            print(f"{key:16} error: {e['error']}")
            continue
        line = (f"{key:16} {e['commits']:4} commits, {e['merged_prs']:3} PRs, {e['authors']} authors, "
                f"+{e['lines_added']}/-{e['lines_deleted']}")
        if "test_functions_added" in e:
            r = e["test_runs"]
            line += (f"; tests +{e['test_functions_added']}/-{e['test_functions_removed']}, "
                     f"{r['runs']} runs on {a.version} {r['by_tier']}")
        if "reports_added" in e:
            line += f"; {e['reports_added']} reports added"
        if "review_ledger" in e:
            line += f"; ledger {e['review_ledger']}"
        print(line)


if __name__ == "__main__":
    main()
