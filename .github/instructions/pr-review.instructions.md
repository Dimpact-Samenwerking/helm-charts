---
applyTo: "**"
excludeAgent: "cloud-agent"
---

# Review: every pull request

- The PR targets the branch its name belongs to:
  `feature/podiumd-<X.Y.0>-*` targets `feature/podiumd-<X.Y.0>`, and only a
  finished release branch targets `main`.
- The PR contains only its own commits. Flag commits that belong to the
  release branch or to another PR: the branch was merged instead of rebased.
- The description follows the PR template. Flag a missing `Solves IN-xxxx` (or "none"), an
  "Effect on values and upgrade" section that is empty instead of "None",
  and checks listed without their result. A check that did not run, or a
  change that was not tested, is named under **Not run** or **Not tested**.
- A release PR (`feature/podiumd-<X.Y.0>` into `main`) uses the release
  layout instead: Upgrade paths, Component changes, Fixes and changes,
  Status.
- Commit messages use `<type>(<scope>): <description>` with type `feat`,
  `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `perf` or `style`.
- Flag committed local files: `.DS_Store`, `cve-scan-cache.json`,
  `image-upgrade-cache.json`, `node_modules/`.
- Flag passwords, tokens, client secrets, private keys and connection strings
  with credentials in any file, including docs and examples.
- Flag `helm install`, `helm upgrade`, `kubectl apply` or `kubectl delete`
  instructions aimed at aks-blue clusters: changes there go through the
  pipeline. Read-only `kubectl` commands must pass `--context`.
