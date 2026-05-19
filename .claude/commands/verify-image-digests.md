Verify every digest-pinned image in `charts/podiumd/values.yaml` (and the `docs/images/images-*.yaml` manifests) against its upstream registry, report stale pins, and optionally refresh them on the current branch.

Usage: `/verify-image-digests`            → report only
       `/verify-image-digests --fix`      → also bump stale digests on the current branch

What "stale" means here: the version **tag** (e.g. `1.30.0`, `26.6.1`) is unchanged but upstream re-published that tag with new base/security layers, so the multi-arch index digest changed. The old pinned digest is still pullable (immutable) — nothing is broken — but the deployment runs old layers and misses upstream patches. Stale ≠ corrupt. This is normally Renovate's job; this command is for an explicit pre-release sweep that also catches images Renovate has no PR for (e.g. omc, zgw-office-add-in, solr, apisix had none).

Behavior:

1. Extract every `tag: "<tag>@sha256:<digest>"` pin from `charts/podiumd/values.yaml` (skip pure comment lines). Map each to its `repository` (the `repository:` line in the same block, an explicit `# host/repo:tag@sha256:` ref comment, or the sub-chart default). Cross-reference `docs/images/images-4.7.0.yaml` / latest `images-*.yaml` which carry explicit `url` + `digest` and are authoritative for repo paths.
2. For each unique `host/repo:tag`, fetch the upstream `Docker-Content-Digest` (the canonical multi-arch index digest) using the registry recipe from `/fetch-image-digest`. **Run the fetches inside WSL** (`wsl -d Ubuntu-24.04 -- bash /mnt/c/.../tmp/verify-digests.sh`): direct Windows Python/curl to `ghcr.io`/`registry-1.docker.io` times out; WSL works. Auth: docker.io & ghcr.io need an anonymous bearer token; quay.io/gcr.io/registry.k8s.io do not. Keep going on per-item errors and retry a fetch error once.
3. Report a table of MISMATCH / FETCH-ERR rows only, plus an `N/total matched` count. For each mismatch give the full pinned digest, full upstream digest, and the exact `values.yaml` line numbers (a single image can be pinned many times — nginx-unprivileged appears ~8×). Also flag any image where `values.yaml` and the `images-*.yaml` manifest already disagree with each other.
4. With `--fix`: for each confirmed stale pin, replace ONLY the 64-hex sha256 substring (Edit with `replace_all`, keep the tag and everything else byte-identical). Update any adjacent ref/comment line that embeds the old digest too. Do NOT touch tag-only references that have no `@sha256` (e.g. a sub-chart-default image such as apisix) — those are not pinned in values.yaml; record them in the release `images-*.yaml` instead. After editing, run `/helm-render-all` and confirm the chart still templates and the new digests appear in the rendered output before reporting done.

Notes:
- A heavy fetch sweep (~25-30 images) is a good fit to delegate to a sub-agent so the registry output stays out of the main context; have it return only the findings table + exact line numbers, then apply fixes in the parent.
- `images-*.yaml` files are frozen per release — do not retroactively rewrite a shipped release's manifest; record refreshed digests in the manifest for the release you are preparing.
- Render-verify is mandatory after `--fix` (project rule: never report a `values.yaml` change done without a helm render).

Reference (digest-only replace, preserves tag — run once per stale image):

```
Edit charts/podiumd/values.yaml
  old_string: <old 64-hex>     new_string: <new 64-hex>     replace_all: true
```
