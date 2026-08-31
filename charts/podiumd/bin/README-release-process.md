# Release Process

## Table of contents
- [Process steps](#process-steps)
  - [Start a new release](#start-a-new-release)
  - [When release is rebased on a different baseline](#when-release-is-rebased-on-a-different-baseline)
  - [Update component versions in the release](#update-component-versions-in-the-release)
  - [Update image versions in the release](#update-image-versions-in-the-release)
  - [Fix and debug tools](#fix-and-debug-tools)
  - [Check or finalize the release](#check-or-finalize-the-release)
- [Tools overview](#tools-overview)

## Process steps

### Start a new release
- create a branch from the baseline branch, name it `podiumd-<version>`
- run `create-podiumd-version` to set the version and create (upgrade) docs
- run `verify-podiumd` to check consistency, if not ok, fix the issues
- run `export-confluence-release-table` to fetch the input for the release
- commit+push the changes

### When release is rebased on a different baseline
- rebase the branch on the new baseline
- run `set-doc-baseline` to update the baseline for the docs
- run `change-podiumd-baseline` to update `charts/podiumd/release-baseline`
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
- `change-podiumd-baseline`: corrects the baseline recorded in `charts/podiumd/release-baseline` (e.g. after `create-podiumd-version` recorded the wrong one, or a rebase onto a different baseline)
- `render-podiumd`: outputs a rendered chart, so that line-numbers in output of verify-podiumd can be matched
- `set-doc-baseline`: changes the baseline version of doc filenames and components and images in it
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
- `change-podiumd-baseline`: change the baseline recorded in `charts/podiumd/release-baseline`, given a baseline that must resolve to an existing `podiumd-<version>` tag or `feature/podiumd-<version>` branch
- `create-podiumd-version`: uses version in `charts/podiumd/Chart.yaml` as baseline release, update version in `Chart.yaml`, record the baseline in `charts/podiumd/release-baseline` and create updgrade docs in `charts/podiumd/docs/_UPGRADE_PATHS`
- `export-confluence-release-table`: fetch release data from confluence and store it in `charts/podiumd/release-table.csv`
- `list-helmchart-images`: list images in a helm chart, given chart name and version
- `list-podiumd-images`: list images in `charts/podiumd`
- `query-release-table`: query release data from `charts/podiumd/release-table.csv` by section, vendor, component
- `render-podiumd`: outputs a rendered chart, so that line-numbers in output of verify-podiumd can be matched
- `set-doc-baseline`: given a new baseline, it changes the baseline version of doc filenames and components and images in it
- `set-image-digests`: updates image digests for one specific image or all stale images
- `show-component-baseline-version`: get the version of component, given the baseline version and the component name
- `strip-utf8-bom`: strip the utf8-bom of `charts/podiumd/values.yaml`
- `update-component-version`: update the version of component, given component name, app-version and helm-version
- `update-image-version`: update the version of image, given image name and version
- `update-podiumd-readme`: re-generate `charts/podiumd/README.md` using `helm-doc`
- `verify-helmchart-version`: verify that a helm-chart exists, given component name and version 
- `verify-image-version`: verify that an image exists, given image name and version
- `verify-podiumd`: verify podiumd's consistency, references, policies 
- `verify-release-table-with-podiumd`: verify the confluence exported release table against podiumd's implementation
