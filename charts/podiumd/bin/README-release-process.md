# Release Process

## Table of contents
- [Setup](#setup)
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
`verify-podiumd` needs the tools below, one per check — `verify-podiumd --help` points back to this table instead of repeating it. A missing tool fails that check with a clear message (add its step to `--skip=` to bypass it) — `docker` and `az` are the two exceptions, falling back gracefully instead (see their own rows):

| Tool | Needed for | Debian | macOS |
| --- | --- | --- | --- |
| `helm` | required to run at all | no apt package — official install script: `curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \| bash` | `brew install helm` |
| `helm-docs` | Helm docs check | no apt package — download the `.deb` from the [latest release](https://github.com/norwoodj/helm-docs/releases) and `sudo dpkg -i helm-docs_*.deb` | `brew install helm-docs` |
| `yamllint` | yamllint check | `sudo apt install yamllint` | `brew install yamllint` |
| `kubeconform` | kubeconform check | no apt package — download the static binary from the [latest release](https://github.com/yannh/kubeconform/releases) | `brew install kubeconform` |
| `shellcheck` | shellcheck check | `sudo apt install shellcheck` | `brew install shellcheck` |
| `kube-score` | kube-score check | no apt package — download the static binary from the [latest release](https://github.com/zegl/kube-score/releases) | `brew install kube-score` |
| `docker` | CVE scan (optional — missing docker just reports the scan as skipped, never blocks a run) | `sudo apt install docker.io` | `brew install --cask docker` (Docker Desktop), or `brew install colima docker docker-compose docker-credential-helper` for a free/no-license-limit CLI-only alternative |
| `az` | optional, Dependencies only (tells an Azure auth problem apart from a network blip — missing/unused `az` just falls back to plain retry-with-backoff) | `sudo apt install azure-cli` (in Debian's own `bookworm/main` repo, no extra source needed) | `brew install azure-cli` |

### Python tools (`ruff`, `pymarkdown`)
The `charts/podiumd/bin/` scripts' own tests use `ruff` for linting, and `verify-podiumd`'s markdown check uses `pymarkdown` — both installed into a project-root virtualenv, not system-wide: both Debian's system Python and macOS's Homebrew Python refuse a bare `pip install` ("externally managed environment", PEP 668).

Debian only — install the venv module first if it isn't already (Debian splits it out of the base `python3` package):
```bash
sudo apt install python3-venv
```

Then, from the repo root (works the same on Debian and macOS):
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.venv/` is gitignored — safe to delete and recreate any time with the two commands above.

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
- `change-doc-baseline`: rebases doc filenames and components and images in them onto a different baseline (normally run automatically by `change-podiumd-baseline`)
- `create-doc-version`: scaffolds any of the standard docs missing for the current target version (normally run automatically by `create-podiumd-version`)
- `render-podiumd`: outputs a rendered chart, so that line-numbers in output of verify-podiumd can be matched
- `set-image-digests`: updates image digests for one specific image or all stale images
- `strip-utf8-bom`: strip the utf8-bom of `charts/podiumd/values.yaml`
- `update-podiumd-readme`: re-generate `charts/podiumd/README.md` using `helm-doc`

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
- `change-doc-baseline`: given a new baseline, rebases doc filenames and components and images in them onto it (creates the standard docs fresh instead, for whichever were never scaffolded under any baseline at all)
- `change-podiumd-baseline`: change the baseline recorded in `charts/podiumd/release-baseline` and rebase the docs onto it (runs `change-doc-baseline`), given a baseline that must resolve to an existing `podiumd-<version>` tag or `feature/podiumd-<version>` branch
- `create-doc-version`: create the standard docs for the current target version, for whichever don't already exist — refuses if docs already exist under a different baseline (use `change-doc-baseline` for that instead)
- `create-podiumd-version`: uses version in `charts/podiumd/Chart.yaml` as baseline release, update version in `Chart.yaml`, record the baseline in `charts/podiumd/release-baseline` and create upgrade docs (runs `create-doc-version`)
- `export-confluence-release-table`: fetch release data from confluence and store it in `charts/podiumd/release-table.csv`
- `list-helmchart-images`: list images in a helm chart, given chart name and version
- `list-podiumd-images`: list images in `charts/podiumd`
- `query-release-table`: query release data from `charts/podiumd/release-table.csv` by section, vendor, component
- `render-podiumd`: outputs a rendered chart, so that line-numbers in output of verify-podiumd can be matched
- `set-image-digests`: updates image digests for one specific image or all stale images
- `show-component-baseline-version`: get the Helm chart AND app image version(s) of a component, given the baseline version and the component name
- `show-image-baseline-version`: get just the app image version(s) of a component, given the baseline version and the component name (same shape as `show-component-baseline-version`, minus the Helm chart version)
- `strip-utf8-bom`: strip the utf8-bom of `charts/podiumd/values.yaml`
- `update-component-version`: update the version of component, given component name, app-version and helm-version
- `update-image-version`: update the version of image, given image name and version
- `update-podiumd-readme`: re-generate `charts/podiumd/README.md` using `helm-doc`
- `verify-component-version`: verify that a component's helm-chart version AND app image version(s) exist, given component name, app-version and chart-version (same shape as `update-component-version`) — pre-flight check for that command
- `verify-image-version`: verify that an image version exists for an already-pinned image, given image name and version (same shape as `update-image-version`) — pre-flight check for that command, no chart involved
- `verify-podiumd`: verify podiumd's consistency, references, policies 
- `verify-release-table-with-podiumd`: verify the confluence exported release table against podiumd's implementation
