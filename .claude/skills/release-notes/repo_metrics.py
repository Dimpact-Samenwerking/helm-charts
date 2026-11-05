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
| externals | ExternalsPodiumD (Azure DevOps; local clone only) | private | merged PRs from "Merged PR N:" |
| release-tooling | helm-charts: bin, scripts, etc, .claude, .github | public | - |
| monitoring-logging | helm-charts: charts/monitoring-logging | public | - |

Per repository: commits (no merges) on the default branch and the repository's
integration branches, matched by exact name (helm-charts: feature/podiumd-X.Y.Z,
feature/monitoring-logging-X.Y.Z, release/podiumd-X.Y.Z, leaving out the release-PR
squash commits on main while the release branch's commits are still counted;
ExternalsPodiumD: feature/info-podiumd-X.Y; podiumd-infra: all
branches, it does not squash-merge), authors, lines
added and deleted, merged PRs (from the commit subjects: "Merge pull request
#N", "... (#N)" or "Merged PR N:"); and, separately in "other_branches", the
commits that are only on other branches of origin. Those are unmerged work
(the QA infrastructure works on long-lived branches), but can also be the
original commits of a squash-merged PR whose branch was kept: never add them
to the default-branch figures. Commits are selected by author date, which a
rebase keeps. The test and report counts use the default branch; the test
count compares `def test_` lines, so a renamed or moved test counts as one
added and one removed (approximate).

Period: from the commit time of the tag podiumd-<baseline> (exclusive) (baseline from
charts/podiumd/etc/release-baseline.yaml, or --baseline) to the commit time of the tag
podiumd-<version> (inclusive), or now while the release is not tagged, so a tag's own
commit counts for that release only. --since/--until override both (dates, UTC, whole
days, inclusive).

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

HELM_CHARTS = "Dimpact-Samenwerking/helm-charts"
# Integration branches by exact name (regex on the branch name under origin/): a glob
# like feature/podiumd-* would also take PR and work branches such as
# feature/podiumd-4.10.0-keycloak-hostname, whose commits come back squashed.
HC_INTEGRATION = [r"feature/podiumd-\d+\.\d+\.\d+", r"feature/monitoring-logging-\d+(\.\d+)+",
                  r"release/podiumd-\d+\.\d+\.\d+"]
# The release PR squash-merges feature/podiumd-X.Y.Z into main ("feature: PodiumD 4.10.0 (#482)",
# "Feature/podiumd 4.8.2 (#389)"). That commit repeats the release branch's commits, but only
# while those commits are still counted, i.e. reachable from an integration branch. Once the
# release branch is deleted, the squash commit is the only copy of the release work and counts.
HC_RELEASE_SQUASH = r"(?i)^(feature[:/]?\s*)?podiumd \d+\.\d+\.\d+\b.*\(#(\d+)\)$"
REPOS = [
    # key, slug, public, role for the notes (Dutch), paths (None: whole repository),
    # integration branches next to the default branch: the branches work is merged into.
    # Their commits count as done work; commits only on other branches are reported apart.
    ("podiumd-tests", "infonl/podiumd-tests", True, "podiumd-tests (testset)", None, []),
    ("podiumd-minikube", "infonl/podiumd-minikube", True, "podiumd-minikube (lokale testomgeving)", None, []),
    ("known-issues", "infonl/podiumd-known-issues", False, "het interne overzicht van bekende problemen", None, []),
    # podiumd-infra works on long-lived branches and does not squash-merge: every branch counts.
    ("qa-infra", "ICATT-Menselijk-Digitaal/podiumd-infra", False, "de QA-infrastructuur", None, ["*"]),
    ("review-tooling", "infonl/podiumd-local-review", False, "de reviewtooling (lokale LLM-reviews)", None, []),
    # Not on GitHub (Azure DevOps): only a local clone works. Only the PodiumD-release
    # integration branches count (feature/info-podiumd-<minor>), where the environment PRs land.
    ("externals", "ssctwente/ExternalsPodiumD", False, "de inrichting van de externe ontwikkelomgevingen", None,
     [r"feature/info-podiumd-\d+\.\d+"]),
    ("release-tooling", HELM_CHARTS, True, "de releasetooling in helm-charts (scripts, controles, skills)",
     ["charts/podiumd/bin", "charts/podiumd/scripts", "charts/podiumd/etc", ".claude", ".github"], HC_INTEGRATION),
    ("monitoring-logging", HELM_CHARTS, True, "de monitoring-logging-chart", ["charts/monitoring-logging"],
     HC_INTEGRATION),
]
PR_SUBJECT = re.compile(r"Merge pull request #(\d+)|\(#(\d+)\)\s*$|^Merged PR (\d+):")
# Tools, not people: never count them as contributors (authors or Co-authored-by).
NOT_A_PERSON = re.compile(r"(?i)\b(claude|copilot|renovate|dependabot)\b|\[bot\]")
TEST_DEF = re.compile(r"^[+-]\s*(?:async\s+)?def test_\w+", re.M)


def run(args, cwd=None, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"{' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def utc(iso):
    """An ISO 8601 timestamp as an aware UTC datetime."""
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def in_window(iso, since, until):
    """since < t <= until: a tag's own commit belongs to that tag's release, not to the next."""
    try:
        return since < utc(iso) <= until
    except ValueError:
        return False


def tag_date(tag):
    """Commit time of a helm-charts tag (from GitHub, ISO 8601), or None when it does not exist."""
    try:
        p = subprocess.run(["gh", "api", f"repos/Dimpact-Samenwerking/helm-charts/commits/{tag}",
                            "--jq", ".commit.committer.date"], capture_output=True, text=True)
    except OSError:
        return None
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def baseline_version():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "..", "charts", "podiumd", "etc", "release-baseline.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"^\s*upgrade_docs:\s*\"?([\d.]+)", text, re.M)
    return m and m[1]


def clone(slug, clones_dir, tmp, github=True):
    name = slug.split("/")[1]
    path = os.path.join(clones_dir, name)
    if os.path.isdir(os.path.join(path, ".git")):
        remotes = run(["git", "remote", "-v"], cwd=path, check=False)
        if slug.lower() in remotes.lower():
            run(["git", "fetch", "-q", "origin"], cwd=path)
            return path
    if not github:
        raise RuntimeError(f"no local clone of {slug} in {clones_dir} (not on GitHub, so no gh clone)")
    path = os.path.join(tmp, name)
    run(["gh", "repo", "clone", slug, path, "--", "-q", "--filter=blob:none"])
    return path


def default_ref(path):
    out = run(["git", "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], cwd=path, check=False).strip()
    return out or "origin/main"


def _pr_head(pr):
    """The head commit of a helm-charts PR, or None (gh missing, PR unknown)."""
    try:
        p = subprocess.run(["gh", "pr", "view", str(pr), "-R", HELM_CHARTS, "--json", "headRefOid",
                            "--jq", ".headRefOid"], capture_output=True, text=True)
    except OSError:
        return None
    return p.stdout.strip() or None if p.returncode == 0 else None


def squash_skipper(path, refs, pattern):
    """A predicate: skip a release-PR squash commit on main only when the PR's head commit
    is reachable from one of the integration branches (so its commits are counted there).
    Without gh, fall back to: the release branch named in the subject exists."""
    if not pattern:
        return None
    branches = [r for r in refs if r.startswith("origin/")]
    cache = {}

    def skip(subject):
        m = re.search(pattern, subject)
        if not m:
            return False
        pr = m[2]
        if pr not in cache:
            head = _pr_head(pr)
            if head is None:
                v = re.search(r"\d+\.\d+\.\d+", subject)[0]
                cache[pr] = f"origin/feature/podiumd-{v}" in branches
            else:
                cache[pr] = any(subprocess.run(["git", "merge-base", "--is-ancestor", head, b], cwd=path,
                                               capture_output=True).returncode == 0 for b in branches)
        return cache[pr]
    return skip


def _log_metrics(path, refs, since, until, only, skip_subject=None):
    """Commits (no merges), authors, lines, PR numbers and counted release-squash commits of
    the commits reachable from refs whose author date is in the period. Author date, not
    committer date: a rebase resets the committer date, so rebased older work would count
    as new. A counted release-squash commit (its release branch is gone) stands for the
    whole release branch: its Co-authored-by authors count too."""
    commits, authors, prs, added, deleted, squashes = 0, set(), set(), 0, 0, 0
    log = run(["git", "log", *refs, "--no-merges", "--format=%x00%H%x09%aI%x09%an%x09%s", "--numstat", *only],
              cwd=path)
    for block in log.split("\x00")[1:]:
        head, _, stats = block.partition("\n")
        sha, date, author, subject = head.split("\t", 3)
        if not in_window(date, since, until) or (skip_subject and skip_subject(subject)):
            continue
        commits += 1
        if not NOT_A_PERSON.search(author):
            authors.add(author)
        if skip_subject and re.search(HC_RELEASE_SQUASH, subject):
            squashes += 1
            body = run(["git", "show", "-s", "--format=%b", sha], cwd=path)
            authors.update(n for n in (m.strip() for m in re.findall(r"^Co-authored-by:\s*([^<]+)<", body, re.M))
                           if not NOT_A_PERSON.search(n))
        for m in PR_SUBJECT.finditer(subject):
            prs.add(int(m[1] or m[2] or m[3]))
        for line in stats.splitlines():
            a, d, *_ = line.split("\t") + ["", ""]
            if a.isdigit() and d.isdigit():
                added, deleted = added + int(a), deleted + int(d)
    return commits, authors, prs, added, deleted, squashes


def integration_refs(path, ref, patterns):
    """The default branch plus the integration branches whose name fully matches one of
    the regexes (git log arguments). "*" means every branch of origin."""
    if "*" in patterns:
        return [ref, "--remotes=origin"]
    names = run(["git", "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/origin"], cwd=path).split()
    return [ref, *[f"origin/{n}" for n in names if any(re.fullmatch(p, n) for p in patterns)]]


def git_metrics(path, ref, since, until, paths=None, integration=(), skip_subject=None):
    """Work on the default and integration branches (merged), plus commits that are
    only on other branches of origin (not merged yet, or the pre-squash commits of a
    squash-merged PR whose branch was kept), reported separately so the two are never
    added up."""
    only = ["--", *paths] if paths else []
    refs = integration_refs(path, ref, integration)
    skip = squash_skipper(path, refs, skip_subject)
    commits, authors, prs, added, deleted, squashes = _log_metrics(path, refs, since, until, only, skip)
    merges = run(["git", "log", *refs, "--merges", "--format=%aI%x09%s", *only], cwd=path)
    for line in merges.splitlines():
        date, _, subject = line.partition("\t")
        if in_window(date, since, until):
            for m in PR_SUBJECT.finditer(subject):
                prs.add(int(m[1] or m[2] or m[3]))
    o_commits, o_authors, _, o_added, o_deleted, _ = _log_metrics(
        path, ["--remotes=origin", "--not", *refs], since, until, only)
    return {"commits": commits, "authors": len(authors), "merged_prs": len(prs),
            "lines_added": added, "lines_deleted": deleted, "release_squash_commits": squashes,
            "other_branches": {"commits": o_commits, "authors": len(o_authors),
                               "lines_added": o_added, "lines_deleted": o_deleted}}


def window_base(path, ref, since):
    """The last commit before the period, or the root when there is none."""
    base = run(["git", "rev-list", "-1", f"--before={since.isoformat()}", ref], cwd=path).strip()
    return base or run(["git", "rev-list", "--max-parents=0", ref], cwd=path).split()[0]


def window_head(path, ref, until):
    return run(["git", "rev-list", "-1", f"--before={until.isoformat()}", ref], cwd=path).strip()


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
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if str(r.get("chart_version")) != version or not in_window(str(r.get("started", "")), since, until):
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
        if not in_window(str(job.get("reviewed_at") or ""), since, until) or job.get("repo") != "helm-charts":
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
    # A date from the command line covers that whole day (UTC); a tag means its exact commit time.
    if a.since:
        since = utc(f"{a.since}T00:00:00Z") - dt.timedelta(microseconds=1)
    else:
        start = baseline and tag_date(f"podiumd-{baseline}")
        if not start:
            sys.exit("no start date: pass --since or --baseline (tag podiumd-<baseline> not found)")
        since = utc(start)
    if a.until:
        until = utc(f"{a.until}T23:59:59Z")
    else:
        end = tag_date(f"podiumd-{a.version}")
        until = utc(end) if end else dt.datetime.now(dt.timezone.utc)

    out = {"target": a.version, "baseline": baseline, "since": since.isoformat(), "until": until.isoformat(),
           "repos": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for key, slug, public, role, paths, integration in REPOS:
            entry = {"public": public, "notes_name": role}
            try:
                path = clone(slug, a.clones_dir, tmp, github=key != "externals")
                ref = default_ref(path)
                entry.update(git_metrics(path, ref, since, until, paths, integration,
                                         HC_RELEASE_SQUASH if slug == HELM_CHARTS else None))
                if integration:
                    entry["integration_branches"] = integration
                if paths:
                    entry["paths"] = paths
                if key == "podiumd-tests":
                    entry.update(tests_added(path, ref, since, until))
                    entry["test_runs"] = test_runs(a.tests_results or os.path.join(path, "results"),
                                                   a.version, since, until)
                if key == "known-issues":
                    entry.update(known_issue_counts(path, ref, since, until))
                if key == "review-tooling":
                    entry["review_ledger"] = review_ledger(a.context, a.namespace, since, until)
            except (RuntimeError, OSError, ValueError) as e:
                entry["error"] = str(e)[:300]
            out["repos"][key] = entry

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"{since.isoformat()} to {until.isoformat()} (baseline {baseline}, target {a.version})")
    for key, e in out["repos"].items():
        if "error" in e:
            print(f"{key:16} error: {e['error']}")
            continue
        line = (f"{key:16} {e['commits']:4} commits, {e['merged_prs']:3} PRs, {e['authors']} authors, "
                f"+{e['lines_added']}/-{e['lines_deleted']}")
        ob = e.get("other_branches") or {}
        if ob.get("commits"):
            line += f" (other branches: {ob['commits']} commits)"
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
