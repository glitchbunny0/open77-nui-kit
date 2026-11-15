// Parity cases: each runs in real RmlUi 6.3 (the kit's rmlhost parity mode, output kept in golden.json) and through lrbind.js
// in jsdom; parity.test.mjs compares the element trees after every step. Markup must parse the same as XML (RmlUi)
// and as HTML (WebUI): write && as &amp;&amp; and < as &lt; (or keep a space after it), use div/span/b only.
// Steps: { set: "path (0-based)", value } or { event: "<id>", type: "click", params: { mouse_x } }.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const T = (name, rml, model, extra = {}) => ({ name, rml: `<body data-model="m">${rml}</body>`, model, ...extra });

// Shared blocks of real documents, read from the files themselves: a change to one fails parity until the golden
// file is regenerated through RmlUi (bin/lrbind-parity --regen). Your own suite imports sharedBlock the same way.
const here = dirname(fileURLToPath(import.meta.url));
export function sharedBlock(file, name, base = here) {
  const text = readFileSync(join(base, file), "utf8");
  const m = text.match(new RegExp(`<!-- ${name}: begin[\\s\\S]*?-->([\\s\\S]*?)<!-- ${name}: end -->`));
  if (!m) throw new Error(`no '${name}' block in ${file}`);
  return m[1];
}
const VOICE_EMPTY = { vOn: false, vState: "offline", vMode: "normal", vLabel: "", vDist: 0, vKey: "", vTalk: 0, vLit: 0 };

