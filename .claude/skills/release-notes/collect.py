#!/usr/bin/env python3
"""Release-notes collector: upstream hints for the release-notes skill.

collect.py <baseline version> <target version> <out.json>

Reads, at tag podiumd-<target>:
- the component table of docs/_UPGRADE_PATHS/<baseline>-to-<target>-upgrade.md
  (one row per component or sub-image: app range and chart range),
- docs/images/images-<target>.yaml (image URL per row),
- charts/podiumd/Chart.yaml (chart repository per dependency),
and fetches, per row, the upstream GitHub releases in (old, new] of the
application (source repo from the image's OCI label, a ghcr path, or an
override) and of the Helm chart (repo from <org>.github.io/<repo>, release tags
<chart>-<version>). Versions published only as a tag fall back to the repo's
changelog file. Writes one JSON bundle; does not write any notes.

The upstream texts are only input for the size and impact assessment in
SKILL.md; they do not go into the release notes.
"""
import json
import re
import subprocess
import sys

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                      check=True).stdout.strip()
APP_OVERRIDES = {  # image repository -> GitHub repo
    "maykinmedia/open-inwoner": "maykinmedia/open-inwoner",
    "maykinmedia/open-forms": "open-formulieren/open-forms",
    "openformulieren/open-forms": "open-formulieren/open-forms",
    "maykinmedia/objects-api": "maykinmedia/objects-api",
    "maykinmedia/open-object": "maykinmedia/open-object",
    "infonl/zaakafhandelcomponent": "infonl/dimpact-zaakafhandelcomponent",
    "hashicorp/vault-k8s": "hashicorp/vault-k8s",
    "alpine/k8s": "alpine-docker/k8s",
}
SEMVER = re.compile(r"\d+\.\d+\.\d+")


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, check=False)


def git_show(tag, path):
    return sh("git", "-C", REPO, "show", f"{tag}:{path}").stdout


def vkey(v):
    m = SEMVER.search(v)
    return tuple(int(x) for x in m.group(0).split(".")) if m else (0, 0, 0)


def in_range(v, old, new):
    return old is not None and vkey(old) < vkey(v) <= vkey(new)


def parse_range(cell):
    m = re.match(r"(\S+)\s*→\s*(\S+)", cell.strip())
    return (m.group(1), m.group(2)) if m else None


