Fetch the OCI manifest digest (`sha256:...`) for a container image. Used by `/images-manifest` and ad-hoc when verifying a new image entry.

Usage: `/fetch-image-digest <registry>/<repository>:<tag>`

Examples:
- `/fetch-image-digest docker.io/openzaak/open-zaak:1.27.1`
- `/fetch-image-digest quay.io/keycloak/keycloak:26.6.1`
- `/fetch-image-digest ghcr.io/infonl/zaakafhandelcomponent:4.7.1`

Behavior:

1. Parse `$ARGUMENTS` into registry, repository, tag. Reject if any piece is missing.
2. Resolve auth:
   - **Docker Hub** (`docker.io`, also accept bare `library/<name>`): first GET `https://auth.docker.io/token?service=registry.docker.io&scope=repository:<repo>:pull` to obtain a bearer token. Use the returned `token` in the `Authorization: Bearer` header for step 3.
   - **GHCR** (`ghcr.io`): GET `https://ghcr.io/token?scope=repository:<repo>:pull` for an anonymous token. Same `Authorization: Bearer` flow.
   - **Quay** (`quay.io`), **gcr.io**, **registry.k8s.io**: no token required for public manifests.
3. Request the manifest:
   ```
   GET https://<registry-host>/v2/<repository>/manifests/<tag>
   Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json
   ```
   Note: for `docker.io`, the host in the URL is `registry-1.docker.io`. Single-component repos like `nginx` must be prefixed with `library/` (so `library/nginx`).
4. Read the `Docker-Content-Digest` response header — that is the canonical multi-arch index digest. Print it.
5. If the header is missing (rare — usually a redirect), follow the `Location` header once and retry.

Reference Python snippet (use this verbatim with `python -c`):

```python
import sys, urllib.request, json
spec = sys.argv[1]               # e.g. docker.io/openzaak/open-zaak:1.27.1
host_repo, tag = spec.rsplit(':', 1)
host, repo = host_repo.split('/', 1)
api_host = 'registry-1.docker.io' if host == 'docker.io' else host
if host == 'docker.io' and '/' not in repo:
    repo = 'library/' + repo
auth = {}
if host == 'docker.io':
    t = urllib.request.urlopen(f'https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull').read()
    auth['Authorization'] = 'Bearer ' + json.loads(t)['token']
elif host == 'ghcr.io':
    t = urllib.request.urlopen(f'https://ghcr.io/token?scope=repository:{repo}:pull').read()
    auth['Authorization'] = 'Bearer ' + json.loads(t)['token']
req = urllib.request.Request(
    f'https://{api_host}/v2/{repo}/manifests/{tag}',
    headers={**auth, 'Accept': 'application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'})
with urllib.request.urlopen(req) as r:
    print(r.headers['Docker-Content-Digest'])
```

Output exactly one line: the `sha256:...` digest. If the lookup fails, report the HTTP status and which step failed (token vs manifest).
