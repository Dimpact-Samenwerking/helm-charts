/*
 * Open Forms configuratiecontrole (browser).
 *
 * Read-only. Run it in the browser while logged in to the Open Forms admin
 * (page under /admin/), as a bookmarklet or pasted into the console. It reads
 * all forms through the admin API (/api/v2/...) with the admin session and
 * shows a report in Dutch on top of the page.
 *
 * Needs: a staff account with the "forms.change_form" permission.
 *
 * Checks per form (deleted forms are not returned by the API):
 *   Type berekening  a "set value" logic action writes a value of another
 *                    type than the target field or variable expects
 *   Verwijzing       logic refers to a field, variable or step that does
 *                    not exist (anymore)
 *   Beginwaarde      the initial value of a variable or field has the wrong
 *                    type
 *   Logica 4.0       (3.5 only) the form still uses the old logic evaluation,
 *                    or a rule has "trigger from step" with the new one
 *   Logica-cyclus    rules that set each other's input (or their own)
 *   Volgende-knop    (3.5 only) a "disable next" action whose step the
 *                    migration had to guess
 *   Verbergen (4.0)  logic that compares a hidden or later-step field with an
 *                    empty value; behaves differently from Open Forms 4.0
 *   Catalogus        a file upload field uses another catalogue than the
 *                    form's ZGW or Objects API registration
 *   Onbekende service  a registration or file upload field points at a URL
 *                    without a configured service
 *   Koppeling        an objecttype (and version), catalogue, zaaktype,
 *                    document type, role type or product that a registration
 *                    or Objects API prefill refers to, does not exist (or is a
 *                    draft) in the API behind the form's API group; checked
 *                    through Open Forms' own admin endpoints
 *
 * The 4.0 checks follow Open Forms' own scripts in /app/bin
 * (report_invalid_form_logic, check_disable_next_logic_action,
 * report_logic_with_deprecated_clear_on_hide_behavior,
 * report_file_component_inconsistent_catalogues) and PodiumD's
 * openforms-check-registration-options.py (NO_SERVICE).
 *
 * Severity:
 *   FOUT         wrong type, broken reference, or blocks the 4.0 upgrade
 *   LET OP       a division is written to a whole-number (int) variable, or a
 *                linked objecttype version, zaaktype or document type is a draft
 *   CONTROLEREN  needs a manual check: result type unknown, or a rule that
 *                may behave differently
 *
 * Written against Open Forms 3.5.14 and 4.0.x.
 */