def component_rows(tag, baseline, target):
    doc = git_show(tag, f"charts/podiumd/docs/_UPGRADE_PATHS/{baseline}-to-{target}-upgrade.md")
    rows, in_table = [], False
    for line in doc.splitlines():
        if line.startswith("## Component versions"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if in_table and line.startswith("| ") and not line.startswith(("| Component", "| ---")):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append({"component": cells[0], "app": parse_range(cells[1]), "chart": parse_range(cells[2]),
                         "app_cell": cells[1], "chart_cell": cells[2], "notes": cells[3] if len(cells) > 3 else ""})
    return rows


def manifest_urls(tag, target):
    groups, current = {}, None
    for line in git_show(tag, f"charts/podiumd/docs/images/images-{target}.yaml").splitlines():
        m = re.match(r"# (\S.*?) \S+ -> \S+$", line) or re.match(r"# (\S.*?) \S+ \(digest changed\)$", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"\s+url:\s+(\S+)", line)
        if m and current:
            groups.setdefault(current, []).append(m.group(1))
    return groups


def image_for_row(row, groups):
    head, _, sub = row["component"].partition(" - ")
    urls = groups.get(row["component"]) or groups.get(head) or []
    if sub:
        hits = [u for u in urls if sub.lower() in u.rsplit("/", 1)[-1].lower()]
        return hits[0] if hits else None
    return urls[0] if urls else None


def app_repo(url, version):
    repo = url.split("/", 1)[1] if "." in url.split("/")[0] else url
    repo = repo.removeprefix("library/")
    if repo in APP_OVERRIDES:
        return APP_OVERRIDES[repo], "override"
    r = sh("crane", "config", f"{url}:{version}")
    if r.returncode == 0:
        labels = (json.loads(r.stdout).get("config") or {}).get("Labels") or {}
        m = re.match(r"https?://github\.com/([^/]+/[^/#?]+)", labels.get("org.opencontainers.image.source", ""))
        if m:
            return m.group(1).removesuffix(".git"), "oci-label"
    if url.startswith("ghcr.io/"):
        parts = url.split("/")
        return f"{parts[1]}/{parts[2].split('.')[0]}", "ghcr-path"
    return None, "unknown"


def chart_repos(tag):
    """Dependency name or alias -> (chart name, GitHub repo) from Chart.yaml."""
    out, dep = {}, {}
    for line in git_show(tag, "charts/podiumd/Chart.yaml").splitlines() + ["  - name: __end__"]:
        m = re.match(r"\s+-\s+name:\s*(\S+)", line)
        if m:
            if dep.get("name"):
                rm = re.match(r'"?https://([^.]+)\.github\.io/([^/"]+)', dep.get("repository", ""))
                for key in filter(None, (dep.get("alias"), dep["name"])):
                    out[key] = (dep["name"], f"{rm.group(1)}/{rm.group(2)}" if rm else None)
            dep = {"name": m.group(1)}
            continue
        m = re.match(r"\s+(repository|alias):\s*(\S+)", line)
        if m and dep:
            dep[m.group(1)] = m.group(2).strip('"')
    return out


CHANGELOG_PATHS = ("CHANGELOG.md", "CHANGELOG.rst", "CHANGES.rst", "CHANGELOG", "docs/changelog.rst",
                   "docs/changelog.md", "docs/changelog/changelog.md", "docs/changelog/changelog.rst")


def changelog(repo, ref=""):
    for path in CHANGELOG_PATHS:
        q = f"?ref={ref}" if ref else ""
        r = sh("gh", "api", f"repos/{repo}/contents/{path}{q}", "-H", "Accept: application/vnd.github.raw")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    return ""


def section(log, version):
    lines = log.splitlines()

    def heading(i):
        under = i + 1 < len(lines) and lines[i + 1].strip() and set(lines[i + 1].strip()) <= set("=-~^")
        return lines[i].startswith("#") or bool(under)

    start = next((i for i, l in enumerate(lines)
                  if re.search(rf"(^|[^0-9.]){re.escape(version)}([^0-9]|$)", l) and heading(i)), None)
    if start is None:
        return ""
    end = next((j for j in range(start + 2, len(lines)) if SEMVER.search(lines[j]) and heading(j)), len(lines))
    return "\n".join(lines[start:end]).strip()[:6000]


def thin(body):
    """A release text that is only links (changelog, docs, image, compare)."""
    text = re.sub(r"https?://\S+|\[[^\]]*\]\([^)]*\)|`[^`]*`|[#*>\-_]", " ", body or "")
    text = re.sub(r"(?i)changelog|documentation|docker image|helm chart|release notes|all changes|full changelog|what's changed", " ", text)
    return len(text.split()) < 15


def enrich(repo, rel, prev_tag):
    """Fill a thin release from the changelog at its tag, else from the PR titles in the compare range."""
    if not thin(rel.get("body")):
        return rel
    version = SEMVER.search(rel["tag"]).group(0)
    log = changelog(repo, rel["tag"])
    body = section(log, version) if log else ""
    if body and not thin(body):
        return dict(rel, body=body, source="changelog@tag")
    if prev_tag:
        r = sh("gh", "api", f"repos/{repo}/compare/{prev_tag}...{rel['tag']}", "--jq",
               "[.commits[].commit.message | split(\"\\n\")[0]] | .[]")
        titles = [l for l in r.stdout.splitlines() if not re.search(r"(?i)^(chore|ci|build)|bump|renovate|dependabot|merge (branch|pull)", l)]
        if titles:
            return dict(rel, body="\n".join(f"* {l}" for l in titles[:60]), source="compare")
    return rel


def releases(repo, old, new, tag_prefix=""):
    r = sh("gh", "api", f"repos/{repo}/releases?per_page=100", "--paginate", "--jq",
           ".[] | {tag: .tag_name, name: .name, date: .published_at, url: .html_url, body: .body, draft: .draft, prerelease: .prerelease}")
    if r.returncode != 0:
        return [], f"releases API: {r.stderr.strip()[:120]}"
    out = []
    for line in r.stdout.splitlines():
        rel = json.loads(line)
        if rel.get("draft") or rel.get("prerelease"):
            continue
        if tag_prefix and not re.fullmatch(rf"{re.escape(tag_prefix)}v?\d+\.\d+\.\d+", rel["tag"]):
            continue
        if in_range(rel["tag"], old, new):
            out.append(rel)
    if not tag_prefix:
        have = {SEMVER.search(x["tag"]).group(0) for x in out}
        tags = sh("gh", "api", f"repos/{repo}/tags?per_page=100", "--jq", ".[].name").stdout.split()
        missing = sorted({SEMVER.search(t).group(0) for t in tags
                          if re.fullmatch(r"v?\d+\.\d+\.\d+", t) and in_range(t, old, new)} - have,
                         key=vkey)
        if missing:
            log = changelog(repo)
            for v in missing:
                out.append({"tag": v, "name": v, "url": f"https://github.com/{repo}/releases/tag/{v}",
                            "body": section(log, v) if log else "", "source": "changelog" if log else "tag-only"})
    out = sorted(out, key=lambda x: vkey(x["tag"]))
    if not tag_prefix:
        tags = sh("gh", "api", f"repos/{repo}/tags?per_page=100", "--jq", ".[].name").stdout.split()
        # Final releases only: v2.4.6, not v2.4.6-rc1.
        by_version = {SEMVER.search(t).group(0): t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", t)}
        prev = by_version.get(old)
        enriched = []
        for rel in out:
            rel.setdefault("tag", rel["tag"])
            real_tag = by_version.get(SEMVER.search(rel["tag"]).group(0), rel["tag"])
            enriched.append(enrich(repo, dict(rel, tag=real_tag), prev))
            prev = real_tag
        out = enriched
    return out, None


def main(baseline, target, out_path):
    tag = f"podiumd-{target}"
    groups, charts = manifest_urls(tag, target), chart_repos(tag)
    bundle = {"baseline": baseline, "target": target, "components": []}
    for row in component_rows(tag, baseline, target):
        entry = dict(row, sources=[])
        if row["app"]:
            url = image_for_row(row, groups)
            repo, how = app_repo(url, row["app"][1]) if url else (None, "no image in manifest")
            rels, err = releases(repo, *row["app"]) if repo else ([], "source repo unknown")
            entry["sources"].append({"kind": "app", "repo": repo, "found_via": how, "image": url,
                                     "releases": rels, "error": err})
        if row["chart"]:
            name, repo = charts.get(row["component"].split(" - ")[0], (row["component"], None))
            rels, err = releases(repo, *row["chart"], tag_prefix=f"{name}-") if repo else (
                [], "chart repo is not a <org>.github.io/<repo> URL")
            entry["sources"].append({"kind": "chart", "repo": repo, "found_via": f"chart {name}",
                                     "releases": rels, "error": err})
        bundle["components"].append(entry)
    json.dump(bundle, open(out_path, "w"), indent=1)
    for c in bundle["components"]:
        print(f"{c['component']:42} app={c['app_cell']:28} chart={c['chart_cell']}")
        for s in c["sources"]:
            tags = [r["tag"] + ("*" if r.get("source") else "") for r in s["releases"]]
            print(f"    {s['kind']:5} {s['repo']} [{s['found_via']}] {tags} {s['error'] or ''}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
