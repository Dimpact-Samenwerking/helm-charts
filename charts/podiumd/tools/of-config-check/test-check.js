// Offline tests with deliberately broken forms; the bookmarklet is up to date and its
// minified code gives the same findings as the source: npm test
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const core = require("./form-config-check.js");
const { buildBookmarklet, TARGET } = require("./build-bookmarklet.js");
const staticVariables = [{ key: "today", dataType: "date" }];
const steps = [{
  uuid: "s1", name: "Stap 1",
  configuration: { components: [
    { key: "a", type: "number", label: "Bedrag A" },
    { key: "b", type: "number", label: "Bedrag B" },
    { key: "totaal", type: "textfield", label: "Totaal", disabled: true },
    { key: "verborgen", type: "textfield", label: "Verborgen", hidden: true },
    { key: "fs", type: "fieldset", components: [{ key: "kinderen", type: "editgrid", label: "Kinderen",
      components: [{ key: "naam", type: "textfield", label: "Naam" }] }] },
  ] },
}];
const variables = [
  { key: "a", dataType: "float", source: "component", initialValue: null },
  { key: "b", dataType: "float", source: "component", initialValue: "" },
  { key: "totaal", dataType: "string", source: "component", initialValue: "" },
  { key: "verborgen", dataType: "string", source: "component", initialValue: 5 },
  { key: "kinderen", dataType: "array", source: "component", initialValue: [] },
  { key: "aantal", name: "Aantal", dataType: "int", source: "user_defined", initialValue: "3" },
  { key: "half", name: "Half", dataType: "int", source: "user_defined", initialValue: 0 },
];
const rules = [
  { description: "Totaal berekenen", order: 0, jsonLogicTrigger: { "!!": [{ var: "a" }] },
    actions: [{ variable: "totaal", action: { type: "variable", value: { "+": [{ var: "a" }, { var: "b" }] } } }] },
  { description: "Oud veld", order: 1, jsonLogicTrigger: { "==": [{ var: "oudVeld" }, "x"] },
    actions: [{ component: "weg", action: { type: "property", property: { value: "hidden" }, state: true } }] },
  { description: "Scopes en statisch", order: 2, jsonLogicTrigger: { ">": [{ var: "today" }, { var: "kinderen.0.naam" }] },
    actions: [{ variable: "aantal", action: { type: "variable",
      value: { reduce: [{ var: "kinderen" }, { "+": [{ var: "accumulator" }, 1] }, 0] } } },
      { variable: "half", action: { type: "variable", value: { "/": [{ var: "aantal" }, 2] } } },
      { variable: "bestaatNiet", action: { type: "variable", value: "x" } },
      { formStepUuid: "s9", action: { type: "step-not-applicable" } }] },
  { description: "Verborgen veld", order: 3, jsonLogicTrigger: true,
    actions: [{ variable: "verborgen", action: { type: "variable", value: { "*": [2, 3] } } }] },
];
const { findings } = core.checkForm({ form: {}, steps, variables, rules, staticVariables });
const got = findings.map((f) => `${f.severity}|${f.check}|${f.target.text.split("  ")[0]}`).sort();
console.log(got.join("\n"));
const expect = [
  "FOUT|Beginwaarde|Aantal",
  "FOUT|Beginwaarde|Verborgen",
  "FOUT|Type berekening|Totaal",
  "FOUT|Type berekening|Verborgen",
  "FOUT|Verwijzing|'bestaatNiet' in de actie (doelvariabele)",
  "FOUT|Verwijzing|'oudVeld' in de voorwaarde",
  "FOUT|Verwijzing|'stap s9' in de actie (stap)",
  "FOUT|Verwijzing|'weg' in de actie (veld eigenschap wijzigen)",
  "LET OP|Type berekening|Half",
].sort();
assert.deepStrictEqual(got, expect);
const totaal = findings.find((f) => f.target.text.startsWith("Totaal"));
assert.match(totaal.problem, /De gebruiker ziet/);
const verborgen = findings.find((f) => f.check === "Type berekening" && f.target.text.startsWith("Verborgen"));
assert.match(verborgen.problem, /verborgen/);
assert.strictEqual(core.literalHint("number", "3"), 'Schrijf de waarde zonder aanhalingstekens: 3 in plaats van "3".');
// ---- Open Forms 4.0 upgrade checks -------------------------------------------

const step = (uuid, index, name, components) => ({ uuid, index, name, configuration: { components } });
const rule = (order, trigger, actions, extra = {}) => ({ order, description: `regel ${order + 1}`, jsonLogicTrigger: trigger, actions, ...extra });
const setVar = (variable, value) => ({ variable, action: { type: "variable", value } });
const v = (key, dataType, source = "component", extra = {}) => ({ key, dataType, source, initialValue: null, ...extra });
const summary = (found) => found.map((f) => `${f.severity}|${f.check}|${f.target.text}${f.rule ? `|${f.rule}` : ""}`).sort();

