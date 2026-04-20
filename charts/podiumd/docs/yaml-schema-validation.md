---
title: YAML/JSON Schema validation for `values.yaml`
---

Why you see schema validation errors
-------------------------------

`charts/podiumd/values.yaml` contains an editor directive at the top that tells the YAML language server to validate the file with a JSON Schema:

```yaml
# yaml-language-server: $schema=./kiss.schema.json
```

That schema used to only declare the `kiss` subtree, so the language server flagged many other top-level keys (for example `keycloak`, `global`, `persistentVolume`, etc.) as "not declared in schema". Those editor/IDE inspection results are surfaced during commits as warnings or errors depending on your IDE settings.

What we changed
----------------

To avoid spurious errors while keeping validation for the KISS subtree, `kiss.schema.json` was updated to declare a root object and allow other top-level keys:

- it keeps the `$ref` to the upstream KISS values schema for the `kiss` key
- it sets `additionalProperties: true` so unrelated top-level keys are not treated as errors

This is a conservative, low-risk change that preserves useful validation for KISS-specific config while preventing false positives for the umbrella chart's many other settings.

How to avoid warnings in your IDE
--------------------------------

If you still see warnings during commit, here are recommended options:

1. Temporarily skip code analysis during a commit
   - In JetBrains IDEs (IntelliJ/PyCharm/IDEA family): in the Commit dialog uncheck "Analyze code" or "Perform code analysis".

2. Permanently disable pre-commit code analysis
   - File > Settings > Version Control > Commit — uncheck "Perform code analysis" under "Before Commit".

3. Adjust YAML/JSON schema inspection severity
   - File > Settings > Editor > Inspections. Search for YAML/JSON schema validation and lower its severity or disable it. You can also create an inspection scope to exclude `charts/podiumd/values.yaml`.

4. Remove the schema directive in `values.yaml`
   - Delete or comment out the `# yaml-language-server: $schema=./kiss.schema.json` line. This disables schema validation for the file entirely (you lose KISS-specific validation).

5. Produce a complete schema for the umbrella chart (long-term)
   - Create a combined JSON Schema that documents every top-level key used in `values.yaml`. This is the most accurate approach but requires significant maintenance as the chart evolves.

Notes and recommendations
-------------------------
- The current change in `kiss.schema.json` (allowing additional properties) is intentionally conservative: it retains helpful validation where it matters and prevents annoying, false-positive errors.
- If you prefer a different approach (remove the schema directive, or create a stricter combined schema), say which and I can make that change.
- This file documents why the change was made so future contributors understand the rationale.

Related files
-------------
- `charts/podiumd/kiss.schema.json` — the JSON Schema used by the YAML language server for `values.yaml`
- `charts/podiumd/values.yaml` — the values file that includes the `$schema` directive

---
Last updated: April 20, 2026

