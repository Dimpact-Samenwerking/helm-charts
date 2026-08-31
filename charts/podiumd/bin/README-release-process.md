# Release Process

## Table of contents
- [Setup](#setup)
  - [Required external tools](#required-external-tools)
  - [Debian setup](#debian-setup)
  - [macOS setup](#macos-setup)
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
`verify-podiumd` needs each of these for its checks:
- `helm-docs` — Helm doc
- `yamllint` — yamllint check
- `kubeconform` — kubeconform check
- `shellcheck` — shellcheck check
- `kube-score` — kube-score check
- `docker` — CVE scan (optional — missing docker just reports the scan as skipped, never blocks a run)
- `python3-venv` (Debian only — see below) — to create the `.venv`

### Debian setup
`helm`/`helm-docs`/`kubeconform`/`kube-score` have no Debian package — installed straight from their own GitHub releases.

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
                              # (colima: free, no-license-limit CLI-only alternative to Docker
                              # Desktop — unlike Desktop it doesn't self-start, `colima start`
                              # is needed once per boot; no special flags needed for CVE scanning)

# Python tools, from the project-root
python3 -m venv .venv
.venv/bin/pip install -r charts/podiumd/bin/requirements.txt
```

## Process steps

### Start a new release
- create a branch from the baseline branch, name it `podiumd-<version>`
- run `create-podiumd-version` to set the version and create (upgrade) docs
- run `verify-podiumd` to check consistency, if not ok, fix the issues
- run `export-confluence-release-table` to fetch the input for the release
- commit+push the changes

### When release is rebased on a different baseline
- rebase the branch on the new baseline
- run `change-podiumd-baseline` to update `charts/podiumd/release-baseline` and rebase the docs
- run `verify-podiumd` to check consistency, if not ok, fix the issues
- commit+push the changes

### Update component versions in the release
A component consists of a helm-chart and a container image.

- create a branch from the release branch (`podiumd-<version>`), name it `podiumd-<version>-<my_changes>`
- run `query-release-table vendor <name>` or `query-release-table component <name>`, to show changes
- per component:
    - run `show-component-baseline-version` to show the baseline version, check it in confluence
    - run `update-component-version <component> <app-version> <helm-version>` to update the app+helm version using the queried data
    - check change docs from the component and add relevant changes to the update docs 
    - run `verify-podiumd` to check consistency, if not ok, fix the issues
    - commit+push the changes
- create a PR to merge the my-changes branch into the release branch

### Update image versions in the release
This updates just a container image version in a release.

- create a branch from the release branch (`podiumd-<version>`), name it `podiumd-<version>-<my_changes>`
- run `query-release-table section <overige|technische>` or `query-release-table component <name>`, to show changes
- per images:
    - run `show-image-baseline-version` to show the baseline version, check it in confluence
    - run `update-image-version <image> <version>` to update the app (= image) version using the queried data
    - run `verify-podiumd` to check consistency, if not ok, fix the issues
    - commit+push the changes
- create a PR to merge the my-changes branch into the release branch

### Fix and debug tools
- `fix-doc-consistency`: rebases doc filenames and components and images in them onto a different baseline (normally run automatically by `change-podiumd-baseline`)
- `fix-helm-doc`: re-generate `charts/podiumd/README.md` using `helm-docs`
- `fix-image-digests`: updates image digests for one specific image or all stale images (also runs `fix-helm-doc` on any real write)
- `fix-markdown`: auto-fix whatever pymarkdown's own `fix` mode can safely resolve
- `fix-node-selector`: insert the required `nodeSelector` into any own template missing one
- `fix-utf8-bom`: strip the utf8-bom of `charts/podiumd/values.yaml`
- `fix-vendored-tgz`: delete an extracted sub-chart directory shadowing its own pinned `.tgz`
- `render-podiumd`: outputs a rendered chart, so that line-numbers in output of verify-podiumd can be matched

### Check or finalize the release
- per changes branch:
    - merge the changes branch into the release branch
    - fix merge conflicts
    - run `verify-podiumd` to check consistency, if not ok, fix the issues
    - commit+push if changes were made
- run `verify-podiumd` to check consistency, if not ok, fix the issues or repeat previous steps
- run `export-confluence-release-table` to fetch the input for the release
- run `verify-release-table-with-podiumd` to the release contains the expected changes
- run `list-podiumd-images` to list all images, check that all are mentioned in confluence

## Tools overview
Notes: 
- tools are re-runable
- tools support `--help`

Tools:
- `change-podiumd-baseline`: change the baseline recorded in `charts/podiumd/release-baseline` and rebase the docs onto it (runs `fix-doc-consistency`, then `fix-helm-doc`), given a baseline that must resolve to an existing `podiumd-<version>` tag or `feature/podiumd-<version>` branch
- `create-doc-version`: create the standard docs for the current target version, for whichever don't already exist — refuses if docs already exist under a different baseline (use `fix-doc-consistency` for that instead)
- `create-podiumd-version`: uses version in `charts/podiumd/Chart.yaml` as baseline release, update version in `Chart.yaml`, record the baseline in `charts/podiumd/release-baseline` and create upgrade docs (runs `create-doc-version`)
- `export-confluence-release-table`: fetch release data from confluence and store it in `charts/podiumd/release-table.csv`
- `fix-doc-consistency`: given a new baseline, rebases doc filenames and components and images in them onto it (creates the standard docs fresh instead, for whichever were never scaffolded under any baseline at all)
- `fix-helm-doc`: re-generate `charts/podiumd/README.md` using `helm-docs`
- `fix-image-digests`: updates image digests for one specific image or all stale images (also runs `fix-helm-doc` on any real write)
- `fix-markdown`: auto-fix whatever pymarkdown's own `fix` mode can safely resolve
- `fix-node-selector`: insert the required `nodeSelector` into any own template missing one
- `fix-utf8-bom`: strip the utf8-bom of `charts/podiumd/values.yaml`
- `fix-vendored-tgz`: delete an extracted sub-chart directory shadowing its own pinned `.tgz`
- `list-helmchart-images`: list images in a helm chart, given chart name and version
- `list-podiumd-images`: list images in `charts/podiumd`
- `query-release-table`: query release data from `charts/podiumd/release-table.csv` by section, vendor, component
- `render-podiumd`: outputs a rendered chart, so that line-numbers in output of verify-podiumd can be matched
- `show-component-baseline-version`: get the Helm chart AND app image version(s) of a component, given the baseline version and the component name
- `show-image-baseline-version`: get just the app image version(s) of a component, given the baseline version and the component name (same shape as `show-component-baseline-version`, minus the Helm chart version)
- `update-component-version`: update the version of component, given component name, app-version and helm-version
- `update-image-version`: update the version of image, given image name and version
- `verify-component-version`: verify that a component's helm-chart version AND app image version(s) exist, given component name, app-version and chart-version (same shape as `update-component-version`) — pre-flight check for that command
- `verify-image-version`: verify that an image version exists for an already-pinned image, given image name and version (same shape as `update-image-version`) — pre-flight check for that command, no chart involved
- `verify-podiumd`: verify podiumd's consistency, references, policies 
- `verify-release-table-with-podiumd`: verify the confluence exported release table against podiumd's implementation
