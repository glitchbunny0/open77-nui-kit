// lrbind.js page protocol in jsdom: the Open77 bridge messages lrbind.lua sends and expects, the form-control
// controllers, and the plain-browser (mockup) mode. Parity of the bindings themselves: parity/parity.test.mjs.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "package.json"));
let JSDOM;
try { ({ JSDOM } = require("jsdom")); } catch {
  console.log("FAIL jsdom missing: run `npm install` in lrbind/tests of the kit");
  process.exit(1);
}
const SHIM = readFileSync(process.env.LRBIND_SHIM || join(here, "..", "lrbind.js"), "utf8");
const tick = () => new Promise((r) => setTimeout(r, 0));

let pass = 0, fail = 0;
const check = (cond, what) => { if (cond) pass++; else { fail++; console.log("FAIL " + what); } };

function page(body, withBridge = true) {
  const dom = new JSDOM(`<!doctype html><html><head></head><body>${body}</body></html>`, { runScripts: "outside-only" });
  const w = dom.window;
  const sent = [], handlers = {};
  if (withBridge) w.Open77 = { on: (e, fn) => { handlers[e] = fn; }, emit: (e, p) => sent.push([e, JSON.parse(JSON.stringify(p))]) };
  w.console.warn = () => {};
  w.eval(SHIM);
  const fire = async (e, p) => { handlers[e](JSON.parse(JSON.stringify(p))); await tick(); };
  const $ = (s) => w.document.querySelector(s);
  return { w, sent, handlers, fire, $, last: (e) => [...sent].reverse().find(([n]) => n === e) };
}

// ---- before init: ready is announced, nothing raw shows
{
  const p = page(`<div id="root" data-model="voice"><span id="d">{{distance}}m</span></div>`);
  check(p.sent[0] && p.sent[0][0] === "lrbind:ready", "lrbind:ready emitted at load");
  check(p.w.document.documentElement.classList.contains("lrbind-pending"), "pending class before init");
  check(p.w.getComputedStyle(p.$("#root")).visibility === "hidden", "model root hidden while pending (no raw {{x}})");
  await p.fire("lrbind:init", { models: { voice: { distance: 20 } }, events: { voice: [] } });
  check(!p.w.document.documentElement.classList.contains("lrbind-pending"), "pending class gone after init");
  check(p.$("#d").textContent === "20m", "bound after init");

  // a page reload sends init again: data refreshes, nothing doubles
  await p.fire("lrbind:init", { models: { voice: { distance: 8 } }, events: { voice: [] } });
  check(p.$("#d").textContent === "8m" && p.w.document.querySelectorAll("#d").length === 1, "second init refreshes in place");
}

// ---- set / merge / push / removeAt (paths arrive 0-based from lrbind.lua)
{
  const p = page(`<div data-model="m"><b id="t">{{title}}</b><span class="row" data-for="it : items">{{it.name}}</span><i id="n">{{items.size}}</i></div>`);
  await p.fire("lrbind:init", { models: { m: { title: "a", items: [{ name: "x" }, { name: "y" }] } }, events: {} });
  await p.fire("lrbind:set", { model: "m", path: "items[1].name", value: "Y" });
  const names = () => [...p.w.document.querySelectorAll(".row")].filter((e) => e.style.display !== "none").map((e) => e.textContent).join(",");
  check(names() === "x,Y", "set items[1].name (0-based) -> second row");
  await p.fire("lrbind:merge", { model: "m", fields: { title: "b" } });
  check(p.$("#t").textContent === "b", "merge");
  await p.fire("lrbind:push", { model: "m", path: "items", value: { name: "z" } });
  check(names() === "x,Y,z" && p.$("#n").textContent === "3", "push appends a row");
  await p.fire("lrbind:removeAt", { model: "m", path: "items", index: 0 });
  check(names() === "Y,z" && p.$("#n").textContent === "2", "removeAt 0 drops the first row");
  await p.fire("lrbind:set", { model: "m", path: "items", value: [] });
  check(names() === "" && p.$("#n").textContent === "0", "set to [] empties the list");
  await p.fire("lrbind:push", { model: "m", path: "items", value: { name: "q" } });
  check(names() === "q", "push after emptying");
}