const upgradeSteps = [
  step("s1", 0, "Stap 1", [
    { key: "keuze", type: "textfield", label: "Keuze" },
    { key: "optie", type: "textfield", label: "Optie", conditional: { show: true, when: "keuze", eq: "ja" } },
    { key: "uitkomst", type: "textfield", label: "Uitkomst" },
    { key: "bijlage", type: "file", label: "Bijlage", registration: { documentType: { catalogue: { domain: "B", rsin: "1" } } } },
    { key: "bijlageGoed", type: "file", label: "Bijlage goed",
      registration: { documentType: { catalogue: { domain: "A", rsin: "1" } }, informatieobjecttype: "https://elders.nl/catalogi/iot/1" } },
  ]),
  step("s2", 1, "Stap 2", [{ key: "later", type: "textfield", label: "Later" }]),
];
const upgradeVariables = [
  v("keuze", "string"), v("optie", "string"), v("uitkomst", "string"), v("later", "string"),
  v("bijlage", "array"), v("bijlageGoed", "array"),
  v("x", "int", "user_defined"), v("y", "int", "user_defined"), v("teller", "int", "user_defined"),
  v("w", "int", "user_defined"), v("eigen", "string", "user_defined"),
];
const upgradeRules = [
  // x and y set each other: a cycle.
  rule(0, { "!!": [{ var: "x" }] }, [setVar("y", { "+": [{ var: "x" }, 1] })]),
  rule(1, { "!!": [{ var: "y" }] }, [setVar("x", { "+": [{ var: "y" }, 1] })]),
  // teller = teller + 1: a self cycle.
  rule(2, true, [setVar("teller", { "+": [{ var: "teller" }, 1] })]),
  // w is set by one action and read by the next: a valid self cycle.
  rule(3, true, [setVar("w", 1), setVar("uitkomst", { cat: [{ var: "w" }] })]),
  // Compares a conditionally hidden field with its empty value: 4.0 change.
  rule(4, { "==": [{ var: "optie" }, ""] }, [setVar("uitkomst", "leeg")]),
  // Same, with a default value: fine.
  rule(5, { "==": [{ var: ["optie", ""] }, ""] }, [setVar("uitkomst", "leeg")]),
  // Runs on step 1 but compares a step-2 field with its empty value.
  rule(6, { "==": [{ var: "later" }, ""] }, [setVar("uitkomst", "x")]),
  // "Disable next": trigger without fields, trigger with an own variable, trigger with a step field.
  rule(7, true, [{ formStepUuid: "s1", action: { type: "disable-next" } }]),
  rule(8, { "==": [{ var: "eigen" }, "x"] }, [{ formStepUuid: "s1", action: { type: "disable-next" } }]),
  rule(9, { "==": [{ var: "keuze" }, "x"] }, [{ formStepUuid: "s1", action: { type: "disable-next" } }]),
];
const upgradeForm = (extra) => ({
  newLogicEvaluationEnabled: false,
  registrationBackends: [{ backend: "objects_api", name: "Objecten",
    options: { catalogue: { rsin: "1", domain: "A" }, objectsApiGroup: 1, documentUrl: "https://elders.nl/documenten/1" } }],
  ...extra,
});
const check = (form, rules = upgradeRules) => core.checkForm({
  form, steps: upgradeSteps, variables: upgradeVariables, rules, staticVariables, serviceRoots: ["https://openzaak.nl/"],
}).findings.filter((f) => !["Type berekening", "Verwijzing", "Beginwaarde"].includes(f.check));

const found35 = summary(check(upgradeForm()));
console.log(found35.join("\n"));
assert.deepStrictEqual(found35, [
  "CONTROLEREN|Verbergen (4.0)|later|nr. 7: regel 7",
  "CONTROLEREN|Verbergen (4.0)|optie|nr. 5: regel 5",
  "CONTROLEREN|Volgende-knop|'Volgende uitschakelen'|nr. 8: regel 8",
  "CONTROLEREN|Volgende-knop|'Volgende uitschakelen'|nr. 9: regel 9",
  "FOUT|Catalogus|Bijlage  (sleutel 'bijlage', type file, stap 'Stap 1')",
  "FOUT|Logica 4.0|logica-evaluatie",
  "FOUT|Logica-cyclus|teller|nr. 3: regel 3",
  "FOUT|Logica-cyclus|x, y|nr. 1: regel 1 | nr. 2: regel 2",
  "FOUT|Onbekende service|Bijlage goed  (sleutel 'bijlageGoed', type file, stap 'Stap 1')",
  "FOUT|Onbekende service|Objecten  (objects_api)",
].sort());

