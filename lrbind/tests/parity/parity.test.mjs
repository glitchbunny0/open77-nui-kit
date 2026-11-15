// lrbind.js parity with RmlUi 6.3: every case runs through the shim in jsdom and is compared, snapshot by snapshot,
// with what real RmlUi produced (the golden file, written by bin/lrbind-parity --regen through rmlhost parity).
//   node parity.test.mjs                    compare cases.mjs against golden.json
//   node parity.test.mjs --cases F --golden G   your own suite: F exports `cases`, G is its golden file
//   node parity.test.mjs --emit-cases       print the cases as JSON (the regen pipes them into rmlhost parity)
//   node parity.test.mjs --only <substr>    run the matching cases, print both trees on a mismatch
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "..", "package.json"));
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? resolve(args[args.indexOf(k) + 1]) : d);
const casesFile = opt("--cases", join(here, "cases.mjs"));
const goldenFile = opt("--golden", join(here, "golden.json"));
const { cases } = await import(pathToFileURL(casesFile).href);

if (args.includes("--emit-cases")) {
  // no process.exit here: it cuts a piped stdout off at 64 KiB
  process.stdout.write(JSON.stringify(cases));
} else {
  await main();
}

async function main() {

let JSDOM;
try { ({ JSDOM } = require("jsdom")); } catch (e) {
  // jsdom 29 needs Node ^20.19 || ^22.13 || >=24; on an older Node it is there but does not load
  console.log(`FAIL jsdom does not load (Node ${process.versions.node}; it needs 20.19+): run \`npm ci\` in lrbind/tests of the kit. ${String(e && e.message).split("\n")[0]}`);
  process.exit(1);
}

const SHIM = readFileSync(process.env.LRBIND_SHIM || join(here, "..", "..", "lrbind.js"), "utf8");   // env: mutation runs
const golden = JSON.parse(readFileSync(goldenFile, "utf8"));
const only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;
const tick = () => new Promise((r) => setTimeout(r, 0));

const collapse = (s) => s.replace(/[ \n\t\r]+/g, " ").trim();

function dump(node) {
  if (node.nodeType === 3) return { text: collapse(node.nodeValue) };
  const attrs = {};
  for (const a of Array.from(node.attributes).sort((x, y) => (x.name < y.name ? -1 : 1))) {
    if (a.name.startsWith("data-") || a.name === "class" || a.name === "style") continue;
    attrs[a.name] = a.value;
  }
  const style = {};
  const names = Array.from(node.style).sort();
  for (const n of names) style[n] = node.style.getPropertyValue(n);
  const children = [];
  for (const c of node.childNodes) {
    if (c.nodeType === 3 && collapse(c.nodeValue) === "") continue;
    if (c.nodeType !== 1 && c.nodeType !== 3) continue;
    if (c.nodeType === 1 && c.tagName.toUpperCase() === "STYLE") continue;
    children.push(dump(c));
  }
  return { tag: node.tagName.toLowerCase(), attrs, classes: Array.from(node.classList).sort(), style, children };
}

// What RmlUi's form controls add to themselves, and nothing else: ElementFormControl sets a local `tab-index: auto`,
// ElementFormControlInput sets a class named after its type ("text" when the type is unknown), and the text widget
// (text/password inputs, textarea) sets seven local properties. Dropped on both sides, so the rest of an <input> (its
// attributes, other classes and styles) is still compared.
const INPUT_TYPES = new Set(["password", "radio", "checkbox", "range", "submit", "button"]);
const TEXT_WIDGET = { "white-space": ["pre"], "overflow-x": ["hidden"], "overflow-y": ["hidden"], drag: ["drag"],
  "word-break": ["break-word"], "text-transform": ["none"], clip: ["auto", "always"] };
function formNoise(d) {
  if (!d.tag) return d;
  d = { ...d, children: d.children.map(formNoise) };
  if (d.tag !== "input" && d.tag !== "textarea" && d.tag !== "select") return d;
  const style = { ...d.style };
  if (style["tab-index"] === "auto") delete style["tab-index"];
  let classes = d.classes;
  const type = INPUT_TYPES.has(d.attrs.type) ? d.attrs.type : "text";
  if (d.tag === "input") classes = classes.filter((c) => c !== type);
  if (d.tag === "textarea" || (d.tag === "input" && (type === "text" || type === "password"))) {
    for (const [k, vs] of Object.entries(TEXT_WIDGET)) if (vs.includes(style[k])) delete style[k];
  }
  return { ...d, classes, style };
}

// RmlUi's own warnings that have nothing to do with bindings (no font engine in the reference host)
const dataWarnings = (list) => list.filter((w) => !w.startsWith("No font face") && !w.startsWith("  ") && !/^\s*\^$/.test(w));

// A step's event as the DOM fires it. params are RmlUi's (button 1 = right, modifiers 0/1, wheel in notches); the shim
// must turn the DOM's form back into exactly those.
const DOM_TYPE = { mousescroll: "wheel", textinput: "input" };
function domEvent(w, type, p) {
  const mods = { ctrlKey: !!p.ctrl_key, shiftKey: !!p.shift_key, altKey: !!p.alt_key, metaKey: !!p.meta_key };
  const mouse = { clientX: p.mouse_x || 0, clientY: p.mouse_y || 0, button: p.button === 1 ? 2 : p.button === 2 ? 1 : p.button || 0 };
  const t = DOM_TYPE[type] || type;
  if (/^key/.test(type)) return new w.KeyboardEvent(t, { bubbles: true, ...mods });
  if (type === "mousescroll") return new w.WheelEvent(t, { bubbles: true, ...mods, ...mouse, deltaX: (p.wheel_delta_x || 0) * 100, deltaY: (p.wheel_delta_y || 0) * 100 });
  if (/^(mouse|click|dblclick)/.test(type)) return new w.MouseEvent(t, { bubbles: true, ...mods, ...mouse });
  return new w.Event(t, { bubbles: true });
}

async function runCase(c) {
  // xhtml: the page parsed as XML, as RmlUi parses a document (attribute names keep their case)
  const dom = c.xhtml
    ? new JSDOM(`<html xmlns="http://www.w3.org/1999/xhtml"><head></head>${c.rml}</html>`, { runScripts: "outside-only", contentType: "application/xhtml+xml" })
    : new JSDOM(`<!doctype html><html><head></head>${c.rml}</html>`, { runScripts: "outside-only" });
  const w = dom.window;
  const emitted = [];
  const handlers = {};
  w.Open77 = {
    on: (e, fn) => { handlers[e] = fn; },
    emit: (e, payload) => emitted.push([e, payload]),
  };
  w.eval(SHIM);
  const warns = [];
  w.LrBind.onError((m) => warns.push(m));
  w.console.warn = () => {};
  handlers["lrbind:init"]({ models: { m: structuredClone(c.model) }, events: { m: c.events || [] } });
  await tick();
  const snaps = [];
  const snap = () => {
    const root = dump(w.document.body);
    const calls = emitted.filter(([e]) => e === "lrbind:event").map(([, p]) => p.name + "(" + p.args.map((a) => w.LrBind._expr.toStr(a)).join(",") + ")");
    emitted.length = 0;
    snaps.push({ dom: root, calls, warned: warns.length > 0 });
    warns.length = 0;
  };
  snap();
  for (const s of c.steps || []) {
    if (s.set !== undefined) handlers["lrbind:set"]({ model: "m", path: s.set, value: structuredClone(s.value) });
    if (s.event !== undefined) {
      const el = w.document.getElementById(s.event);
      if (el) el.dispatchEvent(domEvent(w, s.type, s.params || {}));
    }
    await tick();
    snap();
  }
  return snaps;
}

function stripRoot(dom) { return formNoise({ ...dom, style: {} }); }

const sameJson = (a, b) => JSON.stringify(a) === JSON.stringify(b);

let failed = 0, passed = 0, checks = 0;
const byName = new Map(golden.map((g) => [g.name, g]));
for (const c of cases) {
  if (only && !c.name.includes(only)) continue;
  const ref = byName.get(c.name);
  if (!ref) { console.log(`FAIL ${c.name}: not in the golden file (run bin/lrbind-parity --regen)`); failed++; continue; }
  const got = await runCase(c);
  let ok = ref.snapshots.length === got.length;
  const notes = [];
  if (!ok) notes.push(`snapshots ${got.length} vs RmlUi ${ref.snapshots.length}`);
  for (let i = 0; ok && i < got.length; i++) {
    checks++;
    const r = ref.snapshots[i], g = got[i];
    if (!sameJson(stripRoot(r.dom), stripRoot(g.dom))) { ok = false; notes.push(`step ${i}: tree differs`); }
    if (!sameJson(r.calls, g.calls)) { ok = false; notes.push(`step ${i}: calls ${JSON.stringify(g.calls)} vs RmlUi ${JSON.stringify(r.calls)}`); }
    const rw = dataWarnings(r.warnings).length > 0;
    if (rw !== g.warned) { ok = false; notes.push(`step ${i}: warned=${g.warned} vs RmlUi ${rw} (${JSON.stringify(dataWarnings(r.warnings))})`); }
    if (!ok && (only || args.includes("-v"))) {
      console.log("  RmlUi :", JSON.stringify(stripRoot(r.dom)));
      console.log("  lrbind:", JSON.stringify(stripRoot(g.dom)));
    }
  }
  if (ok) passed++;
  else { failed++; console.log(`FAIL ${c.name}: ${notes.join("; ")}`); }
}
console.log(`parity: ${passed} cases passed, ${failed} failed (${checks} snapshots compared with RmlUi 6.3)`);
process.exitCode = failed ? 1 : 0;
}