// ---- events and errors go back to Lua
{
  const p = page(`<div data-model="m"><div id="b" data-event-click="pick(n, 'x'); n = n + 1">{{n}}</div><div id="bad">{{nope}}</div></div>`);
  await p.fire("lrbind:init", { models: { m: { n: 1 } }, events: { m: ["pick"] } });
  const err = p.last("lrbind:error");
  check(err && /nope/.test(err[1].message), "a broken binding reports lrbind:error");
  p.$("#b").dispatchEvent(new p.w.MouseEvent("click", { bubbles: true }));
  await tick();
  const ev = p.last("lrbind:event");
  check(ev && ev[1].name === "pick" && ev[1].args[0] === 1 && ev[1].args[1] === "x" && ev[1].n === 2, "lrbind:event carries name, args, n");
  const ch = p.last("lrbind:change");
  check(ch && ch[1].path === "n" && ch[1].value === 2 && p.$("#b").textContent === "2", "assignment updates the view and reports lrbind:change");
}

// ---- form controls: data-value / data-checked, two-way
{
  const p = page(`<div data-model="f">
    <input id="txt" type="text" data-value="name"/><span id="echo">{{name}}</span>
    <input id="vol" type="range" min="0" max="100" data-value="volume"/>
    <input id="cb" type="checkbox" data-checked="loud"/><span id="loud">{{loud}}</span>
    <input id="r1" type="radio" name="g" value="a" data-checked="pick"/><input id="r2" type="radio" name="g" value="b" data-checked="pick"/>
    <span id="pick">{{pick}}</span>
    <div data-for="row : rows"><input class="rc" type="checkbox" data-checked="row.on"/></div>
  </div>`);
  await p.fire("lrbind:init", { models: { f: { name: "V", volume: 30, loud: false, pick: "b", rows: [{ on: false }, { on: true }] } }, events: {} });
  check(p.$("#txt").value === "V" && p.$("#vol").value === "30", "model -> control values");
  check(p.$("#cb").checked === false && p.$("#r2").checked === true && p.$("#r1").checked === false, "model -> checked state");
  p.$("#txt").value = "Vik";
  p.$("#txt").dispatchEvent(new p.w.Event("input", { bubbles: true }));
  await tick();
  check(p.$("#echo").textContent === "Vik" && p.last("lrbind:change")[1].path === "name", "typing writes the model on every edit (RmlUi fires change per edit)");
  p.$("#cb").checked = true;
  p.$("#cb").dispatchEvent(new p.w.Event("change", { bubbles: true }));
  await tick();
  check(p.$("#loud").textContent === "1" && p.last("lrbind:change")[1].value === true, "checkbox writes a bool");
  await p.fire("lrbind:set", { model: "f", path: "loud", value: false });
  check(p.$("#cb").checked === false && !p.$("#cb").hasAttribute("checked"), "a later set unchecks a checkbox the user clicked (live state and attribute)");
  p.$("#r1").checked = true;
  p.$("#r1").dispatchEvent(new p.w.Event("change", { bubbles: true }));
  await tick();
  check(p.$("#pick").textContent === "a" && p.last("lrbind:change")[1].value === "a", "radio writes its value");
  const rc = p.w.document.querySelectorAll(".rc");
  check(rc[0].checked === false && rc[1].checked === true, "checkboxes inside data-for follow their row");
  rc[0].checked = true;
  rc[0].dispatchEvent(new p.w.Event("change", { bubbles: true }));
  await tick();
  check(p.last("lrbind:change")[1].path === "rows[0].on" && p.w.LrBind.get("f").rows[0].on === true, "a row control reports its 0-based path");
  await p.fire("lrbind:set", { model: "f", path: "name", value: "Judy" });
  check(p.$("#txt").value === "Judy", "a later set moves the control's live value too");
}

