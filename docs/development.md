# Development instructions

How we work in the helm-charts repository. The details live in
[README.md](../README.md#branching-strategy) and
[`.github/copilot-instructions.md`](../.github/copilot-instructions.md);
this page only lists the rules.

## PodiumD chart

### Branches

- Work for release X.Y.Z goes on `feature/podiumd-<X.Y.Z>-<topic>`, branched
  from `feature/podiumd-<X.Y.Z>`, and its PR targets that release branch.
- Only squash merges; history stays linear. Never merge the release branch
  into your branch: rebase your own commits onto it
  (`git rebase --onto origin/feature/podiumd-<X.Y.Z> <old-base>`).

### Making changes

- Change the chart (`charts/podiumd/`), never a running cluster or container.
  On AKS-blue only read-only commands (`kubectl get/logs/describe`,
  `helm status`); everything else goes through the pipeline.
- Configure a component only through its own image, the documented values of
  its Helm chart and its APIs:
  - Avoid `extraEnvVars`, `extraEnv`, `extraVolumes` and similar escape
    hatches. When the chart lacks a setting, request the change in the
    component's Helm chart (an issue or PR upstream) instead of working
    around it here.
  - Do not script inside containers: no `kubectl exec`, no shell commands or
    wrapper scripts that change a running container.
  - Do not copy data into containers: no `kubectl cp`, no files written into
    a container's filesystem.
  - Avoid volumes to inject information (ConfigMap or Secret files, init
    containers that write files). Use one only when the component offers no
    other way, and say why in the PR.
- Every container has CPU/memory requests and limits.
- Images use `{{ include "podiumd.image" ... }}` with a digest-pinned tag in
  `values.yaml`; never a plain `repo:tag` string in a template.
- A component or image version change also updates the release's upgrade
  guide (`charts/podiumd/docs/_UPGRADE_PATHS/<prev>-to-<version>-upgrade.md`)
  and images manifest (`charts/podiumd/docs/images/images-<version>.yaml`);
  run `charts/podiumd/bin/fix-doc-consistency` instead of editing the
  generated lines by hand.
- Keycloak realm security changes are logged in
  `charts/podiumd/docs/apps/keycloak/keycloak-security-updates.md`.

### Before you open a PR

- `charts/podiumd/bin/verify-podiumd --skip=cve-scan,cve-diff` passes
  (BOM, duplicate keys, lint, render, Markdown, doc consistency, digests).
- The full `verify-podiumd`, CVE steps included, passes before the PR is
  marked ready and before a release.
- Changed Markdown has no pymarkdown findings.

### Review

A reviewer checks that:

- the change covers the acceptance criteria of the story (Jira key in the
  PR title or description);
- the upgrade guide tells an operator everything they must do (new images to
  mirror, values to change, manual steps);
- `verify-podiumd` passes on the branch.
