Lint the podiumd Helm chart.

```bash
helm lint charts/podiumd
```

If $ARGUMENTS contains a values file path, also lint with that file:

```bash
helm lint charts/podiumd -f $ARGUMENTS
```

Report all warnings and errors. For errors, diagnose the root cause and suggest fixes.