(function () {
  "use strict";

  // Data types as the SDK checks them: dates and times are text in JSON.
  const DATA_TYPE_KIND = {
    string: "text", date: "text", datetime: "text", time: "text",
    int: "number", float: "number",
    boolean: "boolean", array: "array", object: "object",
  };
  const KIND_NL = {
    text: "tekst", number: "getal", boolean: "ja/nee", array: "lijst",
    object: "object", date: "datum",
  };
  // A date result (date, today, date arithmetic) is stored as text.
  const COMPATIBLE = { text: ["text", "date"] };

  const NUMBER_OPS = new Set(["+", "-", "*", "/", "%", "min", "max"]);
  const TEXT_OPS = new Set(["cat", "substr"]);
  const BOOLEAN_OPS = new Set(["==", "===", "!=", "!==", "<", ">", "<=", ">=", "!", "!!", "in"]);
  const ARRAY_OPS = new Set(["map", "filter", "merge"]);
  const DATE_OPS = new Set(["date", "datetime", "today"]);
  const DELTA_OPS = new Set(["rdelta", "duration"]);
  const BRANCH_OPS = new Set(["if", "?:"]);
  // Operators whose later arguments run with their own "var" scope.
  const SCOPED_OPS = new Set(["map", "filter", "all", "some", "none", "reduce"]);
  const SEVERITY_ORDER = ["FOUT", "LET OP", "CONTROLEREN"];

  const isPlainObject = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
  const show = (x) => JSON.stringify(x);

  function varName(args) {
    const name = Array.isArray(args) ? args[0] : args;
    return typeof name === "string" ? name : null;
  }

  function valueKind(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value === "boolean") return "boolean";
    if (typeof value === "number") return "number";
    if (typeof value === "string") return "text";
    if (Array.isArray(value)) return "array";
    return "object";
  }

  /** Possible result kinds of a JSON-logic expression; "unknown" when not derivable. */
  function resultKinds(expr, varTypes) {
    if (!isPlainObject(expr)) return new Set([valueKind(expr)]);
    const ops = Object.keys(expr);
    if (ops.length !== 1) return new Set(["unknown"]);
    const op = ops[0];
    const args = expr[op];
    const argList = Array.isArray(args) ? args : [args];
    if (NUMBER_OPS.has(op)) {
      if ((op === "+" || op === "-") && argList.some((a) => {
        const kinds = resultKinds(a, varTypes);
        return kinds.has("date") || kinds.has("delta");
      })) {
        return new Set([op === "+" || argList.length === 2 ? "date" : "unknown"]);
      }
      return new Set(["number"]);
    }
    if (TEXT_OPS.has(op)) return new Set(["text"]);
    if (BOOLEAN_OPS.has(op)) return new Set(["boolean"]);
    if (ARRAY_OPS.has(op)) return new Set(["array"]);
    if (DATE_OPS.has(op)) return new Set(["date"]);
    if (DELTA_OPS.has(op)) return new Set(["delta"]);
    if (op === "var") {
      const kind = DATA_TYPE_KIND[varTypes[varName(args)]];
      return new Set([kind || "unknown"]);
    }
    if (op === "reduce" && Array.isArray(args) && args.length >= 3) {
      // The accumulator keeps the type of its start value.
      return resultKinds(args[2], varTypes);
    }
    if (BRANCH_OPS.has(op) && Array.isArray(args)) {
      const branches = args.filter((_, i) => i % 2 === 1);
      if (args.length % 2 === 1) branches.push(args[args.length - 1]);
      else if (args.length > 1) branches.push(null); // no else: the result can be null
      const kinds = new Set();
      for (const branch of branches) resultKinds(branch, varTypes).forEach((k) => kinds.add(k));
      return kinds;
    }
    return new Set(["unknown"]);
  }

  /** Every variable name an expression reads, outside the scoped arguments of map/filter/reduce/... */
  function referencedNames(expr, out = new Set()) {
    if (Array.isArray(expr)) {
      expr.forEach((e) => referencedNames(e, out));
      return out;
    }
    if (!isPlainObject(expr)) return out;
    for (const [op, args] of Object.entries(expr)) {
      if (op === "var") {
        const name = varName(args);
        if (name !== null) out.add(name);
        else referencedNames(args, out);
        if (Array.isArray(args)) referencedNames(args.slice(1), out);
      } else if (SCOPED_OPS.has(op) && Array.isArray(args)) {
        referencedNames(args[0], out);
        if (op === "reduce") referencedNames(args[2], out);
      } else {
        referencedNames(args, out);
      }
    }
    return out;
  }

  function* iterComponents(node, intoEditgrid = true) {
    if (Array.isArray(node)) {
      for (const child of node) yield* iterComponents(child, intoEditgrid);
      return;
    }
    if (!isPlainObject(node)) return;
    if (typeof node.key === "string" && typeof node.type === "string") yield node;
    if (node.type === "editgrid" && !intoEditgrid) return;
    for (const child of node.components || []) yield* iterComponents(child, intoEditgrid);
    for (const column of node.columns || []) yield* iterComponents(column, intoEditgrid);
  }

  const FIX_HINTS = {
    "text|number": "Zet de berekening in een 'cat', dan wordt de uitkomst tekst: " +
      '{"cat": [ <berekening> ]}. Of gebruik een getalveld als het veld een getal moet blijven.',
    "text|array": "De berekening geeft een lijst. Kies één element (bijv. " +
      '{"var": "veld.0"}), maak er tekst van, of gebruik een veld dat meerdere waarden accepteert.',
    "text|boolean": "De berekening geeft ja/nee. Gebruik een selectievakje, of zet het om " +
      'naar tekst met {"if": [ <voorwaarde>, "ja", "nee" ]}.',
    "number|text": 'De berekening geeft tekst. Zet het om naar een getal met {"+": [ <waarde> ]}, ' +
      "of gebruik een tekstveld.",
    "number|date": "Een datum past niet in een getalveld; gebruik een datumveld.",
  };

  function literalHint(expected, value) {
    if (expected === "number" && typeof value === "string") {
      const number = Number(value.replace(",", "."));
      if (value.trim() === "" || Number.isNaN(number)) {
        return `Gebruik een getal in plaats van de tekst ${show(value)}.`;
      }
      return `Schrijf de waarde zonder aanhalingstekens: ${show(number)} in plaats van ${show(value)}.`;
    }
    if (expected === "text" && ["number", "boolean"].includes(typeof value)) {
      return `Schrijf de waarde tussen aanhalingstekens: "${show(value)}" in plaats van ${show(value)}.`;
    }
    return `Vul een vaste waarde in van het type ${KIND_NL[expected] || expected}.`;
  }

  function fixHint(expected, got, expr) {
    if (!isPlainObject(expr)) return literalHint(expected, expr);
    return FIX_HINTS[`${expected}|${got}`] ||
      `Laat de berekening een ${KIND_NL[expected] || expected} opleveren, ` +
      `of wijzig het type van het veld naar ${KIND_NL[got] || got}.`;
  }

  function wrongKinds(targetKind, kinds) {
    const allowed = COMPATIBLE[targetKind] || [targetKind];
    return [...kinds].filter((k) => k !== "null" && !allowed.includes(k)).sort();
  }

  /** Field index of one form: key -> {label, type, step, hidden}. */
  function indexFields(steps, rules) {
    const fields = {};
    for (const step of steps) {
      for (const comp of iterComponents(step.configuration || {})) {
        const conditional = comp.conditional || {};
        fields[comp.key] = {
          label: comp.label || comp.key,
          type: comp.type,
          step: step.name,
          hidden: Boolean(comp.hidden || conditional.when),
        };
      }
    }
    for (const rule of rules) {
      for (const action of rule.actions || []) {
        const body = action.action || {};
        const prop = (body.property || {}).value;
        if (body.type === "property" && prop === "hidden" && fields[action.component]) {
          fields[action.component].hidden = true;
        }
      }
    }
    return fields;
  }

  function targetDescription(key, variable, field) {
    if (field) {
      return { label: "Veld", text: `${field.label}  (sleutel '${key}', type ${field.type}, stap '${field.step}')` };
    }
    const name = (variable && variable.name) || key;
    const dtype = variable ? variable.dataType : "?";
    return { label: "Variabele", text: `${name}  (sleutel '${key}', eigen variabele, type ${dtype})` };
  }

  function mismatchProblem(gotKinds, targetKind, isComponent, visible, what) {
    const got = gotKinds.map((k) => KIND_NL[k] || k).join(" of ");
    let problem = `${what} is een ${got}, maar ${isComponent ? "het veld" : "de variabele"} ` +
      `verwacht ${KIND_NL[targetKind]}.`;
    if (isComponent && visible) {
      const expected = targetKind === "text" ? "string" : targetKind;
      problem += ` De gebruiker ziet: "Verwachtte type ${expected} maar kreeg ...".`;
    } else if (isComponent) {
      problem += " Het veld is (soms) verborgen, dus de fout is niet altijd zichtbaar.";
    } else {
      problem += " Geen foutmelding op het scherm, maar registratie, latere berekeningen of sjablonen kunnen misgaan.";
    }
    return problem;
  }

  function checkTypes(ctx) {
    const findings = [];
    for (const rule of ctx.rules) {
      for (const action of rule.actions || []) {
        const body = action.action || {};
        if (body.type !== "variable") continue;
        const key = action.variable || "";
        const variable = ctx.variables[key];
        const targetKind = variable && DATA_TYPE_KIND[variable.dataType];
        if (!targetKind) continue;
        const expr = body.value;
        const kinds = resultKinds(expr, ctx.varTypes);
        kinds.delete("null");
        if (kinds.size === 0) continue;
        const field = ctx.fields[key];
        const base = { check: "Type berekening", target: targetDescription(key, variable, field), rule: ruleLabel(rule), expr };
        if (kinds.has("unknown") || kinds.has("delta")) {
          findings.push({ ...base, severity: "CONTROLEREN", problem: "Het type van de uitkomst is niet uit de berekening af te leiden.", hint: "" });
          continue;
        }
        const wrong = wrongKinds(targetKind, kinds);
        if (wrong.length) {
          const isComponent = variable.source === "component";
          const visible = Boolean(field) && !field.hidden;
          findings.push({
            ...base, severity: "FOUT",
            problem: mismatchProblem(wrong, targetKind, isComponent, visible, "De uitkomst van de berekening"),
            hint: fixHint(targetKind, wrong[0], expr),
          });
        } else if (variable.dataType === "int" && isPlainObject(expr) && "/" in expr) {
          findings.push({
            ...base, severity: "LET OP",
            problem: "Een deling kan een kommagetal opleveren (bijv. 2,5), maar de variabele verwacht een geheel getal.",
            hint: "",
          });
        }
      }
    }
    return findings;
  }

  function checkReferences(ctx) {
    const findings = [];
    const known = new Set([...Object.keys(ctx.variables), ...Object.keys(ctx.fields), ...ctx.staticKeys]);
    const resolves = (name) => {
      if (name === "") return true;
      const parts = name.split(".");
      for (let i = 1; i <= parts.length; i++) {
        if (known.has(parts.slice(0, i).join("."))) return true;
      }
      return false;
    };
    const stepUuids = new Set(ctx.steps.map((s) => s.uuid));
    for (const rule of ctx.rules) {
      const missing = new Map(); // name -> {where, exprLabel, expr}
      const note = (name, where, exprLabel, expr) => {
        if (!missing.has(name)) missing.set(name, { where, exprLabel, expr });
      };
      referencedNames(rule.jsonLogicTrigger).forEach((n) => {
        if (!resolves(n)) note(n, "voorwaarde", "Voorwaarde", rule.jsonLogicTrigger);
      });
      for (const action of rule.actions || []) {
        const body = action.action || {};
        if (body.type === "variable") {
          referencedNames(body.value).forEach((n) => {
            if (!resolves(n)) note(n, "berekening", "Berekening", body.value);
          });
        }
        const sets = body.type === "variable" || body.type === "fetch-from-service";
        if (sets && action.variable && !(action.variable in ctx.variables)) {
          note(action.variable, "actie (doelvariabele)", "Actie", action);
        }
        if (body.type === "property" && action.component && !(action.component in ctx.fields)) {
          note(action.component, "actie (veld eigenschap wijzigen)", "Actie", action);
        }
        const stepUuid = action.formStepUuid;
        if (body.type && body.type.startsWith("step-") && stepUuid && !stepUuids.has(stepUuid)) {
          note(`stap ${stepUuid}`, "actie (stap)", "Actie", action);
        }
      }
      for (const [name, { where, exprLabel, expr }] of missing) {
        findings.push({
          check: "Verwijzing", severity: "FOUT",
          target: { label: "Verwijzing", text: `'${name}' in de ${where}` },
          rule: ruleLabel(rule),
          problem: `De regel gebruikt '${name}', maar dat veld, die variabele of die stap bestaat niet (meer) in dit formulier. ` +
            "De regel werkt daardoor niet zoals bedoeld.",
          hint: "Pas de regel aan naar de juiste sleutel (bijv. na het hernoemen van een veld), of verwijder de regel als die niet meer nodig is.",
          expr, exprLabel,
        });
      }
    }
    return findings;
  }

  function checkInitialValues(ctx) {
    const findings = [];
    for (const [key, variable] of Object.entries(ctx.variables)) {
      const targetKind = DATA_TYPE_KIND[variable.dataType];
      if (!targetKind) continue;
      const value = variable.initialValue;
      const kind = valueKind(value);
      // Open Forms stores "" as the empty initial value of e.g. map fields.
      if (kind === "null" || value === "") continue;
      const wrong = wrongKinds(targetKind, [kind]);
      let problem = null;
      if (wrong.length) {
        const field = ctx.fields[key];
        problem = mismatchProblem(wrong, targetKind, variable.source === "component",
          Boolean(field) && !field.hidden, "De beginwaarde");
      } else if (variable.dataType === "int" && !Number.isInteger(value)) {
        problem = "De beginwaarde is een kommagetal, maar de variabele verwacht een geheel getal.";
      }
      if (!problem) continue;
      findings.push({
        check: "Beginwaarde", severity: "FOUT",
        target: targetDescription(key, variable, ctx.fields[key]),
        rule: null, problem,
        hint: literalHint(targetKind, value),
        expr: value, exprLabel: "Beginwaarde",
      });
    }
    return findings;
  }

  // ---- Open Forms logic analysis ---------------------------------------------
  // Mirrors openforms.forms.models.logic.FormLogic and
  // openforms.submissions.logic.actions (3.5.14 / 4.0.7): which variables a rule
  // reads and writes, and on which steps it runs.

  const REDUCE_VAR_NAMES = new Set(["current", "accumulator"]);
  // openforms.formio.constants.COMPONENT_DATATYPES
  const COMPONENT_DATATYPES = {
    date: "date", time: "time", file: "array", currency: "float", number: "float",
    checkbox: "boolean", selectboxes: "object", npFamilyMembers: "object", map: "object",
    editgrid: "array", datetime: "datetime", partners: "array", children: "array",
    customerProfile: "array",
  };
  // openforms.variables.constants.DEFAULT_INITIAL_VALUE
  const DEFAULT_INITIAL_VALUE = {
    string: "", boolean: false, object: {}, array: [], int: null, float: null,
    datetime: "", date: "", time: "",
  };
  const ZGW_BACKENDS = new Set(["objects_api", "zgw-create-zaak"]);

  /** Key of the form variable a (nested) data key belongs to: exact, else the shortest prefix. */
  function resolveKey(key, keys) {
    if (keys.has(key)) return key;
    const parts = key.split(".");
    for (let i = 1; i < parts.length; i++) {
      const prefix = parts.slice(0, i).join(".");
      if (keys.has(prefix)) return prefix;
    }
    return null;
  }

  /** Variable names an expression reads, as Open Forms' introspection finds them. */
  function inputKeys(expr, inReduce = false, out = new Set()) {
    if (Array.isArray(expr)) {
      expr.forEach((e) => inputKeys(e, inReduce, out));
      return out;
    }
    if (!isPlainObject(expr)) return out;
    for (const [op, args] of Object.entries(expr)) {
      const argList = Array.isArray(args) ? args : [args];
      if (op === "var" && typeof argList[0] === "string" &&
        !(inReduce && REDUCE_VAR_NAMES.has(argList[0]))) {
        out.add(argList[0]);
      }
      inputKeys(argList, inReduce || op.toLowerCase() === "reduce", out);
    }
    return out;
  }

  /** Variables used in a service fetch template ({{ name }} or {% ... name ... %}). */
  function templateVariables(fetchConfig) {
    const out = new Set();
    if (!isPlainObject(fetchConfig)) return out;
    const texts = [fetchConfig.path || ""];
    for (const group of [fetchConfig.queryParams, fetchConfig.headers]) {
      for (const value of Object.values(group || {})) texts.push(...(Array.isArray(value) ? value : [value]));
    }
    for (const text of texts) {
      for (const match of String(text).matchAll(/\{\{\s*([A-Za-z_][\w.]*)/g)) out.add(match[1]);
    }
    return out;
  }

  function stepUuidFromUrl(url) {
    return typeof url === "string" ? url.replace(/\/$/, "").split("/").pop() : null;
  }

  /** Per form: component maps and helpers for the logic analysis. */
  function buildFormModel(steps, variables) {
    const ordered = [...steps].sort((a, b) => (a.index || 0) - (b.index || 0));
    const componentMap = new Map(); // key -> component (no editgrid children)
    const stepOfKey = new Map(); // key -> step
    const keysOfStep = new Map(); // step uuid -> Set of component keys
    for (const step of ordered) {
      const keys = new Set();
      for (const comp of iterComponents(step.configuration || {}, false)) {
        componentMap.set(comp.key, comp);
        stepOfKey.set(comp.key, step);
        keys.add(comp.key);
      }
      keysOfStep.set(step.uuid, keys);
    }
    const varKeys = new Set(variables.map((v) => v.key));
    const variablesByKey = new Map(variables.map((v) => [v.key, v]));
    const childKeys = (key) => {
      const comp = componentMap.get(key);
      if (!comp) return [];
      return [...iterComponents(comp.components || [], false), ...iterComponents(comp.columns || [], false)]
        .map((c) => c.key);
    };
    return { steps: ordered, componentMap, stepOfKey, keysOfStep, varKeys, variablesByKey, childKeys };
  }

  /** Unresolved input and output variable names of one action (ActionOperation subclasses). */
  function actionIO(action, model) {
    const body = action.action || {};
    const config = body.config || {};
    switch (body.type) {
      case "property":
        return { inputs: new Set(), outputs: new Set([action.component, ...model.childKeys(action.component)]) };
      case "step-not-applicable":
      case "step-applicable":
        return { inputs: new Set(), outputs: new Set(model.keysOfStep.get(action.formStepUuid) || []) };
      case "variable":
        return { inputs: inputKeys(body.value), outputs: new Set([action.variable]) };
      case "synchronize-variables":
        return { inputs: new Set([config.sourceVariable]), outputs: new Set([config.destinationVariable]) };
      case "fetch-from-service": {
        const variable = model.variablesByKey.get(action.variable) || {};
        return { inputs: templateVariables(variable.serviceFetchConfiguration), outputs: new Set([action.variable]) };
      }
      case "evaluate-dmn":
        return {
          inputs: new Set((config.inputMapping || []).map((m) => m.formVariable)),
          outputs: new Set((config.outputMapping || []).map((m) => m.formVariable)),
        };
      default: // disable-next, set-registration-backend
        return { inputs: new Set(), outputs: new Set() };
    }
  }

  /** Inputs/outputs per rule, resolved against the form variables, as FormLogic computes them. */
  function analyzeRule(rule, model) {
    const triggerInputs = new Set();
    for (const key of inputKeys(rule.jsonLogicTrigger)) {
      const resolved = resolveKey(key, model.varKeys);
      if (resolved !== null) triggerInputs.add(resolved);
    }
    const inputMap = new Map(); // resolved key -> Set of action indexes
    const outputMap = new Map();
    const add = (map, key, i) => map.set(key, (map.get(key) || new Set()).add(i));
    const io = (rule.actions || []).map((action) => actionIO(action, model));
    io.forEach(({ inputs, outputs }, i) => {
      for (const key of inputs) {
        const resolved = typeof key === "string" ? resolveKey(key, model.varKeys) : null;
        if (resolved !== null) add(inputMap, resolved, i);
      }
      for (const key of outputs) if (model.varKeys.has(key)) add(outputMap, key, i);
    });
    return { triggerInputs, inputMap, outputMap, io };
  }

  /** Steps a rule runs on (FormLogic.steps), in step order. */
  function ruleSteps(rule, analysis, model) {
    const stepsOf = (keys) => {
      const found = new Set();
      for (const key of keys) {
        const resolved = resolveKey(key, model.varKeys) || key;
        const step = model.stepOfKey.get(resolved);
        if (step) found.add(step);
      }
      return found;
    };
    const steps = new Set();
    (rule.actions || []).forEach((action, i) => {
      const type = (action.action || {}).type;
      const { inputs, outputs } = analysis.io[i];
      let found;
      if (type === "disable-next") {
        found = new Set(model.steps.filter((s) => s.uuid === action.formStepUuid));
      } else if (type === "step-not-applicable" || type === "step-applicable") {
        found = new Set(model.steps);
      } else if (type === "set-registration-backend") {
        found = stepsOf(analysis.triggerInputs);
      } else {
        found = stepsOf(outputs);
        if (!found.size && ["variable", "fetch-from-service", "evaluate-dmn"].includes(type)) {
          found = stepsOf(new Set([...analysis.triggerInputs, ...inputs]));
        }
      }
      found.forEach((s) => steps.add(s));
    });
    return model.steps.filter((s) => steps.has(s));
  }

  /** Groups of rules that depend on each other in a loop (openforms.forms.logic_analysis). */
  function logicCycles(rules, analyses) {
    const writers = new Map(); // variable -> rule indexes that write it
    analyses.forEach((a, r) => {
      for (const key of a.outputMap.keys()) writers.set(key, [...(writers.get(key) || []), r]);
    });
    const edges = rules.map(() => new Map()); // from -> (to -> Set of variables)
    analyses.forEach((a, r) => {
      const inputs = new Set([...a.inputMap.keys(), ...a.triggerInputs]);
      for (const key of inputs) {
        for (const from of writers.get(key) || []) {
          if (from === r && validSelfCycle(a, key)) continue;
          const vars = edges[from].get(r) || new Set();
          edges[from].set(r, vars.add(key));
        }
      }
    });
    // Tarjan's strongly connected components.
    let counter = 0;
    const index = new Map();
    const low = new Map();
    const stack = [];
    const onStack = new Set();
    const groups = [];
    const visit = (v) => {
      index.set(v, counter);
      low.set(v, counter++);
      stack.push(v);
      onStack.add(v);
      for (const w of edges[v].keys()) {
        if (!index.has(w)) {
          visit(w);
          low.set(v, Math.min(low.get(v), low.get(w)));
        } else if (onStack.has(w)) {
          low.set(v, Math.min(low.get(v), index.get(w)));
        }
      }
      if (low.get(v) === index.get(v)) {
        const group = [];
        let w;
        do {
          w = stack.pop();
          onStack.delete(w);
          group.push(w);
        } while (w !== v);
        groups.push(group);
      }
    };
    rules.forEach((_, v) => { if (!index.has(v)) visit(v); });
    return groups
      .filter((g) => g.length > 1 || edges[g[0]].has(g[0]))
      .map((g) => {
        const variables = new Set();
        for (const from of g) for (const to of g) (edges[from].get(to) || []).forEach((k) => variables.add(k));
        return { rules: g.sort((a, b) => a - b).map((i) => rules[i]), variables: [...variables].sort() };
      });
  }

  function validSelfCycle(analysis, key) {
    for (const k of analysis.triggerInputs) if (analysis.outputMap.has(k)) return false;
    const outputs = analysis.outputMap.get(key) || new Set();
    for (const i of analysis.inputMap.get(key) || []) if (outputs.has(i)) return false;
    return true;
  }

  // ---- Checks from the Open Forms 4.0 upgrade preparation ----------------------

  const ruleLabel = (rule) => `nr. ${(rule.order || 0) + 1}: ${rule.description || "(geen beschrijving)"}`;
  const isOpenForms35 = (form) => "newLogicEvaluationEnabled" in form;

  /** report_invalid_form_logic.py (3.5): old logic evaluation, trigger-from-step, cycles. */
  function checkLogicEvaluation(ctx) {
    const findings = [];
    const { form, rules } = ctx;
    if (!rules.length) return findings;
    const base = { check: "Logica 4.0", severity: "FOUT", expr: undefined };
    if (isOpenForms35(form) && form.newLogicEvaluationEnabled === false) {
      findings.push({
        ...base, target: { label: "Formulier", text: "logica-evaluatie" }, rule: null,
        problem: "Dit formulier gebruikt nog de oude logica-evaluatie. Open Forms 4.0 kan niet " +
          "worden geïnstalleerd zolang er zo'n formulier is.",
        hint: "Zet de nieuwe logica-evaluatie aan voor dit formulier (de beheerder kan alle " +
          "formulieren omzetten, zie de upgrade-instructies van PodiumD 4.10). Los eerst eventuele " +
          "logica-cycli hieronder op.",
      });
    }
    if (isOpenForms35(form) && form.newLogicEvaluationEnabled === true) {
      for (const rule of rules.filter((r) => r.triggerFromStep)) {
        findings.push({
          ...base, target: { label: "Regel", text: "'Trigger vanaf stap' is ingesteld" }, rule: ruleLabel(rule),
          problem: "De regel heeft 'trigger vanaf stap', wat niet samengaat met de nieuwe logica-evaluatie.",
          hint: "Haal de instelling 'trigger vanaf stap' weg; de nieuwe logica-evaluatie bepaalt zelf op welke stap de regel draait.",
        });
      }
    }
    for (const cycle of logicCycles(rules, ctx.analyses)) {
      findings.push({
        ...base, check: "Logica-cyclus",
        target: { label: "Variabelen", text: cycle.variables.join(", ") || "(onbekend)" },
        rule: cycle.rules.map(ruleLabel).join(" | "),
        problem: (cycle.rules.length > 1
          ? "Deze regels zetten elkaars invoer, zodat de logica geen eindtoestand bereikt."
          : "Deze regel gebruikt een variabele die hij zelf ook zet (zoals x = x + 1).") +
          " Open Forms 4.0 accepteert dit niet.",
        hint: "Haal de kringloop eruit, bijv. met een aparte (eigen) variabele voor de uitkomst.",
      });
    }
    return findings;
  }

  /** check_disable_next_logic_action.py (3.5): "disable next" actions whose step needs a manual check. */
  function checkDisableNext(ctx) {
    const findings = [];
    if (!isOpenForms35(ctx.form)) return findings;
    const { model } = ctx;
    for (const rule of ctx.rules) {
      const disableActions = (rule.actions || []).filter((a) => (a.action || {}).type === "disable-next");
      if (!disableActions.length) continue;
      const inputSteps = new Set();
      for (const key of inputKeys(rule.jsonLogicTrigger)) {
        const variable = model.variablesByKey.get(resolveKey(key, model.varKeys));
        if (!variable) continue;
        if (variable.prefillPlugin) inputSteps.add(model.steps[0]);
        inputSteps.add(model.stepOfKey.get(variable.key) || null);
      }
      let reason = null;
      if (inputSteps.size === 0 && !rule.triggerFromStep) {
        reason = "Bij de migratie is de eerste stap gekozen als beste gok, omdat de voorwaarde geen velden gebruikt.";
      } else if (inputSteps.has(null)) {
        reason = "De voorwaarde gebruikt een eigen variabele, waarvan niet vast te stellen is op welke stap die gevuld wordt.";
      }
      if (!reason) continue;
      findings.push({
        check: "Volgende-knop", severity: "CONTROLEREN",
        target: { label: "Actie", text: "'Volgende uitschakelen'" }, rule: ruleLabel(rule),
        problem: `${reason} De actie werkt alleen op de stap die erbij staat.`,
        hint: "Controleer of de stap bij de actie 'Volgende uitschakelen' klopt; voeg zo nodig " +
          "een actie per stap toe.",
        expr: rule.jsonLogicTrigger, exprLabel: "Voorwaarde",
      });
    }
    return findings;
  }

  /** report_logic_with_deprecated_clear_on_hide_behavior.py: (variable, compared value) pairs. */
  function* comparedVariables(expr) {
    if (Array.isArray(expr)) {
      for (const e of expr) yield* comparedVariables(e);
      return;
    }
    if (!isPlainObject(expr) || Object.keys(expr).length !== 1) return;
    const [op, raw] = Object.entries(expr)[0];
    const args = Array.isArray(raw) ? raw : [raw];
    const isVar = (x) => isPlainObject(x) && "var" in x;
    const isPrimitive = (x) => x === null || ["number", "string", "boolean"].includes(typeof x);
    const varParts = (x) => (Array.isArray(x.var) ? x.var : [x.var]);
    if (["==", "!=", "===", "!=="].includes(op)) {
      if (args.length !== 2) return;
      const [a, b] = args;
      const pair = isVar(a) && isPrimitive(b) ? [a, b] : isPrimitive(a) && isVar(b) ? [b, a] : null;
      if (!pair) {
        yield* comparedVariables(args);
        return;
      }
      const [name, ...fallback] = varParts(pair[0]);
      if (!fallback.length && typeof name === "string") yield [name, pair[1]];
      return;
    }
    if (op === "in" && args.length === 2 && isVar(args[0]) && Array.isArray(args[1])) {
      const [name, ...fallback] = varParts(args[0]);
      for (const value of args[1]) {
        if (value !== null && typeof value === "object") {
          yield* comparedVariables(value);
        } else {
          if (fallback.length) return;
          if (typeof name === "string") yield [name, value];
        }
      }
      return;
    }
    if (op === "var" && args.length === 1 && typeof args[0] === "string") yield [args[0], null];
    yield* comparedVariables(args);
  }

  /** Python's ==, for the primitive values compared here (True == 1, False == 0). */
  function pyEquals(a, b) {
    const num = (x) => (typeof x === "boolean" ? Number(x) : x);
    if (a === null || b === null || a === undefined || b === undefined) return (a ?? null) === (b ?? null);
    if (typeof a === "object" || typeof b === "object") return false;
    return num(a) === num(b);
  }

  function emptyValue(component) {
    if (component.type === "selectboxes") return false;
    if (component.type === "map") return component.defaultValue ?? null;
    const dataType = component.multiple ? "array" : COMPONENT_DATATYPES[component.type] || "string";
    return dataType in DEFAULT_INITIAL_VALUE ? DEFAULT_INITIAL_VALUE[dataType] : "";
  }

  function checkClearOnHide(ctx) {
    const findings = [];
    const { model } = ctx;
    const affected = new Set();
    for (const [key, comp] of model.componentMap) if ((comp.conditional || {}).when) affected.add(key);
    for (const rule of ctx.rules) {
      for (const action of rule.actions || []) {
        const body = action.action || {};
        if (body.type === "property" && (body.property || {}).value === "hidden") affected.add(action.component);
      }
    }
    for (const key of [...affected]) model.childKeys(key).forEach((k) => affected.add(k));
    const componentKeys = new Set(model.componentMap.keys());

    const analyze = (expr, firstStep) => {
      const hidden = new Set();
      const future = new Set();
      for (const [name, compared] of comparedVariables(expr)) {
        let resolved = resolveKey(name, componentKeys);
        if (resolved === null) continue;
        const variableStep = model.stepOfKey.get(resolved);
        let component = model.componentMap.get(resolved);
        if (component.type === "editgrid" && name !== resolved) {
          const rest = name.slice(resolved.length + 1);
          const dot = rest.indexOf(".");
          if (dot < 0) continue;
          const children = new Map([...iterComponents(component.components || [], false)].map((c) => [c.key, c]));
          resolved = resolveKey(rest.slice(dot + 1), new Set(children.keys()));
          if (resolved === null) continue;
          component = children.get(resolved);
        }
        if (![emptyValue(component), null, component.defaultValue].some((v) => pyEquals(compared, v))) continue;
        if (affected.has(resolved) && component.clearOnHide !== false) hidden.add(name);
        if (variableStep && firstStep && firstStep.index < variableStep.index) future.add(name);
      }
      return { hidden: [...hidden], future: [...future] };
    };

    const DEFAULT_HINT = 'Geef de variabele een standaardwaarde in de vergelijking: {"var": ["veld", ""]} ' +
      'in plaats van {"var": "veld"} (met de lege waarde van dat veld).';
    const report = (rule, where, expr, names, problem) => findings.push({
      check: "Verbergen (4.0)", severity: "CONTROLEREN",
      target: { label: "Variabelen", text: names.join(", ") }, rule: ruleLabel(rule),
      problem, hint: DEFAULT_HINT, expr, exprLabel: where,
    });
    const HIDDEN_PROBLEM = "Vanaf Open Forms 4.0 verdwijnt de waarde van een verborgen veld uit de gegevens, " +
      "in plaats van terug te gaan naar de lege waarde. Deze regel vergelijkt het veld met een lege " +
      "waarde en kan daardoor anders gaan werken.";
    const FUTURE_PROBLEM = "De regel draait al op een eerdere stap dan waar dit veld staat. Vanaf Open Forms " +
      "4.0 bestaat de waarde dan nog niet, in plaats van leeg te zijn.";

    ctx.rules.forEach((rule, r) => {
      const analysis = ctx.analyses[r];
      const firstStep = ruleSteps(rule, analysis, model)[0] || null;
      const trigger = analyze(rule.jsonLogicTrigger, firstStep);
      if (trigger.hidden.length) report(rule, "Voorwaarde", rule.jsonLogicTrigger, trigger.hidden, HIDDEN_PROBLEM);
      if (trigger.future.length) report(rule, "Voorwaarde", rule.jsonLogicTrigger, trigger.future, FUTURE_PROBLEM);
      (rule.actions || []).forEach((action, i) => {
        const body = action.action || {};
        if (body.type === "variable") {
          const result = analyze(body.value, firstStep);
          if (result.hidden.length) report(rule, "Berekening", body.value, result.hidden, HIDDEN_PROBLEM);
          if (result.future.length) report(rule, "Berekening", body.value, result.future, FUTURE_PROBLEM);
        } else if (body.type === "fetch-from-service" || body.type === "evaluate-dmn") {
          const keys = [...analysis.io[i].inputs].map((k) => resolveKey(k, componentKeys)).filter((k) => k !== null);
          const names = new Set(keys.filter((k) => affected.has(k)));
          for (const k of keys) {
            const step = model.stepOfKey.get(k);
            if (firstStep && step && firstStep.index < step.index) names.add(k);
          }
          if (names.size) {
            const what = body.type === "evaluate-dmn" ? "een DMN-beslissing" : "het ophalen uit een service";
            findings.push({
              check: "Verbergen (4.0)", severity: "CONTROLEREN",
              target: { label: "Variabelen", text: [...names].join(", ") }, rule: ruleLabel(rule),
              problem: `Deze velden worden gebruikt in ${what}, maar kunnen vanaf Open Forms 4.0 ontbreken ` +
                "(verborgen veld of veld op een latere stap).",
              hint: "Controleer of de aanroep goed gaat als deze waarden ontbreken.",
            });
          }
        }
      });
    });
    return findings;
  }

  function deepEqual(a, b) {
    return JSON.stringify(a, Object.keys(a || {}).sort()) === JSON.stringify(b, Object.keys(b || {}).sort());
  }

  function* urlsIn(value) {
    if (typeof value === "string") {
      if (value.startsWith("http")) yield value;
    } else if (Array.isArray(value)) {
      for (const v of value) yield* urlsIn(v);
    } else if (isPlainObject(value)) {
      for (const v of Object.values(value)) yield* urlsIn(v);
    }
  }

  /**
   * report_file_component_inconsistent_catalogues.py and the NO_SERVICE part of
   * PodiumD's openforms-check-registration-options.py.
   */
  function checkRegistration(ctx) {
    const findings = [];
    const backends = ctx.form.registrationBackends || [];
    const files = ctx.steps.flatMap((step) => [...iterComponents(step.configuration || {}, true)]
      .filter((c) => c.type === "file").map((c) => ({ component: c, step })));
    const fileTarget = ({ component, step }) => ({
      label: "Veld", text: `${component.label || component.key}  (sleutel '${component.key}', type file, stap '${step.name}')`,
    });

    for (const backend of backends.filter((b) => ZGW_BACKENDS.has(b.backend))) {
      const backendCatalogue = (backend.options || {}).catalogue || {};
      for (const file of files) {
        const catalogue = (((file.component.registration || {}).documentType) || {}).catalogue;
        if (!catalogue || deepEqual(catalogue, backendCatalogue)) continue;
        findings.push({
          check: "Catalogus", severity: "FOUT", target: fileTarget(file), rule: null,
          problem: `Het uploadveld gebruikt catalogus ${show(catalogue)}, maar de registratie ` +
            `'${backend.name}' gebruikt ${show(backendCatalogue)}. De bijlage kan dan niet goed worden geregistreerd.`,
          hint: "Kies in de registratie-instellingen van het uploadveld dezelfde catalogus als in de registratie van het formulier.",
        });
      }
    }

    if (!ctx.serviceRoots) return findings;
    const known = (url) => ctx.serviceRoots.some((root) => url.startsWith(root));
    const NO_SERVICE_HINT = "Corrigeer of verwijder de URL; meestal is het een URL van een andere omgeving.";
    for (const backend of backends) {
      for (const url of new Set(urlsIn(backend.options))) {
        if (known(url)) continue;
        findings.push({
          check: "Onbekende service", severity: "FOUT",
          target: { label: "Registratie", text: `${backend.name}  (${backend.backend})` }, rule: null,
          problem: `De registratie verwijst naar ${url}, maar daarvoor is in Open Forms geen service ingesteld.`,
          hint: NO_SERVICE_HINT,
        });
      }
    }
    for (const file of files) {
      const url = (file.component.registration || {}).informatieobjecttype || "";
      if (!url.startsWith("http") || known(url)) continue;
      findings.push({
        check: "Onbekende service", severity: "FOUT", target: fileTarget(file), rule: null,
        problem: `Het documenttype van het uploadveld verwijst naar ${url}, maar daarvoor is in Open Forms geen service ingesteld.`,
        hint: NO_SERVICE_HINT,
      });
    }
    return findings;
  }

  // ---- Koppelingen: references to Objecttypen and Catalogi ---------------------
  // Checked through Open Forms' own admin endpoints, which call the APIs server-side
  // with the API group's credentials (same in 3.5.14 and 4.0.7).

  const nonEmpty = (x) => typeof x === "string" && x.trim() !== "";
  const unique = (items) => [...new Set(items)];
  const catalogueSet = (c) => isPlainObject(c) && nonEmpty(c.domain) && nonEmpty(c.rsin);
  const fileDescriptions = (options) => (options.files || []).map((f) => f.documentTypeDescription);

  /** What a form refers to in Objecttypen and Catalogi: registration backends and Objects API prefill. */
  function linkReferences(form, variables) {
    const refs = [];
    for (const backend of form.registrationBackends || []) {
      const o = backend.options || {};
      const owner = { label: "Registratie", text: `${backend.name}  (${backend.backend})` };
      if (backend.backend === "objects_api" && nonEmpty(o.objectsApiGroup)) {
        if (nonEmpty(o.objecttype)) {
          refs.push({ owner, type: "objecttype", group: o.objectsApiGroup, uuid: o.objecttype, version: o.objecttypeVersion });
        }
        if (catalogueSet(o.catalogue)) {
          refs.push({
            owner, type: "catalogue", api: { kind: "objects", group: o.objectsApiGroup }, catalogue: o.catalogue,
            documentTypes: unique([o.iotSubmissionReport, o.iotSubmissionCsv, o.iotAttachment, ...fileDescriptions(o)].filter(nonEmpty)),
            caseType: null, roleTypes: [], productUrl: null,
          });
        }
      } else if (backend.backend === "zgw-create-zaak") {
        if (o.zgwApiGroup != null && o.zgwApiGroup !== "" && catalogueSet(o.catalogue)) {
          refs.push({
            owner, type: "catalogue", api: { kind: "zgw", group: o.zgwApiGroup }, catalogue: o.catalogue,
            documentTypes: unique([o.documentTypeDescription, ...fileDescriptions(o)].filter(nonEmpty)),
            caseType: nonEmpty(o.caseTypeIdentification) ? o.caseTypeIdentification : null,
            roleTypes: unique([o.medewerkerRoltype, o.partnersRoltype, o.childrenRoltype].filter(nonEmpty)),
            productUrl: nonEmpty(o.productUrl) ? o.productUrl : null,
          });
        }
        if (nonEmpty(o.objectsApiGroup) && nonEmpty(o.objecttype)) {
          refs.push({ owner, type: "objecttype", group: o.objectsApiGroup, url: o.objecttype, version: o.objecttypeVersion });
        }
      }
    }
    for (const variable of variables) {
      const p = variable.prefillOptions || {};
      if (variable.prefillPlugin !== "objects_api" || !nonEmpty(p.objectsApiGroup) || !nonEmpty(p.objecttypeUuid)) continue;
      refs.push({
        owner: { label: "Prefill", text: `${variable.name || variable.key}  (sleutel '${variable.key}')` },
        type: "objecttype", group: p.objectsApiGroup, uuid: p.objecttypeUuid, version: p.objecttypeVersion,
      });
    }
    return refs;
  }

  /** Lists from Open Forms' admin endpoints, each fetched once: {data} or {error}. */
  function makeLinkResolver(getJson, api) {
    const cache = new Map();
    const get = (path, params) => {
      const url = `${api}${path}?${new URLSearchParams(params)}`;
      if (!cache.has(url)) cache.set(url, getJson(url).then((data) => ({ data }), (error) => ({ error })));
      return cache.get(url);
    };
    const zgw = "/registration/plugins/zgw-api";
    const groupParam = ({ kind, group }) => (kind === "zgw" ? { zgw_api_group: group } : { objects_api_group: group });
    return {
      objecttypes: (group) => get("/objects-api/object-types", { objects_api_group: group }),
      versions: (group, uuid) => get(`/objects-api/object-types/${encodeURIComponent(uuid)}/versions`, { objects_api_group: group }),
      catalogues: (api) => get(api.kind === "zgw" ? `${zgw}/catalogues` : "/objects-api/catalogues", groupParam(api)),
      documentTypes: (api, catalogueUrl, caseType) => get(
        api.kind === "zgw" ? `${zgw}/document-types` : "/objects-api/document-types",
        { ...groupParam(api), catalogue_url: catalogueUrl, ...(caseType ? { case_type_identification: caseType } : {}) },
      ),
      caseTypes: (group, catalogueUrl) => get(`${zgw}/case-types`, { zgw_api_group: group, catalogue_url: catalogueUrl }),
      roleTypes: (group, catalogueUrl, caseType) =>
        get(`${zgw}/role-types`, { zgw_api_group: group, catalogue_url: catalogueUrl, case_type_identification: caseType }),
      products: (group, catalogueUrl, caseType) =>
        get(`${zgw}/products`, { zgw_api_group: group, catalogue_url: catalogueUrl, case_type_identification: caseType }),
    };
  }

  function fetchProblem(what, error) {
    const status = Number(String(error.message).split(/\D/)[0]);
    const reason = status === 400
      ? "de API-groep bestaat niet (meer) of is niet volledig ingesteld"
      : status >= 500
        ? "Open Forms kon de API niet bereiken of kreeg een fout terug"
        : error.message;
    return `${what} konden niet worden opgehaald: ${reason}.`;
  }

  /** Findings for the references of one form; `resolver` is makeLinkResolver's result (or a test stub). */
  async function checkLinks(refs, resolver) {
    const findings = [];
    const add = (ref, severity, problem, hint) =>
      findings.push({ check: "Koppeling", severity, target: ref.owner, rule: null, problem, hint });
    const SETTINGS_HINT = "Controleer de API-groep en de bijbehorende services in de beheeromgeving (Configuratie).";
    const failed = (ref, what, result) => add(ref, "CONTROLEREN", fetchProblem(what, result.error), SETTINGS_HINT);

    for (const ref of refs) {
      if (ref.type === "objecttype") {
        const shown = ref.uuid || ref.url;
        const types = await resolver.objecttypes(ref.group);
        if (types.error) {
          failed(ref, `De objecttypen van API-groep '${ref.group}'`, types);
          continue;
        }
        const type = types.data.find((t) => (ref.uuid ? t.uuid === ref.uuid : t.url === ref.url));
        if (!type) {
          add(ref, "FOUT", `Objecttype ${shown} bestaat niet (meer) in de Objecttypen van API-groep '${ref.group}'.`,
            "Kies in de instellingen een bestaand objecttype.");
          continue;
        }
        if (ref.version === null || ref.version === undefined || ref.version === "") continue;
        const versions = await resolver.versions(ref.group, type.uuid);
        if (versions.error) {
          failed(ref, `De versies van objecttype '${type.name}'`, versions);
          continue;
        }
        const version = versions.data.find((v) => Number(v.version) === Number(ref.version));
        if (!version) {
          add(ref, "FOUT", `Versie ${ref.version} van objecttype '${type.name}' bestaat niet (meer).`,
            "Kies in de instellingen een bestaande versie van het objecttype.");
        } else if (version.status !== "published") {
          add(ref, "LET OP", `Versie ${ref.version} van objecttype '${type.name}' heeft status '${version.status}', niet 'published'.`,
            "Gebruik een gepubliceerde versie van het objecttype.");
        }
        continue;
      }

      // type === "catalogue"
      const { domain, rsin } = ref.catalogue;
      const catalogues = await resolver.catalogues(ref.api);
      if (catalogues.error) {
        failed(ref, `De catalogi van API-groep '${ref.api.group}'`, catalogues);
        continue;
      }
      const catalogue = catalogues.data.find((c) => c.domain === domain && c.rsin === rsin);
      if (!catalogue) {
        add(ref, "FOUT", `Catalogus ${domain} (RSIN ${rsin}) bestaat niet (meer) in API-groep '${ref.api.group}'.`,
          "Kies in de registratie-instellingen een bestaande catalogus.");
        continue;
      }
      let caseType = null;
      if (ref.caseType) {
        const caseTypes = await resolver.caseTypes(ref.api.group, catalogue.url);
        if (caseTypes.error) {
          failed(ref, `De zaaktypen van catalogus '${catalogue.label}'`, caseTypes);
        } else {
          caseType = caseTypes.data.find((c) => c.identification === ref.caseType) || null;
          if (!caseType) {
            add(ref, "FOUT", `Zaaktype '${ref.caseType}' bestaat niet (meer) in catalogus '${catalogue.label}'.`,
              "Kies in de registratie-instellingen een bestaand zaaktype.");
          } else if (caseType.isPublished === false) {
            add(ref, "LET OP", `Zaaktype '${ref.caseType}' in catalogus '${catalogue.label}' is nog een concept.`,
              "Publiceer het zaaktype, of kies een gepubliceerd zaaktype.");
          }
        }
      }
      // A missing case type is reported once; its document, role and product checks would only repeat it.
      if (ref.caseType && !caseType) continue;
      const within = caseType ? ` bij zaaktype '${ref.caseType}'` : "";
      if (ref.documentTypes.length) {
        const documentTypes = await resolver.documentTypes(ref.api, catalogue.url, caseType ? ref.caseType : null);
        if (documentTypes.error) {
          failed(ref, `De documenttypen van catalogus '${catalogue.label}'`, documentTypes);
        } else {
          for (const description of ref.documentTypes) {
            const found = documentTypes.data.find((d) => d.description === description);
            if (!found) {
              add(ref, "FOUT", `Documenttype '${description}' bestaat niet (meer) in catalogus '${catalogue.label}'${within}.`,
                "Kies in de registratie-instellingen een bestaand documenttype.");
            } else if (found.isPublished === false) {
              add(ref, "LET OP", `Documenttype '${description}' in catalogus '${catalogue.label}' is nog een concept.`,
                "Publiceer het documenttype, of kies een gepubliceerd documenttype.");
            }
          }
        }
      }
      if (!caseType) continue;
      if (ref.roleTypes.length) {
        const roleTypes = await resolver.roleTypes(ref.api.group, catalogue.url, ref.caseType);
        if (roleTypes.error) {
          failed(ref, `De roltypen van zaaktype '${ref.caseType}'`, roleTypes);
        } else {
          for (const description of ref.roleTypes.filter((d) => !roleTypes.data.some((r) => r.description === d))) {
            add(ref, "FOUT", `Roltype '${description}' bestaat niet (meer)${within}.`,
              "Kies in de registratie-instellingen een bestaand roltype.");
          }
        }
      }
      if (ref.productUrl) {
        const products = await resolver.products(ref.api.group, catalogue.url, ref.caseType);
        if (products.error) {
          failed(ref, `De producten van zaaktype '${ref.caseType}'`, products);
        } else if (!products.data.some((p) => p.url === ref.productUrl)) {
          add(ref, "FOUT", `Product ${ref.productUrl} hoort niet (meer) bij een geldige versie van zaaktype '${ref.caseType}'.`,
            "Kies in de registratie-instellingen een product van het zaaktype.");
        }
      }
    }
    return findings;
  }

  function sortFindings(findings) {
    return [...findings].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity));
  }

  /** Run all checks on one form. data: {form, steps, variables, rules, staticVariables, serviceRoots}. */
  function checkForm(data) {
    const variables = {};
    for (const v of data.variables) variables[v.key] = v;
    const varTypes = {};
    for (const v of data.variables) varTypes[v.key] = v.dataType;
    for (const s of data.staticVariables || []) varTypes[s.key] = varTypes[s.key] || s.dataType;
    const rules = [...data.rules].sort((a, b) => (a.order || 0) - (b.order || 0));
    const model = buildFormModel(data.steps, data.variables);
    const ctx = {
      form: data.form, steps: data.steps, rules, variables, varTypes, model,
      fields: indexFields(data.steps, rules),
      staticKeys: (data.staticVariables || []).map((s) => s.key),
      analyses: rules.map((rule) => analyzeRule(rule, model)),
      serviceRoots: data.serviceRoots,
    };
    const actions = rules.reduce((n, r) => n + (r.actions || []).filter((a) => (a.action || {}).type === "variable").length, 0);
    const findings = [
      ...checkTypes(ctx), ...checkReferences(ctx), ...checkInitialValues(ctx),
      ...checkLogicEvaluation(ctx), ...checkDisableNext(ctx), ...checkClearOnHide(ctx), ...checkRegistration(ctx),
    ];
    return { findings: sortFindings(findings), setValueActions: actions, ruleCount: rules.length, variableCount: data.variables.length };
  }

  function formatReport(results, meta) {
    const line = "=".repeat(78);
    const thin = "-".repeat(78);
    const out = [];
    out.push(`Open Forms configuratiecontrole - ${meta.host} - ${meta.date}`);
    const is35 = results.some(({ form }) => isOpenForms35(form));
    out.push(`Open Forms ${is35 ? "3.5 (met de controles voor de upgrade naar 4.0)" : "4.0 of nieuwer"}`);
    if (!meta.serviceRoots) out.push("Let op: de services konden niet worden opgehaald; de controle 'Onbekende service' is overgeslagen.");
    const totals = {};
    let actions = 0;
    let rules = 0;
    let variables = 0;
    for (const { form, result } of results) {
      actions += result.setValueActions;
      rules += result.ruleCount;
      variables += result.variableCount;
      if (!result.findings.length) continue;
      out.push(line);
      out.push(`Formulier: ${form.name}  (${form.active ? "actief" : "niet actief"})`);
      if (form.internalName) out.push(`Interne naam: ${form.internalName}`);
      out.push(`Beheer: ${meta.adminBase}/admin/forms/form/?q=${form.uuid}`);
      for (const f of result.findings) {
        totals[f.severity] = (totals[f.severity] || 0) + 1;
        out.push(thin);
        out.push(`[${f.severity}] ${f.check}`);
        out.push(`  ${(f.target.label + ":").padEnd(11)}${f.target.text}`);
        if (f.rule) out.push(`  Regel:     ${f.rule}`);
        out.push(`  Probleem:  ${f.problem}`);
        if (f.hint) out.push(`  Oplossing: ${f.hint}`);
        if (f.expr !== undefined) out.push(`  ${f.exprLabel || "Berekening"}: ${show(f.expr)}`);
      }
    }
    out.push(line);
    const summary = SEVERITY_ORDER.filter((s) => totals[s]).map((s) => `${totals[s]} ${s}`).join(", ") || "geen bevindingen";
    out.push(`${results.length} formulieren gecontroleerd (${rules} logicaregels, ${actions} 'waarde instellen'-acties, ` +
      `${variables} variabelen): ${summary}.`);
    if (meta.errors && meta.errors.length) {
      out.push("");
      out.push("Niet gecontroleerd (fout bij ophalen):");
      meta.errors.forEach((e) => out.push(`  - ${e}`));
    }
    return out.join("\n");
  }

  const core = {
    resultKinds, referencedNames, inputKeys, comparedVariables, checkForm, formatReport, literalHint,
    linkReferences, makeLinkResolver, checkLinks, sortFindings,
  };

  if (typeof window === "undefined") {
    module.exports = core;
    return;
  }

  // ---- Browser part ----------------------------------------------------------

  const adminIndex = location.pathname.indexOf("/admin/");
  if (adminIndex < 0) {
    alert("Start deze controle vanuit de Open Forms beheeromgeving (een pagina onder /admin/).");
    return;
  }
  const adminBase = location.origin + location.pathname.slice(0, adminIndex);
  const api = `${adminBase}/api/v2`;

  const panel = document.createElement("div");
  panel.style.cssText = "position:fixed;inset:24px;z-index:100000;background:#fff;color:#000;" +
    "border:2px solid #333;box-shadow:0 4px 24px rgba(0,0,0,.4);display:flex;flex-direction:column;font:14px sans-serif";
  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;gap:8px;align-items:center;padding:8px;border-bottom:1px solid #ccc";
  const status = document.createElement("strong");
  status.style.flex = "1";
  status.textContent = "Open Forms configuratiecontrole: bezig met ophalen...";
  const pre = document.createElement("pre");
  pre.style.cssText = "flex:1;overflow:auto;margin:0;padding:12px;white-space:pre-wrap;font:13px monospace";
  const button = (text, onClick) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.addEventListener("click", onClick);
    bar.appendChild(b);
    return b;
  };
  bar.appendChild(status);
  const copy = button("Kopiëren", () => navigator.clipboard.writeText(pre.textContent));
  const download = button("Download .txt", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([pre.textContent], { type: "text/plain" }));
    a.download = `openforms-controle-${location.hostname}.txt`;
    a.click();
  });
  button("Sluiten", () => panel.remove());
  copy.disabled = download.disabled = true;
  panel.append(bar, pre);
  document.body.appendChild(panel);

  async function getJson(url) {
    const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (response.status === 401 || response.status === 403) {
      throw new Error(`${response.status}: geen toegang. Je hebt een beheeraccount met het recht "forms.change_form" nodig.`);
    }
    if (!response.ok) throw new Error(`${response.status} bij ${url}`);
    return response.json();
  }

  async function getAll(url) {
    const items = [];
    let next = url;
    while (next) {
      const page = await getJson(next);
      if (Array.isArray(page)) return items.concat(page);
      items.push(...(page.results || []));
      next = page.next;
    }
    return items;
  }

  (async () => {
    try {
      const [forms, staticVariables, services] = await Promise.all([
        getAll(`${api}/forms`),
        getJson(`${api}/variables/static`).catch(() => []),
        getAll(`${api}/services`).catch(() => null),
      ]);
      const serviceRoots = services && services.map((s) => s.apiRoot).filter(Boolean);
      const resolver = makeLinkResolver(getJson, api);
      const results = [];
      const errors = [];
      for (const [i, form] of forms.entries()) {
        status.textContent = `Open Forms configuratiecontrole: formulier ${i + 1} van ${forms.length}...`;
        try {
          const [steps, variables, rules] = await Promise.all([
            getAll(`${api}/forms/${form.uuid}/steps`),
            getJson(`${api}/forms/${form.uuid}/variables`),
            getJson(`${api}/forms/${form.uuid}/logic-rules`),
          ]);
          const result = checkForm({ form, steps, variables, rules, staticVariables, serviceRoots });
          status.textContent = `Open Forms configuratiecontrole: formulier ${i + 1} van ${forms.length}, koppelingen...`;
          const links = await checkLinks(linkReferences(form, variables), resolver);
          results.push({ form, result: { ...result, findings: sortFindings([...result.findings, ...links]) } });
        } catch (error) {
          errors.push(`${form.name}: ${error.message}`);
        }
      }
      results.sort((a, b) => a.form.name.localeCompare(b.form.name, "nl"));
      pre.textContent = formatReport(results, {
        host: location.hostname, date: new Date().toLocaleString("nl-NL"), adminBase, errors, serviceRoots,
      });
      status.textContent = "Open Forms configuratiecontrole: klaar.";
      copy.disabled = download.disabled = false;
    } catch (error) {
      status.textContent = "Open Forms configuratiecontrole: mislukt.";
      pre.textContent = error.message;
    }
  })();
})();
