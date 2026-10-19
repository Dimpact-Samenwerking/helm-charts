#!/usr/bin/env python3
"""Review statistics for the release-notes skill.

review_stats.py <target version> <out.json>

Reads, with `gh api graphql`, every open or merged PR into
feature/podiumd-<target> (the sub-PRs) and into feature/podiumd-<target>-*
(PRs that still need a second merge step), plus the release PR into main.
Writes one JSON bundle and prints a summary. Counts only; the notes decide
what to show.

- reviews: every submitted review, including plain comments and authors
  replying in their own PR; approvals and changes_requested are the verdicts.
- reviewers: human reviewers other than the author (bots such as Copilot are
  left out); merged_without_review lists merged PRs that have none.
- lead_days: created -> merged, merged PRs only.
- jira: IN-<n> keys in the PR title or body.
"""
import json
import re
import statistics
import subprocess
import sys

OWNER, NAME = "Dimpact-Samenwerking", "helm-charts"
JIRA = re.compile(r"\bIN-\d+\b")
QUERY = """
query($q: String!) { search(query: $q, type: ISSUE, first: 100) { nodes { ... on PullRequest {
  number title body state baseRefName createdAt mergedAt additions deletions changedFiles
  author { login }
  commits { totalCount }
  reviews(first: 100) { nodes { state author { login } } }
  reviewThreads(first: 100) { nodes { isResolved } }
} } } }
"""


def search(q):
    out = subprocess.run(["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"q={q}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["data"]["search"]["nodes"]


def side_branches(branch):
    out = subprocess.run(["gh", "api", "--paginate", f"repos/{OWNER}/{NAME}/branches?per_page=100",
                          "--jq", ".[].name"], capture_output=True, text=True, check=True).stdout
    return [b for b in out.split() if b.startswith(branch + "-")]


def is_bot(login):
    return not login or "copilot" in login or login.endswith("[bot]")


def pr_entry(pr):
    reviews = pr["reviews"]["nodes"]
    threads = pr["reviewThreads"]["nodes"]
    lead = None
    if pr["mergedAt"]:
        lead = round((iso(pr["mergedAt"]) - iso(pr["createdAt"])) / 86400, 1)
    return {
        "number": pr["number"], "title": pr["title"], "state": pr["state"],
        "base": pr["baseRefName"], "author": (pr["author"] or {}).get("login"),
        "additions": pr["additions"], "deletions": pr["deletions"], "files": pr["changedFiles"],
        "commits": pr["commits"]["totalCount"],
        "reviews": len(reviews),
        "approvals": sum(r["state"] == "APPROVED" for r in reviews),
        "changes_requested": sum(r["state"] == "CHANGES_REQUESTED" for r in reviews),
        "reviewers": sorted({r["author"]["login"] for r in reviews
                             if r["author"] and not is_bot(r["author"]["login"])}
                            - {(pr["author"] or {}).get("login")}),
        "threads": len(threads), "resolved": sum(t["isResolved"] for t in threads),
        "lead_days": lead,
        "jira": sorted(set(JIRA.findall(pr["title"] + " " + (pr["body"] or "")))),
    }


def iso(ts):
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def summary(prs):
    merged = [p for p in prs if p["state"] == "MERGED"]
    leads = [p["lead_days"] for p in merged]
    return {
        "prs": len(prs), "merged": len(merged), "open": len(prs) - len(merged),
        "reviews": sum(p["reviews"] for p in prs),
        "approvals": sum(p["approvals"] for p in prs),
        "changes_requested": sum(p["changes_requested"] for p in prs),
        "reviewers": sorted({r for p in prs for r in p["reviewers"]}),
        "threads": sum(p["threads"] for p in prs),
        "resolved": sum(p["resolved"] for p in prs),
        "open_threads": {p["number"]: p["threads"] - p["resolved"]
                         for p in prs if p["threads"] > p["resolved"]},
        "merged_without_review": [p["number"] for p in merged if not p["reviewers"]],
        "merged_without_approval": [p["number"] for p in merged if p["approvals"] == 0],
        "most_discussed": [p["number"] for p in sorted(prs, key=lambda p: -p["reviews"])[:5]],
        "lead_days_median": statistics.median(leads) if leads else None,
        "lead_days_max": max(leads) if leads else None,
        "additions": sum(p["additions"] for p in merged),
        "deletions": sum(p["deletions"] for p in merged),
    }


def main(target, out_path):
    branch = f"feature/podiumd-{target}"
    repo = f"repo:{OWNER}/{NAME} is:pr"
    sub = [pr_entry(p) for p in search(f"{repo} base:{branch} is:open")
           + search(f"{repo} base:{branch} is:merged")
           if p["baseRefName"] == branch]  # search's base: also matches longer names
    # Search cannot prefix-match base:, so search each feature/podiumd-<target>-* branch.
    side = [pr_entry(p) for b in side_branches(branch)
            for p in search(f"{repo} base:{b} is:open") + search(f"{repo} base:{b} is:merged")
            if p["baseRefName"] == b]
    release = [pr_entry(p) for p in search(f"{repo} base:main head:{branch}")
               if p["state"] != "CLOSED"]
    bundle = {"target": target, "branch": branch, "summary": summary(sub),
              "release_pr": release[0] if release else None,
              "second_step": side, "prs": sorted(sub, key=lambda p: p["number"])}
    json.dump(bundle, open(out_path, "w"), indent=1)
    s = bundle["summary"]
    print(f"{branch}: {s['prs']} PRs, {s['merged']} merged, {s['open']} open")
    print(f"reviews {s['reviews']}, approvals {s['approvals']}, "
          f"changes requested {s['changes_requested']}, reviewers {len(s['reviewers'])}: "
          f"{', '.join(s['reviewers'])}")
    print(f"threads {s['threads']}, resolved {s['resolved']}, open per PR {s['open_threads']}")
    print(f"merged without review {s['merged_without_review']}, "
          f"without approval {s['merged_without_approval']}")
    print(f"most discussed {s['most_discussed']}, lead days median {s['lead_days_median']} "
          f"max {s['lead_days_max']}, merged lines +{s['additions']} -{s['deletions']}")
    r = bundle["release_pr"]
    if r:
        print(f"release PR #{r['number']} {r['state']}: {r['commits']} commits, {r['files']} files, "
              f"+{r['additions']} -{r['deletions']}, reviews {r['reviews']}")
    for p in side:
        print(f"second step: #{p['number']} -> {p['base']} ({p['state']})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:3])