// ---- ev.* carries what RmlUi hands Lua: ints 0/1 for modifier keys, button only on button events, wheel in notches,
// a range's value as a number, a checkbox's checked, the target's value on a change that bubbled up
{
  const p = page(`<div data-model="e">
    <div id="m" data-event-mousedown="pick(ev.button, ev.ctrl_key, ev.shift_key, ev.mouse_x)" data-event-mousemove="pick(ev.button, ev.alt_key)">m</div>
    <div id="k" tabindex="0" data-event-keydown="pick(ev.ctrl_key, ev.caps_lock_key, ev.num_lock_key, ev.button, ev.mouse_x)">k</div>
    <div id="w" data-event-mousescroll="pick(ev.wheel_delta_y, ev.wheel_delta_x)">w</div>
    <input id="vol" type="range" min="0" max="100" data-value="volume" data-event-change="pick(ev.value)"/>
    <input id="cb" type="checkbox" data-event-change="pick(ev.value, ev.checked)"/>
    <div data-event-change="pick(ev.value)"><input id="t" type="text" value=""/></div>
  </div>`);
  await p.fire("lrbind:init", { models: { e: { volume: 30 } }, events: { e: ["pick"] } });
  const args = () => (p.last("lrbind:event") || [, {}])[1];
  const ev = (el, e) => { p.$(el).dispatchEvent(e); return tick(); };
  await ev("#m", new p.w.MouseEvent("mousedown", { bubbles: true, button: 2, ctrlKey: true, clientX: 7 }));
  check(JSON.stringify(args().args) === "[1,1,0,7]", "mousedown: right button is 1, modifier keys are ints 0/1 " + JSON.stringify(args().args));
  await ev("#m", new p.w.MouseEvent("mousemove", { bubbles: true, altKey: true }));
  check(args().n === 2 && args().args[0] === null && args().args[1] === 1, "mousemove carries no button " + JSON.stringify(args()));
  await ev("#k", new p.w.KeyboardEvent("keydown", { bubbles: true, ctrlKey: true, modifierCapsLock: true }));
  check(JSON.stringify(args().args) === "[1,1,0,null,null]", "keydown: ctrl and caps lock as 1, no button or mouse position " + JSON.stringify(args().args));
  await ev("#w", new p.w.WheelEvent("wheel", { bubbles: true, deltaY: 250, deltaX: -50 }));
  check(JSON.stringify(args().args) === "[2.5,-0.5]", "wheel: deltas in notches (100 px each), not just the sign " + JSON.stringify(args().args));
  await ev("#w", new p.w.WheelEvent("wheel", { bubbles: true, deltaY: 6, deltaMode: 1 }));
  check(args().args[0] === 2, "wheel in lines: 3 a notch " + JSON.stringify(args().args));
  p.$("#vol").value = "42";
  await ev("#vol", new p.w.Event("input", { bubbles: true }));
  check(args().args[0] === 42 && p.last("lrbind:change")[1].value === 42 && p.w.LrBind.get("e").volume === 42,
    "range: ev.value and the model value are numbers " + JSON.stringify([args().args, p.last("lrbind:change")[1]]));
  p.$("#cb").checked = true;
  await ev("#cb", new p.w.Event("change", { bubbles: true }));
  check(JSON.stringify(args().args) === '["on",true]', "checkbox change: value 'on' and checked true " + JSON.stringify(args().args));
  p.$("#t").value = "typed";
  await ev("#t", new p.w.Event("change", { bubbles: true }));
  check(args().args[0] === "typed", "a change that bubbles up carries the target's value " + JSON.stringify(args().args));
}

// ---- plain browser (a mockup): no Open77, init by hand, nothing pending
{
  const p = page(`<div data-model="voice"><span id="d">{{mode | to_upper}}</span></div>`, false);
  check(!p.w.document.documentElement.classList.contains("lrbind-pending"), "no pending class without the bridge");
  p.w.LrBind.init({ models: { voice: { mode: "whisper" } } });
  check(p.$("#d").textContent === "WHISPER", "LrBind.init binds a mockup");
  p.w.LrBind.set("voice", "mode", "shout");
  await tick();
  check(p.$("#d").textContent === "SHOUT", "LrBind.set in a mockup");
}

// ---- two models in one page, each under its own data-model root
{
  const p = page(`<div data-model="a"><span id="x">{{v}}</span></div><div data-model="b"><span id="y">{{v}}</span></div>`);
  await p.fire("lrbind:init", { models: { a: { v: 1 }, b: { v: 2 } }, events: {} });
  await p.fire("lrbind:set", { model: "b", path: "v", value: 5 });
  check(p.$("#x").textContent === "1" && p.$("#y").textContent === "5", "models stay apart");
}

// ---- the bracket rule keeps a mockup honest about what the game drops
{
  const p = page(`<div data-model="m"><span id="ok">{{a}}</span><span id="broken">{{a} }}</span><span id="after">after</span></div>`);
  await p.fire("lrbind:init", { models: { m: { a: 1 } }, events: {} });
  check(p.$("#ok").textContent === "1" && !p.$("#after") && p.$("#broken").textContent === "", "text after a bracket error is removed, as NativeUI never loads it");
  check(/stops loading/.test((p.last("lrbind:error") || [, {}])[1].message || ""), "and lrbind:error says so");
}

console.log(`protocol: ${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