// New logic evaluation on, with "trigger from step": only that rule is reported as Logica 4.0.
const withTriggerStep = summary(check(upgradeForm({ newLogicEvaluationEnabled: true }),
  [rule(0, true, [setVar("uitkomst", "x")], { triggerFromStep: "https://x/api/v2/forms/f/steps/s1" })]));
assert.deepStrictEqual(withTriggerStep.filter((f) => f.includes("Logica 4.0")),
  ["FOUT|Logica 4.0|'Trigger vanaf stap' is ingesteld|nr. 1: regel 1"]);

// Open Forms 4.0 (no newLogicEvaluationEnabled in the API): no 3.5-only checks.
const { newLogicEvaluationEnabled: _unused, ...form40 } = upgradeForm();
const found40 = summary(check(form40));
assert.ok(!found40.some((f) => f.includes("Logica 4.0") || f.includes("Volgende-knop")), found40.join("\n"));
assert.ok(found40.some((f) => f.includes("Logica-cyclus")));

// Without the services list the service check is skipped.
const noServices = core.checkForm({
  form: form40, steps: upgradeSteps, variables: upgradeVariables, rules: [], staticVariables, serviceRoots: null,
}).findings;
assert.ok(!noServices.some((f) => f.check === "Onbekende service"));

// ---- Koppelingen --------------------------------------------------------------

const ok = (data) => Promise.resolve({ data });
const fail = (status) => Promise.resolve({ error: new Error(`${status} bij https://open-forms/api/v2/...`) });
const catalogueA = { domain: "ABCD", rsin: "123", label: "Catalogus A", url: "https://catalogi/a" };
const stubResolver = {
  objecttypes: (group) => (group === "objecten"
    ? ok([{ uuid: "ot-1", url: "https://objecttypen/ot-1", name: "Aanvraag" }])
    : fail(500)),
  versions: (_group, uuid) => ok(uuid === "ot-1" ? [{ version: 1, status: "published" }, { version: 2, status: "draft" }] : []),
  catalogues: (api) => (api.group === 9 ? fail(400) : ok([catalogueA])),
  documentTypes: (api, _url, caseType) => ok(api.kind === "zgw" && caseType === "ZT-1"
    ? [{ description: "Aanvraag", isPublished: true }]
    : [{ description: "Bijlage", isPublished: true }, { description: "Concept doc", isPublished: false }]),
  caseTypes: () => ok([{ identification: "ZT-1", isPublished: true }, { identification: "ZT-C", isPublished: false }]),
  roleTypes: () => ok([{ description: "Behandelaar" }]),
  products: () => ok([{ url: "https://producten/1" }]),
};
const linkForm = {
  registrationBackends: [
    { name: "Objecten", backend: "objects_api", options: {
      objectsApiGroup: "objecten", objecttype: "ot-1", objecttypeVersion: 2, catalogue: { domain: "ABCD", rsin: "123" },
      iotSubmissionReport: "Bijlage", iotAttachment: "Bestaat niet", files: [{ key: "bijlage", documentTypeDescription: "Concept doc" }],
    } },
    { name: "Weg", backend: "objects_api", options: { objectsApiGroup: "objecten", objecttype: "ot-x", objecttypeVersion: 1 } },
    { name: "Zaak", backend: "zgw-create-zaak", options: {
      zgwApiGroup: 1, catalogue: { domain: "ABCD", rsin: "123" }, caseTypeIdentification: "ZT-1",
      documentTypeDescription: "Aanvraag", medewerkerRoltype: "Onbekend", productUrl: "https://producten/2",
      objectsApiGroup: "objecten", objecttype: "https://objecttypen/ot-1", objecttypeVersion: 1,
    } },
    { name: "Zaak2", backend: "zgw-create-zaak", options: { zgwApiGroup: 1, catalogue: { domain: "XYZ", rsin: "999" } } },
    { name: "Zaak3", backend: "zgw-create-zaak", options: {
      zgwApiGroup: 1, catalogue: { domain: "ABCD", rsin: "123" }, caseTypeIdentification: "ZT-weg", documentTypeDescription: "Aanvraag",
    } },
    { name: "Zaak4", backend: "zgw-create-zaak", options: { zgwApiGroup: 9, catalogue: { domain: "ABCD", rsin: "123" } } },
    { name: "Mail", backend: "email", options: { toEmails: ["a@example.org"] } },
  ],
};
const linkVariables = [
  { key: "profiel", name: "Profiel", prefillPlugin: "objects_api", prefillOptions: { objectsApiGroup: "kapot", objecttypeUuid: "ot-1", objecttypeVersion: 1 } },
  { key: "gewoon", name: "Gewoon", prefillPlugin: "", prefillOptions: {} },
];
const linkSummary = (found) => found.map((f) => `${f.severity}|${f.target.text}|${f.problem}`).sort();
const expectedLinks = [
  "CONTROLEREN|Profiel  (sleutel 'profiel')|De objecttypen van API-groep 'kapot' konden niet worden opgehaald: Open Forms kon de API niet bereiken of kreeg een fout terug.",
  "CONTROLEREN|Zaak4  (zgw-create-zaak)|De catalogi van API-groep '9' konden niet worden opgehaald: de API-groep bestaat niet (meer) of is niet volledig ingesteld.",
  "FOUT|Objecten  (objects_api)|Documenttype 'Bestaat niet' bestaat niet (meer) in catalogus 'Catalogus A'.",
  "FOUT|Weg  (objects_api)|Objecttype ot-x bestaat niet (meer) in de Objecttypen van API-groep 'objecten'.",
  "FOUT|Zaak  (zgw-create-zaak)|Product https://producten/2 hoort niet (meer) bij een geldige versie van zaaktype 'ZT-1'.",
  "FOUT|Zaak  (zgw-create-zaak)|Roltype 'Onbekend' bestaat niet (meer) bij zaaktype 'ZT-1'.",
  "FOUT|Zaak2  (zgw-create-zaak)|Catalogus XYZ (RSIN 999) bestaat niet (meer) in API-groep '1'.",
  "FOUT|Zaak3  (zgw-create-zaak)|Zaaktype 'ZT-weg' bestaat niet (meer) in catalogus 'Catalogus A'.",
  "LET OP|Objecten  (objects_api)|Documenttype 'Concept doc' in catalogus 'Catalogus A' is nog een concept.",
  "LET OP|Objecten  (objects_api)|Versie 2 van objecttype 'Aanvraag' heeft status 'draft', niet 'published'.",
].sort();

