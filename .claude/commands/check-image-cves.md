For each tag-pinned image in `charts/podiumd/values.yaml` (and the latest `docs/images/images-*.yaml` manifest), check whether a **newer patched version** exists on the upstream registry — and surface known CVEs the bump would fix. Companion to `/verify-image-digests` (which only refreshes digests for the same tag); this skill catches the case where a newer **tag** has been published with security fixes that nobody has bumped to yet.

Usage: `/check-image-cves` (no args — sweeps every pin)

Output: one Slack-friendly table grouping into three buckets — **SECURITY** (newer patch on the same minor with high/critical CVE fix), **NEWER** (newer minor/major available, no urgent CVE), **CURRENT** (pin is latest on its line). Caps at width ≤ 70 chars.

Why this exists: a stale-pin can be a digest issue (same tag re-pushed → `/verify-image-digests --fix`) **or** a tag issue (upstream cut `1.30.1`, `1.30.2` with security fixes — neither shows up as a digest mismatch on tag `1.30.0`). Renovate normally opens PRs for the tag case but lags on niche images (`omc`, `zgw-office-add-in`, `solr`, `apisix` had no Renovate PRs in 2026-05). This skill is the manual sweep.

Behavior:

1. **Enumerate pinned images** from `charts/podiumd/values.yaml`:
   - Every `tag: "<tag>[@sha256:...]"` line, plus its sibling `repository:` line (the parent block decides the registry; `quay.io/...`, `ghcr.io/...`, `docker.io/<vendor>/...` are common).
   - Cross-reference the latest `docs/images/images-*.yaml` for explicit `url:` values (authoritative for any image not pinned in values.yaml — e.g. some sub-chart default tags).

2. **For each unique `<registry>/<repo>:<tag>`**:
   - List sibling tags on the same minor line (e.g. for `1.30.0` query for `1.30.x`).
   - For docker.io use the `/v2/<repo>/tags/list` endpoint (anonymous bearer token; see `/fetch-image-digest` for the auth dance).
   - For ghcr.io and quay.io use their respective tag-list endpoints; do all fetches inside WSL — direct Windows-side calls time out on ghcr/registry-1.docker.io.
   - Compute `LATEST_PATCH` = highest `<major>.<minor>.<patch>` on the same minor line; `LATEST` = highest version overall.

3. **For each "newer patch on same minor" candidate**, run a focused web search:
   - `WebSearch <product> <new-version> CVE security advisory`
   - Cite source URLs in the output (Slack-clickable).
   - If no CVE info found, still report the bump as available but mark CVE column as "—".

4. **Slack output**:
   ```
   ## Image CVE sweep — charts/podiumd
   ```
   ```
   image              pin       latest-patch  CVE?
   ─────────────────  ────────  ────────────  ─────────────────────
   keycloak           26.6.1    26.6.2        YES (account-takeover, see below)
   nginx-unprivileged 1.30.0    1.30.2        YES (CVE-2026-42945 RCE)
   solr               9.10.1    9.10.1        — current
   apisix             3.16.0    3.16.0        — current
   ```
   - One line per image, width ≤ 70 chars. Truncate image col to 18.
   - Below the table, an ordered list of "SECURITY" bumps with one-sentence CVE summary + source URL each.
   - End with a "next step" suggestion: `/verify-image-digests --fix` for any image where the latest patch is the same tag with a refreshed digest, OR a manual `tag@sha256:` bump for any image where the latest patch is a new tag.

5. **Do not edit anything** — this skill is read-only. The bump itself is a manual judgment call (does the gemeente want this in the current release? is there a Renovate PR pending? does the ACR mirror cover the new tag?). Hand off to the operator with the data.

Notes:

- Cap WebSearch usage to ≤ 5 lookups in one run — over that and the operator can decide per-image.
- For images with no public CVE feed (Worth-NL OMC, infonl ZGW office add-in, KISS), label CVE column "—" and skip the WebSearch.
- The result of this skill drives the "Important security updates" section of the release upgrade notes.

Reference one-shot script (read-only, focused on tag-list lookups only — CVE WebSearch is interactive in the conversation):

```bash
#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:/home/john/bin:/usr/bin:/bin"

# Pull every (repo, tag) from values.yaml, keep the most-recent occurrence per repo
python3 <<'PY'
import re, pathlib, collections
v=pathlib.Path('charts/podiumd/values.yaml').read_text()
pat=re.compile(r'^( *)repository:\s*"?([^"\s#]+)"?\s*$\n(?:.*\n){0,4}^\1tag:\s*"?([^"@\s]+)(?:@sha256:[0-9a-f]+)?"?', re.M)
seen=collections.OrderedDict()
for m in pat.finditer(v):
    repo,tag=m.group(2),m.group(3)
    seen[repo]=tag
for r,t in seen.items(): print(r, t, sep='\t')
PY > /tmp/pins.tsv

# Then for each line, hit the matching registry's tags endpoint (in WSL).
# (registry-specific auth — see /fetch-image-digest reference Python snippet)
echo "Pins extracted (review then run per-registry lookups):"
cat /tmp/pins.tsv
```
