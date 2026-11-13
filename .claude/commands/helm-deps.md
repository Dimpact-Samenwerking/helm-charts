Update and rebuild the podiumd Helm chart dependencies.

Run these commands from the repo root:

```bash
cd charts/podiumd && helm dependency update && helm dependency build
```

After completion:
- Report which dependencies were updated (compare Chart.lock before/after if needed).
- Remind the user to commit only `Chart.yaml`: `Chart.lock` and the `.tgz` files in `charts/podiumd/charts/` are gitignored.