// ---- The minified bookmarklet ------------------------------------------------

(async () => {
  const bookmarklet = await buildBookmarklet();
  assert.ok(fs.readFileSync(TARGET, "utf8") === bookmarklet,
    "form-config-check.bookmarklet.txt is out of date: run npm run build");

  // The minified code must give exactly the same findings as the source.
  const minifiedModule = { exports: {} };
  const code = decodeURIComponent(bookmarklet.trim().slice("javascript:".length));
  new Function("module", code)(minifiedModule);
  const minified = minifiedModule.exports;
  const inputs = [
    { form: {}, steps, variables, rules, staticVariables },
    { form: upgradeForm(), steps: upgradeSteps, variables: upgradeVariables, rules: upgradeRules, staticVariables,
      serviceRoots: ["https://openzaak.nl/"] },
    { form: form40, steps: upgradeSteps, variables: upgradeVariables, rules: upgradeRules, staticVariables, serviceRoots: null },
  ];
  for (const input of inputs) {
    assert.deepStrictEqual(minified.checkForm(input), core.checkForm(input));
  }

  // Koppelingen, with the source and with the minified code.
  for (const lib of [core, minified]) {
    const found = await lib.checkLinks(lib.linkReferences(linkForm, linkVariables), stubResolver);
    assert.deepStrictEqual(linkSummary(found), expectedLinks);
  }

  // The resolver fetches each list once and turns a failed fetch into {error}.
  const fetched = [];
  const fakeGetJson = (url) => {
    fetched.push(url);
    return url.includes("kapot") ? Promise.reject(new Error("500 bij x")) : Promise.resolve([]);
  };
  const resolver = core.makeLinkResolver(fakeGetJson, "https://h/api/v2");
  await resolver.objecttypes("objecten");
  await resolver.objecttypes("objecten");
  const broken = await resolver.objecttypes("kapot");
  assert.strictEqual(fetched.length, 2);
  assert.strictEqual(fetched[0], "https://h/api/v2/objects-api/object-types?objects_api_group=objecten");
  assert.ok(broken.error);
  const docs = await resolver.documentTypes({ kind: "zgw", group: 1 }, "https://catalogi/a", "ZT-1");
  assert.deepStrictEqual(docs, { data: [] });
  assert.strictEqual(fetched[2],
    "https://h/api/v2/registration/plugins/zgw-api/document-types?zgw_api_group=1&catalogue_url=https%3A%2F%2Fcatalogi%2Fa&case_type_identification=ZT-1");
  const results = inputs.map((input) => ({ form: { name: "x", uuid: "u", active: true, ...input.form }, result: core.checkForm(input) }));
  const meta = { host: "h", date: "d", adminBase: "https://h", errors: [], serviceRoots: [] };
  assert.strictEqual(minified.formatReport(results, meta), core.formatReport(results, meta));
  console.log(`OK: all expectations met (bookmarklet ${bookmarklet.length} characters, minified matches source)`);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