export const cases = [
  // ---- precedence and operators (Parse::Expression > Relational > Additive > Term > Factor)
  T("arith precedence", `<div>{{1 + 2 * 3}}|{{(1 + 2) * 3}}|{{10 - 4 - 3}}|{{12 / 3 / 2}}|{{7 - -2}}</div>`, {}),
  T("relational binds looser than additive", `<div>{{a + 1 > b + 1}}|{{a > b == true}}|{{1 &lt; 2 &lt; 3}}|{{3 > 2 > 1}}</div>`, { a: 3, b: 2 }),
  T("and/or left to right", `<div>{{t &amp;&amp; f || t}}|{{f || t &amp;&amp; f}}|{{a > 1 &amp;&amp; b &lt; 5}}</div>`, { t: true, f: false, a: 3, b: 2 }),
  T("not binds to a factor", `<div>{{!t}}|{{!t == false}}|{{!(a > b)}}|{{!a}}|{{!0}}</div>`, { t: true, a: 3, b: 2 }),
  T("ternary takes the rest", `<div>{{a > 1 ? 'big' : 'small'}}|{{f ? 'x' : a > 5 ? 'y' : 'z'}}|{{f ? 1 : 2 + 3}}|{{t ? 'p' : 'q' | to_upper}}|{{f ? 'p' : 'q' | to_upper}}</div>`, { t: true, f: false, a: 3 }),
  T("pipe after and", `<div>{{t &amp;&amp; t | to_upper}}|{{'hot' + 'dog' | to_upper}}</div>`, { t: true }),
  T("doc example", `<div>{{true || false ? (true &amp;&amp; 3==1+2 ? 'Absolutely!' : 'well..') : 'no'}}</div>`, {}),

  // ---- conversions (TypeConverter): bools print 1/0, strings are bools only as 1/0/true/false
  T("bool to string and number", `<div>{{t}}|{{f}}|{{t + 1}}|{{t + 'x'}}|{{t == 1}}|{{t == '1'}}</div>`, { t: true, f: false }),
  T("string truthiness", `<div>{{'abc' ? 'y' : 'n'}}|{{'true' ? 'y' : 'n'}}|{{'TRUE' ? 'y' : 'n'}}|{{'1' ? 'y' : 'n'}}|{{'' ? 'y' : 'n'}}|{{s ? 'y' : 'n'}}</div>`, { s: "yes" }),
  T("string plus number concatenates", `<div>{{'5' + 1}}|{{s + 1}}|{{n + 1}}|{{s * 2}}|{{'12px' * 1}}|{{'abc' * 1}}|{{s - 1}}</div>`, { s: "5", n: 5 }),
  T("equality string vs number", `<div>{{s == 5}}|{{s == n}}|{{d == n}}|{{d == 5}}|{{z == ''}}</div>`, { s: "5.0", n: 5, d: 5.0, z: "" }),
  T("number formatting", `<div>{{0.1 + 0.2}}|{{1 / 3}}|{{2 / 3}}|{{n}}|{{d}}|{{-0.0001}}|{{1 / 0}}|{{-1 / 0}}|{{big}}|{{neg}}</div>`, { n: 20, d: 20.5, big: 123456789.125, neg: -2.5 }),
  T("printf ties to even", `<div>{{a}}|{{b}}|{{c}}|{{dd}}|{{e}}</div>`, { a: 0.0625, b: 2.0625, c: 0.1875, dd: 1.0005, e: -0.0625 }),
  T("int and double model numbers print alike", `<div>{{i}}|{{x}}|{{i + x}}|{{i / 2}}</div>`, { i: 7, x: 7.0 }),

  // ---- transforms
  T("format", `<div>{{x | format(2)}}|{{x | format(0)}}|{{y | format(0)}}|{{z | format(0)}}|{{w | format(2, true)}}|{{5 | format(2, true)}}|{{x | format(1, false)}}|{{x | format(40)}}|{{x | format}}|{{format(x, 3)}}</div>`, { x: 2.25, y: 2.5, z: 3.5, w: 8.7 }),
  T("format trailing zeros", `<div>{{a | format(3, true)}}|{{b | format(0, true)}}|{{c | format(2, 'yes')}}|{{c | format(2, 'true')}}|{{c | format('2')}}</div>`, { a: 1.5, b: 7, c: 1.234 }),
  T("round", `<div>{{a | round}}|{{b | round}}|{{c | round}}|{{'2.6' | round}}|{{round(1.49)}}</div>`, { a: 2.5, b: -2.5, c: 0.49999999999999994 }),
  T("case transforms are ascii", `<div>{{'aBc' | to_upper}}|{{'ÄbÇ' | to_lower}}|{{'straße' | to_upper}}|{{n | to_upper}}|{{t | to_upper}}</div>`, { n: 1.5, t: true }),

  // ---- addresses
  T("arrays and structs", `<div>{{list.size}}|{{list[1]}}|{{items[1].name}}|{{items.size}}|{{empty.size}}|{{obj.a.b}}</div>`,
    { list: ["p", "q", "r"], items: [{ name: "a" }, { name: "b" }], empty: {}, obj: { a: { b: 42 } } }),
  T("dynamic index", `<div>{{list[sel]}}|{{list[sel + 1]}}|{{items[sel].name}}|{{list['1']}}|{{list[1.9]}}</div>`,
    { list: ["p", "q", "r"], items: [{ name: "a" }, { name: "b" }], sel: 0 }, { steps: [{ set: "sel", value: 1 }] }),
  T("misses are empty", `<div>[{{list[9]}}]|[{{items[0].nope}}]|[{{obj.x.y}}]|[{{list}}]|[{{obj}}]</div>`,
    { list: ["p"], items: [{ name: "a" }], obj: { x: 1 } }),
  T("negative dynamic index fails the run", `<div>{{list[i]}}</div><span>{{list[i]}} ok</span>`, { list: ["p", "q"], i: 0 },
    { steps: [{ set: "i", value: -1 }, { set: "i", value: 1 }] }),

  // ---- broken bindings: a parse error drops the binding and leaves the text as written
  T("parse errors", `<div>{{a +}}</div><div>{{-a}}</div><div>{{nope}}</div><div>{{a ++ 1}}</div><div>{{.5 + a}}</div><div>{{a &amp; a}}</div><div>{{1 + a}} and {{a +}}</div>`, { a: 1 }),
  T("runtime errors keep the old text", `<div>{{nofn(a)}}</div><div>{{a}} {{nofn(a)}}</div>`, { a: 1 }, { steps: [{ set: "a", value: 2 }] }),
  // a bracket mistake in text is an XML error natively: the document stops loading right there
  T("bracket error: single close", `<div>ok {{a}}</div><div><b>{{a} }}</b> lost</div><div>lost too</div>`, { a: 1 }),
  T("bracket error: close outside", `<div>{{a}}</div><div>x }} y</div><span>lost</span>`, { a: 1 }),
  T("bracket error: nested", `<div>{{ {{a}} }}</div><span>lost</span>`, { a: 1 }),
  T("bracket ok: braces in a string", `<div>{{ 'a}}b' }}|{{ '{{' }}</div><span>kept</span>`, { a: 1 }),
  T("bracket ok: lt inside brackets", `<div>{{a &lt; 2}}|{{ a &lt;2 }}</div><span>kept</span>`, { a: 1 }),
  T("bracket error: backslash quote in text", `<div>{{'it\\'s'}}</div><span>lost</span>`, {}),
  T("backslash in attributes is fine", `<div data-attr-title="'it\\'s'" data-attr-alt="'back\\\\slash'">{{'a' + 'b' + 1 + 2}}|{{1 + 2 + 'a'}}</div>`, {}),
  T("whitespace", `<div>{{   a+1   }}|{{a  *  2}}|{{ ( a ) }}</div>`, { a: 3 }),

  // ---- views
  T("class attr attrif style", `<div id="v" data-class-hot="a > 2" data-class-cold="a &lt; 2" data-attr-title="'n=' + a" data-attrif-disabled="a > 2" data-style-width="a * 10 + '%'">x</div>`,
    { a: 3 }, { steps: [{ set: "a", value: 1 }, { set: "a", value: 5 }] }),
  T("if and visible", `<div data-if="show">A</div><div data-visible="show">B</div><div style="display: block;" data-if="show">C</div><div style="visibility: visible;" data-visible="show">D</div>`,
    { show: true }, { steps: [{ set: "show", value: false }, { set: "show", value: true }] }),
  T("rml view", `<div data-rml="'&lt;b>' + a + '&lt;/b> tail'"></div>`, { a: "x" }, { steps: [{ set: "a", value: "y" }] }),
  T("alias", `<div data-alias-first="items[0]"><span>{{first.name}}</span></div>`, { items: [{ name: "a" }, { name: "b" }] },
    { steps: [{ set: "items[0].name", value: "z" }] }),

  // ---- data-for
  T("for basics", `<div data-for="item, i : items" data-class-sel="i == sel"><span>{{i}}:{{item.name}} of {{items.size}}</span></div>`,
    { items: [{ name: "a" }, { name: "b" }, { name: "c" }], sel: 1 },
    { steps: [{ set: "sel", value: 2 }, { set: "items", value: [{ name: "x" }] }, { set: "items", value: [{ name: "x" }, { name: "y" }, { name: "w" }, { name: "v" }] }, { set: "items[1].name", value: "Y" }] }),
  T("for default names", `<div data-for="list">{{it_index}}={{it}}</div>`, { list: ["p", "q"] }, { steps: [{ set: "list", value: [] }] }),
  T("for iterator only", `<div data-for="x : list">{{x}}/{{it_index}}</div>`, { list: ["p", "q"] }),
  T("for nested", `<div data-for="row, r : rows"><b>{{row.label}}</b><span data-for="cell, c : row.cells">{{r}}.{{c}}={{cell}}</span></div>`,
    { rows: [{ label: "A", cells: [1, 2] }, { label: "B", cells: [] }, { label: "C", cells: [3] }] },
    { steps: [{ set: "rows[1].cells", value: [9, 8, 7] }, { set: "rows", value: [{ label: "Z", cells: [0] }] }] }),
  T("for over empty object and scalar", `<div data-for="e">{{it}}</div><div data-for="s">{{it}}</div>`, { e: {}, s: 5 }),
  T("global names shadow iterators", `<div data-for="a : list">{{a}}</div>`, { a: "global", list: ["p", "q"] }),
  T("for with if inside", `<div data-for="item : items"><span data-if="item.on">{{item.name}}</span></div>`,
    { items: [{ name: "a", on: true }, { name: "b", on: false }] }, { steps: [{ set: "items[1].on", value: true }] }),
  T("for ids repeat", `<div id="row" data-for="list">{{it}}</div>`, { list: ["p", "q"] }),

  // ---- events (assignment expressions)
  T("event call and assign", `<div id="btn" data-event-click="pick(a, 'x' + 1); a = a + 1">{{a}}</div>`, { a: 3 },
    { events: ["pick"], steps: [{ event: "btn", type: "click" }, { event: "btn", type: "click" }] }),
  T("undeclared event stops the chain", `<div id="btn" data-event-click="a = a + 1; nope(); a = a + 10">{{a}}</div>`, { a: 0 },
    { events: ["pick"], steps: [{ event: "btn", type: "click" }] }),
  T("event params", `<div id="btn" data-event-mousedown="pick(ev.mouse_x, ev.nope); last = ev.mouse_y">{{last}}</div>`, { last: 0 },
    { events: ["pick"], steps: [{ event: "btn", type: "mousedown", params: { mouse_x: 12, mouse_y: 34 } }] }),
  T("assign a string, then a bool", `<div id="btn" data-event-click="s = 'clicked'; b = !b">{{s}}/{{b}}</div>`, { s: "idle", b: false },
    { steps: [{ event: "btn", type: "click" }] }),
  T("shared block read from a file (fixtures/voice.rml)", sharedBlock("fixtures/voice.rml", "voice"), { ...VOICE_EMPTY },
    { steps: [
      { set: "vOn", value: true }, { set: "vState", value: "idle" }, { set: "vLabel", value: "NORMAL" },
      { set: "vDist", value: 20 }, { set: "vKey", value: "F11" },
      { set: "vState", value: "talking" }, { set: "vMode", value: "shout" }, { set: "vLit", value: 12 }, { set: "vTalk", value: 2 },
      { set: "vDist", value: 3.5 }, { set: "vLit", value: 5 }, { set: "vState", value: "muted" }, { set: "vTalk", value: 0 },
      { set: "vOn", value: false },
    ] }),
  T("bad assignment drops the controller", `<div id="btn" data-event-click="a + 1">{{a}}</div><div id="btn2" data-event-click="nope = 1">{{a}}</div>`, { a: 0 },
    { steps: [{ event: "btn", type: "click" }, { event: "btn2", type: "click" }] }),
];
