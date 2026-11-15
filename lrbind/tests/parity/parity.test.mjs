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
try { ({ JSDOM } = require("jsdom")); } catch {
  console.log("FAIL jsdom missing: run `npm install` in lrbind/tests of the kit");
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
    if (c.nodeType === 1 && c.tagName === "STYLE") continue;
    children.push(dump(c));
  }
  return { tag: node.tagName.toLowerCase(), attrs, classes: Array.from(node.classList).sort(), style, children };
}

// RmlUi's own warnings that have nothing to do with bindings (no font engine in the reference host)
const dataWarnings = (list) => list.filter((w) => !w.startsWith("No font face") && !w.startsWith("  ") && !/^\s*\^$/.test(w));

async function runCase(c) {
  const dom = new JSDOM(`<!doctype html><html><head></head>${c.rml}</html>`, { runScripts: "outside-only" });
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
      const p = s.params || {};
      if (el) el.dispatchEvent(new w.MouseEvent(s.type, { bubbles: true, clientX: p.mouse_x || 0, clientY: p.mouse_y || 0 }));
    }
    await tick();
    snap();
  }
  return snaps;
}

function stripRoot(dom) { return { ...dom, style: {} }; }

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
