# Release Process

## Table of contents

- [Setup](#setup)
  - [Required external tools](#required-external-tools)
  - [Debian setup](#debian-setup)
  - [macOS setup](#macos-setup)
  - [Vendored sub-charts](#vendored-sub-charts)
- [Confluence release tables](#confluence-release-tables)
- [Process steps](#process-steps)
  - [Start a new release](#start-a-new-release)
  - [When release is rebased on a different baseline](#when-release-is-rebased-on-a-different-baseline)
  - [Update component versions in the release](#update-component-versions-in-the-release)
  - [Update image versions in the release](#update-image-versions-in-the-release)
  - [Fix and debug tools](#fix-and-debug-tools)
  - [Check or finalize the release](#check-or-finalize-the-release)
- [Tools overview](#tools-overview)

## Setup

### Required external tools

`verify-podiumd` needs these for its checks. Versions are known to work, not
enforced minimums:

- `helm` — needed by nearly every script (known-working: v3.22.0; v3.9.0
  works apart from `--dry-run=client` features)
- `helm-docs` — Helm doc (known-working: 1.14.2)
- `yamllint` — yamllint check (known-working: 1.29.0)
- `kubeconform` — kubeconform check (known-working: v0.8.0)
- `shellcheck` — shellcheck check (known-working: 0.9.0)
- `kube-score` — kube-score check (known-working: 1.20.0)
- `docker` — CVE scan; optional, reported as skipped when missing (known-working: 29.8.0)
- `python3-venv` (Debian only) — to create the `.venv` (known-working: Python 3.11)

### Debian setup

`helm`, `helm-docs`, `kubeconform` and `kube-score` have no Debian package; install them from their GitHub releases.

```bash
sudo apt install -y yamllint shellcheck docker.io python3-venv
# helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
# helm-docs
curl -sL "$(curl -s https://api.github.com/repos/norwoodj/helm-docs/releases/latest | grep -o 'https://[^"]*_Linux_x86_64\.deb')" -o /tmp/helm-docs.deb
sudo dpkg -i /tmp/helm-docs.deb
# kubeconform
curl -sL "$(curl -s https://api.github.com/repos/yannh/kubeconform/releases/latest | grep -o 'https://[^"]*kubeconform-linux-amd64\.tar\.gz')" | sudo tar -xz -C /usr/local/bin kubeconform
# kube-score
curl -sL "$(curl -s https://api.github.com/repos/zegl/kube-score/releases/latest | grep -o 'https://[^"]*kube-score_[0-9.]*_linux_amd64"' | tr -d '"')" -o /tmp/kube-score
sudo install -m 0755 /tmp/kube-score /usr/local/bin/kube-score
# Python tools, from the project-root
python3 -m venv .venv
.venv/bin/pip install -r charts/podiumd/bin/requirements.txt
```

### macOS setup

```bash
brew install helm helm-docs yamllint kubeconform shellcheck kube-score
brew install --cask docker   # or: brew install colima docker && colima start
                              # (colima needs `colima start` once per boot)

# Python tools, from the project-root
python3 -m venv .venv
.venv/bin/pip install -r charts/podiumd/bin/requirements.txt
```

### Vendored sub-charts

`charts/podiumd/charts/*.tgz` and `charts/podiumd/Chart.lock` are gitignored. When
`Chart.yaml` moves on (branch switch, pull, `update-component-version`), they stay at
the old versions until someone re-vendors them. A stale state makes `helm template`
fail with a sub-chart schema error that never mentions the real cause.

Every script that renders the chart or reads its vendored `.tgz` files checks this
first, in milliseconds. When stale, it names the wrong dependencies on stderr and
re-vendors them:

```text
charts/podiumd/charts/ and Chart.lock do not match Chart.yaml, re-vendoring:
  - referentielijsten: Chart.yaml wants 0.2.0, Chart.lock has 0.1.1
  - referentielijsten: Chart.yaml wants 0.2.0, charts/ has 0.1.1
Running helm pull referentielijsten 0.2.0 (attempt 1/3)...
Re-vendored only what changed: fetched 1 of 25 dependencies (referentielijsten 0.2.0)
```

Re-vendoring fetches only the changed dependencies (`helm pull`, or `helm package`
for a `file://` chart) and writes `Chart.lock` as `helm dependency update` would, in
seconds instead of about 80s for all 25. The full update is the fallback when there
is no `Chart.lock`, a dependency uses a version range, or a fetch fails. If that
fails too, the script stops with `Run: helm dependency update charts/podiumd`.

Checked by: `fix-doc-consistency`, `list-podiumd-images`, `render-podiumd`,
`update-component-version`, `update-image-version`, `verify-helm-secret-size`
(against its own `--chart`), `verify-podiumd-dead-values` and
`verify-release-table-with-podiumd` (not with `--baseline-only`).
`update-component-version` also re-vendors as its last step. `verify-podiumd`'s
"Dependencies" step and `fix-image-digests` re-vendor as a step of their own;
`verify-podiumd --skip=dependencies` still re-vendors when a step needs the sub-charts.

## Confluence release tables

`export-confluence-release-table` resolves Confluence rows by exact match only:
ignoring case, spaces and punctuation, the whole name, or the part before or
inside its brackets, must equal an identifier. Other rows get component
`UNKNOWN` and an empty image, with a warning. Name rows as
`<readable name> (<identifier>)`:

- a component row: the Chart.yaml dependency name or alias, or the native
  component (`etc/settings.yaml` `native_components`), e.g.
  `ZAC (zaakafhandelcomponent)`, `Open Inwoner (Portaal)`, `Keycloak`; its
  image follows from the component's registered image paths
- a "Technische component versies" row: "Used by" names the component, the
  name ends in the image basename, e.g. `Frank Gateway Etcd (etcd)`
- a shared `global.images` image: the key or its image basename, e.g.
  `Nginx (unprivileged)`

`verify-release-table-with-podiumd` prints the exact name a missing row
needs.

## Process steps

### Start a new release

- create a branch from the baseline branch, name it `podiumd-<version>`
- run `create-podiumd-version` to set the version and create (upgrade) docs
- run `verify-podiumd` to check consistency, if not ok, fix the issues
- run `export-confluence-release-table` to fetch the input for the release
- run `verify-release-table-with-podiumd --baseline-only` to check the release baseline matches with confluence
- update the confluence with the findings reported
- commit+push the changes

### When release is rebased on a different baseline

- rebase the branch on the new baseline branch
- run `change-podiumd-baseline` to update `charts/podiumd/etc/release-baseline.yaml`'s `upgrade_docs` key and rebase the docs
- run `verify-podiumd` to check consistency, if not ok, fix the issues
- commit+push the changes

### Update component versions in the release

A component consists of a helm-chart and a container image.

- create a branch from the release branch (`podiumd-<version>`), name it `podiumd-<version>-<my_changes>`
- run `query-release-table vendor <name>` or `query-release-table component <name>`, to show changes
- per component:
  - run `update-component-version <component> <app-version> <helm-version>` to update the app+helm version using the queried data
  - check docs from the component and add relevant changes to `<baseline>-to-<version>-*.md`
  - run `verify-podiumd` to check consistency, if not ok, fix the issues
  - commit+push the changes
- create a PR to merge the my-changes branch into the release branch

### Update image versions in the release

This updates just a container image version in a release.

- create a branch from the release branch (`podiumd-<version>`), name it `podiumd-<version>-<my_changes>`
- run `query-release-table section <overige|technische>` or `query-release-table component <name>`, to show changes
- per images:
  - run `update-image-version <key> <basename> <version>` to update the image version using the queried data
  - run `verify-podiumd` to check consistency, if not ok, fix the issues
  - commit+push the changes
- create a PR to merge the my-changes branch into the release branch

### Fix and debug tools

- `fix-doc-consistency`: rebase the upgrade docs onto the `upgrade_docs` baseline and repair their content (run by `change-podiumd-baseline`)
- `fix-helm-doc`: re-generate `charts/podiumd/README.md` using `helm-docs`
- `fix-image-digests`: refresh stale image digests, for one image or all
- `fix-markdown`: apply pymarkdown's safe fixes
- `fix-node-selector`: add the required `nodeSelector` to own templates
- `fix-oidc-url-coverage`: add missing `$oidcClients` entries for Keycloak redirect URI values
- `fix-utf8-bom`: strip the UTF-8 BOM from `charts/podiumd/values.yaml`
- `fix-vendored-tgz`: delete extracted sub-chart directories shadowing a pinned `.tgz`
- `render-podiumd`: render the chart, to match line numbers in `verify-podiumd` output

### Check or finalize the release

- per changes branch:
  - merge the changes branch into the release branch
  - fix merge conflicts
  - run `verify-podiumd` to check consistency, if not ok, fix the issues
  - commit+push if changes were made
- run `verify-podiumd` to check consistency, if not ok, fix the issues or repeat previous steps
- run `export-confluence-release-table` to fetch the input for the release
- run `verify-release-table-with-podiumd` to check the release changes match with confluence

## Tools overview

Notes:

- tools are rerunnable
- tools support `--help`

Tools:

- `change-podiumd-baseline`: set the `upgrade_docs` baseline in `charts/podiumd/etc/release-baseline.yaml` and rebase the docs onto it; never changes `release_table`
- `create-doc-version`: create the missing standard docs for the target version; refuses when docs exist under another baseline
- `create-podiumd-version`: start a release from the branch name: set `Chart.yaml` to the target, record the outgoing version as `upgrade_docs` (and `release_table` on a minor bump) and create the docs; only single patch or minor steps
- `export-confluence-release-table`: fetch release data from Confluence and store it in `charts/podiumd/etc/release-table.csv`
- `fix-doc-consistency`: rebase the upgrade docs onto the `upgrade_docs` baseline, repair their content and create missing ones
- `fix-helm-doc`: re-generate `charts/podiumd/README.md` using `helm-docs`
- `fix-image-digests`: refresh stale image digests, for one image or all
- `fix-markdown`: apply pymarkdown's safe fixes
- `fix-node-selector`: add the required `nodeSelector` to own templates
- `fix-oidc-url-coverage`: add missing `$oidcClients` entries for Keycloak redirect URI values
- `fix-utf8-bom`: strip the UTF-8 BOM from `charts/podiumd/values.yaml`
- `fix-vendored-tgz`: delete extracted sub-chart directories shadowing a pinned `.tgz`
- `list-helmchart-images`: list images in a helm chart, given chart name and version
- `list-podiumd-images`: list images in `charts/podiumd`
- `query-release-table`: query release data from `charts/podiumd/etc/release-table.csv` by section, vendor, component
- `render-podiumd`: render the chart, to match line numbers in `verify-podiumd` output
- `show-component-baseline-version`: show a component's Helm chart and app image versions at both baselines
- `show-image-baseline-version`: show one image's version at both baselines, given `<key> <basename>`
- `update-component-version`: update the version of component, given component
  name, app-version and helm-version; also updates the release docs, `README.md`
  and `images-baseline.yaml`, ending with `fix-doc-consistency`
- `update-image-version`: update an image version, given `<key> <basename>` and
  version; also updates the release docs, `README.md` and `images-baseline.yaml`,
  ending with `fix-doc-consistency`
- `verify-component-version`: check a component's chart and app image versions exist; pre-flight for `update-component-version`
- `verify-helm-secret-size`: estimate a chart's Helm release Secret size against the 1 MiB limit (`--record` updates `<chart>/docs/release-secret-size.md`); for podiumd it also runs in `verify-podiumd`
- `verify-image-version`: check an image version exists; pre-flight for `update-image-version`
- `verify-podiumd`: verify podiumd's consistency, references, policies
- `verify-release-table-with-podiumd`: verify the Confluence exported release table against podiumd's implementation
