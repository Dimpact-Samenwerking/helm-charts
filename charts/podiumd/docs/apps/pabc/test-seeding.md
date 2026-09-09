# pabc - declarative base authorisation setup (new, opt-in)

PodiumD 4.9.1 can seed the PABC base setup from the chart itself, so a fresh
environment no longer needs its roles and mappings clicked together by hand.
`pabc-migrations` only creates the schema on an empty database, and ZAC blocks
every page with "u heeft geen toestemming om deze pagina te bekijken" for as
long as PABC holds no application roles.

- `pabc.datasetConfigMap.enabled` (new, default `false`) renders
  `files/pabc-dataset.json` into the `pabc-dataset` ConfigMap.
- `pabc.seedJob.enabled` (new, default `false`) runs the `pabc-migrations`
  image once against that dataset.
- No image change: the seed Job reuses `pabc.migrations.image`.

Both default to `false`, so this hop changes nothing unless an environment
opts in. **Seeding replaces all PABC content**, so leave it disabled on any
environment that has been curated through the PABC UI. See
[values-deltas](4.9.0-to-4.9.1-values-deltas.md) § "pabc 1.1.1" for the full
story, and [`pabc-iam-migration.md`](../apps/pabc/pabc-iam-migration.md) for
switching an environment over from the old IAM setup.
