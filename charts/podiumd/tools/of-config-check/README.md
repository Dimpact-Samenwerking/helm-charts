# Open Forms config check

Scripts that check the configuration of Open Forms forms. They run in the
browser of a form maintainer who is logged in to the Open Forms admin, and use
the admin API with that session. They only read; nothing in Open Forms changes.

| File | Purpose |
| --- | --- |
| `form-config-check.js` | The configuration check (source; also runs in the browser console) |
| `form-config-check.bookmarklet.txt` | The same script, minified, as a bookmark; generated from the source |
| `build-bookmarklet.js` | Regenerates the bookmarklet after a change to the source (`npm run build`) |
| `test-check.js` | Offline tests with deliberately broken forms, and a check that the bookmarklet is up to date and gives the same findings as the source (`npm test`) |
| `package.json`, `package-lock.json` | The minifier ([terser](https://terser.org/)), pinned |

## What the configuration check reports

The report is in Dutch, grouped per form. Deleted forms are skipped. The
first lines say whether the environment runs Open Forms 3.5 or 4.0; the checks
marked "3.5 only" run only on 3.5, where they prepare the upgrade to 4.0.

| Check | Finds |
| --- | --- |
| Type berekening | A "waarde instellen" logic action writes a value of another type than the field or variable expects, e.g. a sum into a read-only text field |
| Verwijzing | Logic that uses a field, variable or step that does not exist (anymore), e.g. after renaming a field |
| Beginwaarde | An initial value of the wrong type, e.g. `"3"` for a whole-number variable |
| Logica 4.0 | 3.5 only: a form with logic that still uses the old logic evaluation, or a rule with "trigger vanaf stap" under the new one. Both block the upgrade to Open Forms 4.0 |
| Logica-cyclus | Rules that set each other's input, or a rule that sets its own input (`x = x + 1`). Open Forms 4.0 refuses these |
| Volgende-knop | 3.5 only: a "Volgende uitschakelen" action whose step the 3.5 migration had to guess |
| Verbergen (4.0) | Logic that compares a hidden field, or a field on a later step, with its empty value. From Open Forms 4.0 such a value is missing instead of empty, so the rule can behave differently |
| Catalogus | A file upload field with another catalogue than the form's Objects API or ZGW registration |
| Onbekende service | A registration or file upload field that points at a URL for which no service is configured, e.g. another environment's URL |
| Koppeling | An objecttype (and its version), catalogue, zaaktype, document type, role type or product that an Objects API or ZGW registration, or an Objects API prefill, refers to, but that does not exist (anymore) or is a draft in the API behind the form's API group |

The Koppeling check asks Open Forms' own admin endpoints
(`/api/v2/objects-api/...` and `/api/v2/registration/plugins/zgw-api/...`),
which call Objecttypen and Catalogi with the API group's credentials. So it
tests exactly what Open Forms itself can reach. Each list is fetched once per
API group and catalogue. When Open Forms cannot fetch a list, the finding is
CONTROLEREN: an unknown API group (HTTP 400) or an API that Open Forms cannot
reach or that returns an error (HTTP 500).

The Logica 4.0 to Onbekende service checks follow Open Forms' own diagnostic scripts in `/app/bin`, which
the PodiumD 4.10 upgrade guide runs with `kubectl exec`:

| Check | Open Forms script |
| --- | --- |
| Logica 4.0, Logica-cyclus | `report_invalid_form_logic.py` |
| Volgende-knop | `check_disable_next_logic_action.py` |
| Verbergen (4.0) | `report_logic_with_deprecated_clear_on_hide_behavior.py` |
| Catalogus | `report_file_component_inconsistent_catalogues.py` |
| Onbekende service | `NO_SERVICE` of PodiumD's `scripts/openforms-check-registration-options.py` |

Rule numbers in the report count from 1, in the order of the admin's Logica
tab; Open Forms' clear-on-hide script counts from 0.

Severity:

- **FOUT**: wrong type, broken reference, or something that blocks the
  upgrade to Open Forms 4.0. On a visible field with a wrong type the user
  sees "Verwachtte type X maar kreeg Y"; on a hidden field or a user-defined
  variable there is no message, but registration, later calculations or
  templates can go wrong.
- **LET OP**: a division is written to a whole-number variable and can give a
  decimal number, or a linked objecttype version, zaaktype or document type
  is a draft.
- **CONTROLEREN**: check by hand. The type of a calculation's result cannot
  be derived, a rule may behave differently from Open Forms 4.0, or Open
  Forms could not fetch a list for the Koppeling check.

Each finding names the field, variable or registration, the logic rule, the
problem, a suggested fix and the calculation or value. The form link searches
the admin by the form's UUID.

Not checked:

- Prefill, fetch-from-service and DMN results: only known while a form is
  filled in.
- Submissions, templates and registration mappings.
- For the Koppeling check: individual objects in Objecten (forms do not refer
  to them), zaaktype properties (eigenschappen) and the target paths of a
  variables mapping. On Open Forms 3.5, a registration without its own
  catalogue uses the API group's; that fallback is not followed.
- The `V1_KEYS` and `INVALID` checks of `openforms-check-registration-options.py`:
  they need Open Forms' server-side validation. Run that script with
  `kubectl exec` as in the upgrade guide.
- Server certificate bundles of services: an admin setting, not part of the
  forms.

## Running the check

Requirements: an Open Forms admin account that is staff and has the
permission **"forms.change_form"** (the right to edit forms).

Run it on one environment at a time: the check reads the forms of the Open
Forms whose admin you are logged in to.

### Option 1: browser console

1. Log in to the Open Forms admin, e.g. `https://<open-forms-host>/admin/`.
2. Open the developer tools (F12) and go to the **Console** tab.
3. Paste the full content of `form-config-check.js` and press Enter. Chrome
   and Edge first ask you to type `allow pasting`.
4. A panel opens over the page. It shows the progress per form and then the
   report.

### Option 2: bookmark

Set up once:

1. Create a new bookmark in your browser (any page, then edit it).
2. Name it, e.g. "Open Forms controle".
3. Replace the URL with the full content of
   `form-config-check.bookmarklet.txt` (one long line of about 37,000
   characters, starting with `javascript:`).

Run it: open any page of the Open Forms admin and click the bookmark.

### The report

The panel has three buttons:

- **Kopiëren**: copies the report to the clipboard.
- **Download .txt**: saves it as `openforms-controle-<host>.txt`.
- **Sluiten**: closes the panel.

Messages instead of a report:

- "Start deze controle vanuit de Open Forms beheeromgeving": the current
  page is not under `/admin/`.
- "geen toegang": the account lacks staff status or the "forms.change_form"
  permission.
- "Niet gecontroleerd (fout bij ophalen)" at the end of the report: those
  forms could not be read; the rest of the report is complete.
- "de services konden niet worden opgehaald" at the top of the report: the
  "Onbekende service" check was skipped; all other checks ran.

## Changing the script

The checks are plain functions at the top of `form-config-check.js`; the part
after "Browser part" only fetches data and shows the panel. The checks are
written against the admin API of Open Forms 3.5.14 and 4.0.x.

The bookmarklet is the source minified with terser, so the source can keep
its comments and readable names. Install the pinned terser once:

```bash
npm ci
```

After every change to `form-config-check.js`, run:

```bash
npm run build
npm test
```

`npm test` fails when the bookmarklet is out of date, or when the minified
code gives other findings than the source.
