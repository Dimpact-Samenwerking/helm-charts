Verify a chart's `README.md` is not out of sync with its `values.yaml` (and `README.md.gotmpl` if present). This exists because README rows are meant to be helm-docs-generated but nothing in CI enforces that — drift is silent (e.g. a doc row referencing a `values.yaml` key that was never added, or a real key with no doc row).

Target chart: `$ARGUMENTS` if given (path like `charts/monitoring-logging`), otherwise check every `charts/*/` directory that has both a `Chart.yaml` and a `README.md`.

## Tier 1 — real helm-docs regen (preferred)

1. Check for the binary: `helm-docs --version`.
2. If missing, try to get one without asking the user to install anything system-wide:
   - If `go` is on PATH: `go install github.com/norwoodj/helm-docs/cmd/helm-docs@latest`, use the installed binary (`$env:GOPATH\bin\helm-docs.exe` or `go env GOPATH`).
   - Else, download the release binary into the repo's existing gitignored cache dir (`.cache/`, already in `.gitignore` — do not create a new ignore rule). Releases ship as `.tar.gz` on every OS including Windows, not `.zip`:
     ```powershell
     $ver = (Invoke-RestMethod https://api.github.com/repos/norwoodj/helm-docs/releases/latest).tag_name.TrimStart('v')
     $tarUrl = "https://github.com/norwoodj/helm-docs/releases/download/v$ver/helm-docs_${ver}_Windows_x86_64.tar.gz"
     New-Item -ItemType Directory -Force .cache/bin | Out-Null
     Invoke-WebRequest $tarUrl -OutFile .cache/bin/helm-docs.tar.gz
     tar -xzf .cache/bin/helm-docs.tar.gz -C .cache/bin helm-docs.exe
     ```
     Use `.cache/bin/helm-docs.exe` for the rest of this run.
   - If neither works (no network/go), skip to Tier 2 and say so in the report — don't fail silently.
3. For each target chart, run helm-docs scoped to just that chart (don't let it touch charts you weren't asked about):
   ```bash
   helm-docs --chart-search-root=charts --template-files=README.md.gotmpl --template-files=README.md.gotmpl -g <chart-dir-name>
   ```
   (If the chart has no `README.md.gotmpl`, drop `--template-files` and let helm-docs use its default template.)
4. `git diff --stat -- <chart>/README.md`. Empty diff = in sync. Non-empty = README was stale; helm-docs just rewrote it in the working tree.
5. **Do not stage or commit.** Report the diff exists and let the user review/stage it themselves (same policy as `/helm-precommit`).

## Tier 2 — fallback heuristic (only if helm-docs truly can't be obtained)

Approximate check, not a substitute for Tier 1 — say so in the output:

```python
import yaml, re
values = yaml.safe_load(open("<chart>/values.yaml", encoding="utf-8"))

def flatten(d, prefix=()):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from flatten(v, prefix + (k,))
    else:
        yield prefix

def key_str(path):
    # helm-docs quotes a segment if it contains a literal dot, e.g. "grafana.ini"
    return ".".join(f'"{p}"' if "." in p else p for p in path)

value_keys = {key_str(p) for p in flatten(values)}

readme = open("<chart>/README.md", encoding="utf-8").read()
readme_keys = set(re.findall(r'^\|\s*([^\|]+?)\s*\|', readme, re.M)) - {"Key", "Repository"}

orphaned = sorted(k for k in readme_keys if not any(k == v or k.startswith(v + ".") for v in value_keys))
print(f"{len(orphaned)} README row(s) with no matching values.yaml key:")
for o in orphaned:
    print(" ", o)
```

This only catches gross drift (fully orphaned rows, like the stray `grafana."grafana.ini".smtp` row found in `monitoring-logging` on 2026-07-21 before the matching `values.yaml` block existed). It will not catch a changed description or default value — that needs Tier 1.

## Report format

```
HELM-DOCS CHECK — <chart>
  Method   : helm-docs regen | fallback heuristic
  Status   : IN SYNC | DRIFT (<n> rows changed) | COULD NOT CHECK (<reason>)
```

One block per chart checked. If drift was found via Tier 1, the README in the working tree is already the corrected version — tell the user to review the diff and stage it themselves.
