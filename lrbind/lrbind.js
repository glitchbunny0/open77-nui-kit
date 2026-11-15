// SPDX-License-Identifier: MIT
// lrbind.js, part of open77-nui-kit.
// Copyright (c) 2026 the open77-nui-kit authors
// The expression parser, interpreter and data views are ported from RmlUi (https://github.com/mikke89/RmlUi):
// Copyright (c) 2008-2014 CodePoint Ltd, Shift Technology Ltd, and contributors
// Copyright (c) 2019-2026 The RmlUi Team, and contributors
//
// Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
// documentation files (the "Software"), to deal in the Software without restriction, including without limitation
// the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
// permit persons to whom the Software is furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all copies or substantial portions of
// the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
// THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
// TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// lrbind.js: RmlUi data bindings ({{x}}, data-for, data-if, data-class-*, data-event-*, ...) for a WebUI page.
// The same markup runs as a NativeUI document, so a page and its native twin share one source. The expression
// parser and interpreter follow RmlUi 6.3 (DataExpression.cpp) instruction for instruction, the views follow
// DataViewDefault.cpp: precedence, type conversions and number formatting come out the same as in the game.
// Lua talks to it through lrbind.lua (lrbind:init/set/merge/push/removeAt in, lrbind:event/change/error out).
(function (global) {
  "use strict";

  // ---------------------------------------------------------------------------------------------------------
  // Values. A model value is a JS string, number or boolean; undefined stands for RmlUi's empty Variant.
  // Conversions follow Rml::TypeConverter: numbers print with "%.3f" minus trailing zeros, booleans as 1/0,
  // a string reads as a bool only when it is 1/0/true/false, and as a number through atof.

  const NONE = undefined;
  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  // obj[key] = v that stays an own property: a key "__proto__" must not reach Object.prototype
  function setOwn(obj, key, v) {
    if (key === "__proto__") Object.defineProperty(obj, key, { value: v, writable: true, enumerable: true, configurable: true });
    else obj[key] = v;
  }
  const isScalar = (v) => typeof v === "string" || typeof v === "number" || typeof v === "boolean";

  // printf("%.<p>f") for a double: correctly rounded, exact ties to even (JS toFixed breaks ties upwards).
  function fixed(x, p) {
    if (Number.isNaN(x)) return "nan";
    if (x === Infinity) return "inf";
    if (x === -Infinity) return "-inf";
    const neg = x < 0 || Object.is(x, -0);
    const a = Math.abs(x);
    let digits;
    const scaled = a * Math.pow(2, p + 1);
    if (Number.isInteger(scaled) && scaled % 2 === 1 && scaled <= Number.MAX_SAFE_INTEGER) {
      // a * 10^p sits exactly halfway: q * 5^p / 2 with q odd
      const q = BigInt(scaled) * 5n ** BigInt(p);
      let k = (q - 1n) / 2n;
      if (k % 2n === 1n) k += 1n;
      digits = k.toString();
    } else if (a >= 1e21) {
      digits = BigInt(a).toString() + "0".repeat(p);
    } else {
      digits = a.toFixed(p).replace(".", "");
    }
    if (p > 0) {
      digits = digits.padStart(p + 1, "0");
      digits = digits.slice(0, digits.length - p) + "." + digits.slice(digits.length - p);
    }
    return (neg ? "-" : "") + digits;
  }

  function trimDotZeros(s) {
    let n = s.length;
    for (let i = s.length - 1; i >= 0; i--) {
      if (s[i] === ".") { n = i; break; }
      if (s[i] === "0") n = i; else break;
    }
    return s.slice(0, n);
  }

  function toStr(v) {
    if (typeof v === "string") return v;
    if (typeof v === "boolean") return v ? "1" : "0";
    if (typeof v === "number") return trimDotZeros(fixed(v, 3));
    return "";
  }

  // atof: leading blanks, an optional sign, digits with one dot, an optional exponent; inf/nan words.
  function atof(s) {
    const m = /^[ \t\n\v\f\r]*([+-]?)(?:(inf(?:inity)?|nan)|((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))/i.exec(s);
    if (!m) return 0;
    const sign = m[1] === "-" ? -1 : 1;
    if (m[2]) return /^n/i.test(m[2]) ? NaN : sign * Infinity;
    return sign * parseFloat(m[3]);
  }

  function toNum(v) {
    if (typeof v === "number") return v;
    if (typeof v === "boolean") return v ? 1 : 0;
    if (typeof v === "string") return atof(v);
    return 0;
  }

  function toBool(v) {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") {
      const l = v.toLowerCase();
      return l === "1" || l === "true";
    }
    return false;
  }

  // GetInto<int>: doubles truncate, strings go through sscanf("%d"); an empty value fails.
  function toInt(v) {
    if (typeof v === "number") return Number.isFinite(v) ? Math.trunc(v) | 0 : null;
    if (typeof v === "boolean") return v ? 1 : 0;
    if (typeof v === "string") {
      const m = /^[ \t\n\v\f\r]*([+-]?\d+)/.exec(v);
      return m ? parseInt(m[1], 10) | 0 : null;
    }
    return null;
  }

  const asciiUpper = (s) => s.replace(/[a-z]+/g, (c) => c.toUpperCase());
  const asciiLower = (s) => s.replace(/[A-Z]+/g, (c) => c.toLowerCase());

  // The built-in transforms (DataTypeRegister.cpp). A bad call returns NONE, as RmlUi's do.
  const TRANSFORMS = {
    to_upper: (a) => (a.length === 1 && a[0] !== NONE ? asciiUpper(toStr(a[0])) : NONE),
    to_lower: (a) => (a.length === 1 && a[0] !== NONE ? asciiLower(toStr(a[0])) : NONE),
    round: (a) => (a.length === 1 && a[0] !== NONE ? Math.floor(toNum(a[0]) + 0.5) : NONE),
    format: (a) => {
      if (a.length < 2 || a.length > 3) { warn("Transform function 'format' requires at least two arguments, at most three arguments."); return NONE; }
      const p = a[1] === NONE ? null : toInt(a[1]);
      if (p === null || p < 0 || p > 32) { warn("Transform function 'format': Second argument must be an integer in [0, 32]."); return NONE; }
      let trim = false;
      if (a.length >= 3) {
        if (typeof a[2] === "string") {
          const l = a[2].toLowerCase();
          if (l !== "1" && l !== "true" && l !== "0" && l !== "false") return NONE;
        } else if (a[2] === NONE) return NONE;
        trim = toBool(a[2]);
      }
      if (a[0] === NONE) return NONE;
      let s = fixed(toNum(a[0]), p);
      if (trim) {
        if (p === 0 && !/[a-z]/.test(s)) s += ".";   // "%#.0f" keeps the dot, then it is trimmed
        s = trimDotZeros(s);
      }
      return s;
    },
  };

  // ---------------------------------------------------------------------------------------------------------
  // Messages. Where RmlUi warns, the shim warns too (the parity suite compares whether each step warned): console +
  // lrbind:error to Lua (it lands in the client log).

  let errorSink = null;
  function warn(message) {
    if (typeof console !== "undefined") console.warn("[lrbind] " + message);
    if (errorSink) errorSink(message);
  }

  // ---------------------------------------------------------------------------------------------------------
  // Addresses: "a.b[2].c" -> ["a", "b", 2, "c"] (DataModel.cpp ParseAddress). Index entries are numbers.

  function parseAddress(str) {
    const list = str.split(".").map((s) => s.trim());
    const out = [];
    for (const item of list) {
      if (item === "") return null;
      let open = item.indexOf("[");
      if (open === 0) return null;
      out.push(open < 0 ? item : item.slice(0, open));
      while (open >= 0) {
        const close = item.indexOf("]", open + 1);
        if (close < 0) return null;
        const index = toInt(item.slice(open + 1, close + 1));
        if (index === null || index < 0) return null;
        out.push(index);
        open = item.indexOf("[", close + 1);
      }
    }
    return out.length ? out : null;
  }

  // ---------------------------------------------------------------------------------------------------------
  // Expression compiler: a port of Rml::DataParser and the Parse namespace. Programs are instruction lists run
  // by the interpreter below, with the same R/L registers and stack.

  const I = {
    Push: "P", Pop: "o", Literal: "D", Variable: "V", Add: "+", Subtract: "-", Multiply: "*", Divide: "/",
    Not: "!", And: "&", Or: "|", Less: "<", LessEq: "L", Greater: ">", GreaterEq: "G", Equal: "=",
    NotEqual: "N", Ternary: "?", NumArguments: "#", TransformFnc: "T", EventFnc: "E", Assign: "A",
    DynamicVariable: "Y", CastToInt: "I", Jump: "J", JumpIfZero: "Z",
  };
  const REG_R = 0, REG_L = 1;

  class Parser {
    constructor(expression, iface) {
      this.expression = expression;
      this.iface = iface;
      this.index = 0;
      this.reachedEnd = false;
      this.parseError = true;
      this.stackSize = 0;
      this.program = [];
      this.addresses = [];
    }
    look() { return this.reachedEnd ? "\0" : this.expression[this.index]; }
    match(c, skipWhitespace = true) {
      if (c === this.look()) {
        this.next();
        if (skipWhitespace) this.skipWhitespace();
        return true;
      }
      this.expectedChar(c);
      return false;
    }
    next() {
      this.index += 1;
      if (this.index >= this.expression.length) this.reachedEnd = true;
      return this.look();
    }
    skipWhitespace() {
      let c = this.look();
      while (c === " " || c === "\t" || c === "\n" || c === "\r" || c === "\f" || c === "\v") c = this.next();
    }
    error(message) {
      this.parseError = true;
      warn("Error in data expression at " + this.index + ". " + message + "  \"" + this.expression + "\"");
    }
    expected(symbols) {
      const c = this.look();
      if (c === "\0") this.error("Expected " + symbols + " but found end of string.");
      else this.error("Expected " + symbols + " but found character '" + c + "'.");
    }
    expectedChar(c) { this.expected("'" + c + "'"); }
    parse(isAssignment) {
      this.program = [];
      this.addresses = [];
      this.index = 0;
      this.reachedEnd = false;
      this.parseError = false;
      if (this.expression.length === 0) this.reachedEnd = true;
      this.skipWhitespace();
      if (isAssignment) parseAssignment(this); else parseExpression(this);
      if (!this.reachedEnd) {
        this.parseError = true;
        this.error("Unexpected character '" + this.look() + "' encountered.");
      }
      if (!this.parseError && this.stackSize !== 0) {
        this.parseError = true;
        this.error("Internal parser error, inconsistent stack operations.");
      }
      return !this.parseError;
    }
    emit(op, data) { this.program.push([op, data]); }
    push() { this.stackSize += 1; this.program.push([I.Push]); }
    pop(reg) {
      if (this.stackSize <= 0) { this.error("Internal parser error: Tried to pop an empty stack."); return; }
      this.stackSize -= 1;
      this.program.push([I.Pop, reg]);
    }
    fn(op, numArguments, name) {
      if (this.stackSize < numArguments) { this.error("Internal parser error: Popping arguments from a short stack."); return; }
      this.stackSize -= numArguments;
      this.program.push([I.NumArguments, numArguments]);
      this.program.push([op, name]);
    }
    variable(name) { this.variableGetSet(name, false); }
    assign(name) { this.variableGetSet(name, true); }
    state() { return [this.program.length, this.stackSize]; }
    setState(s) { this.program.length = s[0]; this.stackSize = s[1]; }
    addVariableAddress(name) {
      const address = this.iface.parseAddress(name);
      if (!address) return false;
      this.addresses.push(address);
      return true;
    }
    variableGetSet(name, isAssignment) {
      const address = this.iface.parseAddress(name);
      if (!address) { this.error("Could not find data variable with name '" + name + "'."); return; }
      const index = this.addresses.length;
      this.addresses.push(address);
      this.program.push([isAssignment ? I.Assign : I.Variable, index]);
    }
  }

  function isVariableCharacter(c, first) {
    const alpha = (c >= "a" && c <= "z") || (c >= "A" && c <= "Z");
    if (first) return alpha;
    return alpha || (c >= "0" && c <= "9") || c === "_" || c === ".";
  }

  function variableOrFunctionName(p, out) {
    let name = "";
    let first = true;
    let c = p.look();
    while (c !== "\0" && isVariableCharacter(c, first)) {
      name += c;
      c = p.next();
      first = false;
    }
    if (out) out.valid = name.indexOf(".") < 0 && name.indexOf(" ") < 0;
    return name;
  }

  function findNumberLiteral(p, silent) {
    let str = "";
    let firstMatch = false;
    let hasDot = false;
    let c = p.look();
    if (c === "-") { str += c; c = p.next(); }
    while ((c >= "0" && c <= "9") || (c === "." && !hasDot)) {
      firstMatch = true;
      str += c;
      if (c === ".") hasDot = true;
      c = p.next();
    }
    if (!firstMatch) {
      if (!silent) p.error("Invalid number literal. Expected '0-9' or '.' but found '" + c + "'.");
      return "";
    }
    return str;
  }

  function parseAssignment(p) {
    let looping = true;
    while (looping) {
      if (p.look() !== "\0") {
        const name = variableOrFunctionName(p, null);
        if (name === "") { p.error("Expected a variable for assignment but got an empty name."); return; }
        p.skipWhitespace();
        const c = p.look();
        if (c === "=") {
          p.match("=");
          parseExpression(p);
          p.assign(name);
        } else if (c === "(" || c === ";" || c === "\0") {
          parseFunction(p, I.EventFnc, name, false);
        } else {
          p.expected("one of  = ; (  or end of string");
          return;
        }
      }
      const c = p.look();
      if (c === ";") p.match(";");
      else if (c === "\0") looping = false;
      else { p.expected("';' or end of string"); looping = false; }
    }
  }

  function parseExpression(p) {
    parseRelational(p);
    for (;;) {
      const c = p.look();
      if (c === "&") parseAnd(p);
      else if (c === "|") {
        p.match("|", false);
        if (p.look() === "|") parseOr(p);
        else {
          p.push();
          p.skipWhitespace();
          const out = { valid: true };
          const name = variableOrFunctionName(p, out);
          if (name === "") { p.error("Expected a transform function name but got an empty name."); return; }
          if (!out.valid) { p.error("Expected a transform function name but got an invalid name '" + name + "'."); return; }
          parseFunction(p, I.TransformFnc, name, true);
        }
      } else if (c === "?") parseTernary(p);
      else return;
      if (p.parseError) return;
    }
  }

  function parseRelational(p) {
    parseAdditive(p);
    for (;;) {
      const c = p.look();
      if (c === "=") binary(p, "==", I.Equal, parseAdditive);
      else if (c === "!") binary(p, "!=", I.NotEqual, parseAdditive);
      else if (c === "<" || c === ">") {
        p.match(c, false);
        let op = c === "<" ? I.Less : I.Greater;
        if (p.look() === "=") { p.match("="); op = c === "<" ? I.LessEq : I.GreaterEq; } else p.skipWhitespace();
        p.push();
        parseAdditive(p);
        p.pop(REG_L);
        p.emit(op);
      } else return;
      if (p.parseError) return;
    }
  }

  function binary(p, symbol, op, operand) {
    p.match(symbol[0], false);
    p.match(symbol[1]);
    p.push();
    operand(p);
    p.pop(REG_L);
    p.emit(op);
  }

  function parseAdditive(p) {
    parseTerm(p);
    for (;;) {
      const c = p.look();
      if (c !== "+" && c !== "-") return;
      p.match(c);
      p.push();
      parseTerm(p);
      p.pop(REG_L);
      p.emit(c === "+" ? I.Add : I.Subtract);
      if (p.parseError) return;
    }
  }

  function parseTerm(p) {
    parseFactor(p);
    for (;;) {
      const c = p.look();
      if (c !== "*" && c !== "/") return;
      p.match(c);
      p.push();
      parseFactor(p);
      p.pop(REG_L);
      p.emit(c === "*" ? I.Multiply : I.Divide);
      if (p.parseError) return;
    }
  }

  function parseFactor(p) {
    const c = p.look();
    if (c === "(") {
      p.match("(");
      parseExpression(p);
      p.match(")");
    } else if (c === "'") {
      p.match("'", false);
      parseStringLiteral(p);
      p.match("'");
    } else if (c === "!") {
      p.match("!");
      parseFactor(p);
      p.emit(I.Not);
      p.skipWhitespace();
    } else if (c === "-" || (c >= "0" && c <= "9")) {
      const str = findNumberLiteral(p, false);
      if (str !== "") p.emit(I.Literal, atof(str));
      p.skipWhitespace();
    } else if ((c >= "a" && c <= "z") || (c >= "A" && c <= "Z")) {
      parseVariableOrFunction(p);
      p.skipWhitespace();
    } else {
      p.expected("literal, variable name, function name, parenthesis, or '!'");
    }
  }

  function parseStringLiteral(p) {
    let str = "";
    let c = p.look();
    let prev = "\0";
    while (c !== "\0" && (c !== "'" || prev === "\\")) {
      if (prev === "\\" && (c === "\\" || c === "'")) {
        str = str.slice(0, -1);
        prev = "\0";
      } else {
        prev = c;
      }
      str += c;
      c = p.next();
    }
    p.emit(I.Literal, str);
  }

  function variableExpression(p, prefix) {
    if (p.look() === "[") {
      p.next();
      const open = prefix + "[";
      const backup = p.state();
      const index = findNumberLiteral(p, true);
      if (index !== "" && p.look() === "]") {
        p.next();
        return variableExpression(p, open + index + "]");
      }
      p.setState(backup);
      p.emit(I.Literal, open);
      p.push();
      parseExpression(p);
      p.emit(I.CastToInt);
      p.push();
      p.match("]");
      variableExpression(p, "]");
      p.pop(REG_L);
      p.emit(I.Add);
      p.pop(REG_L);
      p.emit(I.Add);
      return "";
    } else if (p.look() === ".") {
      p.next();
      return variableExpression(p, prefix + ".");
    }
    const next = variableOrFunctionName(p, null);
    if (next === "") {
      if (prefix !== "") p.emit(I.Literal, prefix);
      return prefix;
    }
    return variableExpression(p, prefix + next);
  }

  function parseVariableOrFunction(p) {
    const out = { valid: true };
    const name = variableOrFunctionName(p, out);
    if (name === "") { p.error("Expected a variable or function name but got an empty name."); return; }
    if (name === "true") p.emit(I.Literal, true);
    else if (name === "false") p.emit(I.Literal, false);
    else if (p.look() === "(") {
      if (!out.valid) { p.error("Invalid function name '" + name + "'."); return; }
      parseFunction(p, I.TransformFnc, name, false);
    } else if (p.look() === "[") {
      const backup = p.state();
      const full = variableExpression(p, name);
      if (full !== "") {
        p.setState(backup);
        p.variable(full);
      } else {
        p.addVariableAddress(name);
        p.emit(I.DynamicVariable);
      }
    } else p.variable(name);
  }

  function parseOr(p) {
    p.match("|");
    p.push();
    parseRelational(p);
    p.pop(REG_L);
    p.emit(I.Or);
  }

  function parseAnd(p) {
    p.match("&", false);
    p.match("&");
    p.push();
    parseRelational(p);
    p.pop(REG_L);
    p.emit(I.And);
  }

  function parseTernary(p) {
    const jumpFalse = p.program.length;
    p.emit(I.JumpIfZero);
    p.match("?");
    parseExpression(p);
    const jumpEnd = p.program.length;
    p.emit(I.Jump);
    p.match(":");
    const falseBranch = p.program.length;
    parseExpression(p);
    const end = p.program.length;
    p.program[jumpFalse] = [I.JumpIfZero, falseBranch];
    p.program[jumpEnd] = [I.Jump, end];
  }

  function parseFunction(p, op, name, piped) {
    let n = piped ? 1 : 0;
    if (p.look() === "(") {
      let looping = true;
      p.match("(");
      if (p.look() === ")") { p.match(")"); looping = false; }
      while (looping) {
        n += 1;
        parseExpression(p);
        p.push();
        const c = p.look();
        if (c === ")") { p.match(")"); looping = false; }
        else if (c === ",") p.match(",");
        else { p.expected("one of ')' or ','"); looping = false; }
        if (p.parseError) return;
      }
    } else p.skipWhitespace();
    p.fn(op, n, name);
  }

  // Interpreter (Rml::DataInterpreter). Returns { ok, value }.
  function run(program, addresses, iface) {
    let R = NONE, L = NONE;
    const stack = [];
    const anyString = (a, b) => typeof a === "string" || typeof b === "string";
    let i = 0;
    while (i < program.length) {
      const [op, data] = program[i];
      let next = i + 1;
      switch (op) {
        case I.Push: stack.push(R); R = NONE; break;
        case I.Pop:
          if (!stack.length) return fail("Cannot pop stack, it is empty.");
          if (data === REG_R) R = stack.pop(); else L = stack.pop();
          break;
        case I.Literal: R = data; break;
        case I.DynamicVariable: {
          const address = iface.parseAddress(toStr(R));
          if (!address) return fail("Variable address not found.");
          R = iface.getValue(address);
          break;
        }
        case I.Variable:
          if (data >= addresses.length) return fail("Variable address not found.");
          R = iface.getValue(addresses[data]);
          break;
        case I.Add: R = anyString(L, R) ? toStr(L) + toStr(R) : toNum(L) + toNum(R); break;
        case I.Subtract: R = toNum(L) - toNum(R); break;
        case I.Multiply: R = toNum(L) * toNum(R); break;
        case I.Divide: R = toNum(L) / toNum(R); break;
        case I.Not: R = !toBool(R); break;
        case I.And: R = toBool(L) && toBool(R); break;
        case I.Or: R = toBool(L) || toBool(R); break;
        case I.Less: R = toNum(L) < toNum(R); break;
        case I.LessEq: R = toNum(L) <= toNum(R); break;
        case I.Greater: R = toNum(L) > toNum(R); break;
        case I.GreaterEq: R = toNum(L) >= toNum(R); break;
        case I.Equal: R = anyString(L, R) ? toStr(L) === toStr(R) : toNum(L) === toNum(R); break;
        case I.NotEqual: R = anyString(L, R) ? toStr(L) !== toStr(R) : toNum(L) !== toNum(R); break;
        case I.NumArguments: R = data; break;
        case I.TransformFnc:
        case I.EventFnc: {
          const n = typeof R === "number" ? R : -1;
          if (n < 0 || stack.length < n) return fail("Invalid number of arguments.");
          const args = stack.splice(stack.length - n, n);
          if (op === I.TransformFnc) {
            const t = Object.prototype.hasOwnProperty.call(TRANSFORMS, data) ? TRANSFORMS[data] : null;
            if (!t) return fail("Failed to execute transform function: " + data);
            R = t(args);
          } else if (!iface.eventCallback(data, args)) {
            return fail("Failed to execute event callback: " + data);
          }
          break;
        }
        case I.Assign:
          if (data >= addresses.length) return fail("Variable address not found.");
          if (!iface.setValue(addresses[data], R)) return fail("Could not assign to variable.");
          break;
        case I.CastToInt: {
          const n = R === NONE ? null : toInt(R);
          if (n === null) return fail("Could not cast value to int.");
          R = n;
          break;
        }
        case I.JumpIfZero: if (!toBool(R)) next = data; break;
        case I.Jump: next = data; break;
        default: return fail("Instruction not implemented.");
      }
      i = next;
    }
    return { ok: true, value: R };
  }

  function fail(message) {
    warn("Error during execution. " + message);
    return { ok: false, value: NONE };
  }

  // ---------------------------------------------------------------------------------------------------------
  // Models. A model holds the data published by Lua and the views bound to it.

  const models = new Map();       // name -> Model
  let bridge = null;              // { emit(event, payload) } once Open77 is there

  // DataModel.cpp LegalVariableName: what a model may bind (case-insensitive, ASCII)
  const RESERVED = new Set(["it", "it_index", "ev", "true", "false", "size", "literal"]);
  function illegalName(name) {
    const l = asciiLower(name);
    if (l === "") return "Name cannot be empty.";
    if (!/^[a-z]/.test(l)) return "First character must be 'a-z' or 'A-Z'.";
    if (!/^[a-z0-9_]*$/.test(l)) return "Name must strictly contain characters a-z, A-Z, 0-9 and under_score.";
    if (RESERVED.has(l)) return "Name is reserved.";
    return null;
  }

  class Model {
    constructor(name, data, events) {
      this.name = name;
      this.data = data && typeof data === "object" && !Array.isArray(data) ? data : {};
      // bound names are fixed at create, like DataModel; a name RmlUi refuses is not bound at all
      this.variables = new Set();
      for (const k of Object.keys(this.data)) {
        const why = illegalName(k);
        if (why) warn("Could not bind data variable '" + k + "'. " + why);
        else this.variables.add(k);
      }
      this.events = new Set(events || []);   // only declared callbacks run, as natively
      this.views = [];
      this.dirty = new Set();
      this.aliases = new WeakMap();   // element -> Map(name -> address)
      this.attrAliases = new WeakMap();   // element -> Set of the names that came from data-alias-* attributes
      this.root = null;
    }

    // DataModel::ResolveAddress: a bound variable first, then aliases from the element up.
    resolve(str, element) {
      const address = parseAddress(str);
      if (!address) return null;
      if (this.variables.has(address[0])) return address;
      const lower = asciiLower(address[0]);
      for (let el = element; el && modelOf(el) === this; el = el.parentNode) {
        const names = this.aliases.get(el);
        if (!names) continue;
        if (names.has(address[0])) return names.get(address[0]).concat(address.slice(1));
        // An HTML parser lowercases attribute names, so data-alias-firstRow reaches the shim as firstrow; RmlUi (XML)
        // keeps it as written. Resolve the name as written, and say so: in game it must match exactly.
        const fromAttr = this.attrAliases.get(el);
        if (lower !== address[0] && fromAttr && fromAttr.has(lower) && lowercasesAttributes(el.ownerDocument)) {
          warn("'" + address[0] + "' matches data-alias-" + lower + " only ignoring case: the HTML parser lowercased the attribute name, " +
            "NativeUI keeps it as written. Write data-* modifier names in lowercase.");
          return names.get(lower).concat(address.slice(1));
        }
      }
      return null;
    }

    // DataModel::GetVariable + Get: walk the address; a non-scalar end or a miss is the empty value.
    getValue(address) {
      if (address[0] === "literal") return address[1] === "int" ? address[2] : NONE;
      if (!this.variables.has(address[0])) return NONE;
      let cur = this.data[address[0]];
      for (let i = 1; i < address.length; i++) {
        cur = child(cur, address[i]);
        if (cur === NONE) return NONE;
      }
      if (!isScalar(cur)) { warn("Values can only be retrieved from scalar data types."); return NONE; }
      return cur;
    }

    getContainer(address) {
      let cur = this.data[address[0]];
      for (let i = 1; i < address.length && cur !== NONE; i++) cur = child(cur, address[i]);
      return cur;
    }

    // DataModel::GetVariable walks every entry first (a missing member, an index out of bounds or `size` fails), then
    // DataVariable::Set takes scalars only. A refused assignment warns and stops the data-event chain.
    setValue(address, value) {
      if (!this.variables.has(address[0])) return false;
      let parent = this.data, key = address[0];
      for (let i = 1; i < address.length; i++) {
        const cur = parent[key], entry = address[i];
        if (cur === null || typeof cur !== "object") { warn("Tried to get the child of a scalar type."); return false; }
        if (isArrayLike(cur)) {
          if (typeof entry !== "number" || !Array.isArray(cur) || entry < 0 || entry >= cur.length) { warn("Data array index out of bounds."); return false; }
        } else if (typeof entry === "number" || !hasOwn(cur, entry)) {
          warn("Member " + String(entry) + " not found in data struct.");
          return false;
        }
        parent = cur;
        key = entry;
      }
      const cur = parent[key];
      if (cur !== null && typeof cur === "object") { warn("Values can only be assigned to scalar data types."); return false; }
      if (value === NONE) return false;
      setOwn(parent, key, value);
      this.dirty.add(address[0]);
      schedule();
      return true;
    }
  }

  function isArrayLike(v) {
    // Lua's {} reaches JSON as {} or []: an empty object is an empty array, as it is natively
    return Array.isArray(v) || (v !== null && typeof v === "object" && Object.keys(v).length === 0);
  }

  function child(cur, entry) {
    if (cur === null || typeof cur !== "object") { warn("Tried to get the child of a scalar type."); return NONE; }
    if (isArrayLike(cur)) {
      const arr = Array.isArray(cur) ? cur : [];
      if (typeof entry === "number" && entry >= 0 && entry < arr.length) return arr[entry];
      if (entry === "size") return arr.length;
      warn("Data array index out of bounds.");
      return NONE;
    }
    if (typeof entry === "number" || !Object.prototype.hasOwnProperty.call(cur, entry)) {
      warn("Member " + String(entry) + " not found in data struct.");
      return NONE;
    }
    return cur[entry];
  }

  function modelOf(el) {
    for (let e = el; e; e = e.parentNode) {
      if (e.__lrbindModel) return e.__lrbindModel;
    }
    return null;
  }

  // The interface an expression sees (DataExpressionInterface), for one element and maybe one event.
  function makeIface(model, element, event) {
    return {
      parseAddress(str) {
        if (str.length >= 4 && str.startsWith("ev.")) return ["ev", str.slice(3)];
        return model.resolve(str, element);
      },
      getValue(address) {
        if (address[0] === "ev" && address.length === 2) {
          if (event) return hasOwn(event, address[1]) ? event[address[1]] : NONE;
          warn("Could not get value from data variable 'ev." + address[1] + "'.");   // outside an event: a model miss
          return NONE;
        }
        return model.getValue(address);
      },
      setValue(address, value) {
        const ok = model.setValue(address, value);
        if (ok) send("lrbind:change", { model: model.name, path: addressString(address), value });
        return ok;
      },
      eventCallback(name, args) {
        if (!event) return false;
        if (!model.events.has(name)) {
          warn("Could not find data event callback '" + name + "' in data model.");
          return false;
        }
        send("lrbind:event", { model: model.name, name, args, n: args.length });   // n: JSON turns an empty value into a hole
        return true;
      },
    };
  }

  function addressString(address) {
    let s = "";
    for (const e of address) s += typeof e === "number" ? "[" + e + "]" : (s ? "." : "") + e;
    return s;
  }

  function compile(model, element, source, isAssignment) {
    const p = new Parser(source, makeIface(model, element, null));
    if (!p.parse(isAssignment)) return null;
    const deps = new Set();
    for (const a of p.addresses) if (a[0] !== "ev" && a[0] !== "literal") deps.add(a[0]);
    return { program: p.program, addresses: p.addresses, deps };
  }

  function evaluate(view, event) {
    return run(view.expr.program, view.expr.addresses, makeIface(view.model, view.element, event));
  }

  // ---------------------------------------------------------------------------------------------------------
  // Views (DataViewDefault.cpp). Each keeps the last value it wrote, as RmlUi compares before writing.

  const VIEW_ORDER = { alias: 0, for: 1, other: 2 };

  function addView(model, view) {
    view.model = model;
    model.views.push(view);
    return view;
  }

  // A checkbox or radio keeps its state in the checked attribute natively, and every change of that attribute fires
  // "change" (InputTypeCheckbox/InputTypeRadio::OnAttributeChange), which data-checked/data-value controllers and
  // data-event-change see, whoever changed it: a click, a view, the markup. A radio that gets checked first unchecks
  // every other radio with the same name (PopRadioSet: in its form, else in the document outside any form; an empty
  // name is a name too).
  const isToggle = (el) => el.nodeType === 1 && el.tagName.toLowerCase() === "input" && (el.type === "checkbox" || el.type === "radio");

  function setChecked(el, on) {
    if ("checked" in el && el.checked !== on) el.checked = on;
    if (el.hasAttribute("checked") === on) return;
    if (on) el.setAttribute("checked", ""); else el.removeAttribute("checked");
    checkedChanged(el, on);
  }

  function checkedChanged(el, on) {
    if (!isToggle(el)) return;
    if (on && el.type === "radio") popRadioSet(el);
    const win = el.ownerDocument.defaultView || global;
    el.dispatchEvent(new win.Event("change", { bubbles: true }));
  }

  function popRadioSet(el) {
    const form = el.closest("form");
    const name = el.getAttribute("name") || "";
    for (const r of Array.from((form || el.ownerDocument).querySelectorAll("input"))) {
      if (r === el || r.type !== "radio" || (r.getAttribute("name") || "") !== name || (!form && r.closest("form"))) continue;
      setChecked(r, false);
    }
  }

  // A click changed .checked: the attribute follows (RmlUi's default action sets it), before any listener runs.
  function syncToggle(e) {
    const el = e.target;
    if (!isToggle(el) || el.hasAttribute("checked") === el.checked) return;
    if (el.checked) el.setAttribute("checked", ""); else el.removeAttribute("checked");
    if (el.checked && el.type === "radio") popRadioSet(el);
  }

  const VIEWS = {
    attr(el, value, mod) {
      const v = toStr(value);
      const changed = el.getAttribute(mod) !== v;
      if (changed) el.setAttribute(mod, v);
      if (mod === "value" && "value" in el && el.value !== v) el.value = v;
      if (mod === "checked" && changed) { if ("checked" in el) el.checked = true; checkedChanged(el, true); }
    },
    attrif(el, value, mod) {
      const on = toBool(value);
      if (mod === "checked") return setChecked(el, on);
      if (el.hasAttribute(mod) !== on) { if (on) el.setAttribute(mod, ""); else el.removeAttribute(mod); }
      if (mod === "disabled" && "disabled" in el) el.disabled = on;
    },
    class(el, value, mod) { el.classList.toggle(mod, toBool(value)); },
    style(el, value, mod) {
      const v = toStr(value);
      const old = el.style.getPropertyValue(mod);
      if (old === v) return;
      el.style.removeProperty(mod);
      el.style.setProperty(mod, v);
      if (v === "" || el.style.getPropertyValue(mod) !== "") return;
      warn("Syntax error parsing inline property declaration '" + mod + ": " + v + ";'.");   // the old value stays
      if (old !== "") el.style.setProperty(mod, old);
    },
    // DataViewIf/DataViewVisible: "shown" means no inline display/visibility at all, so a true value also
    // removes an inline display the markup set, exactly as RmlUi does
    if(el, value) {
      const on = toBool(value);
      if ((el.style.display === "") !== on) { if (on) el.style.removeProperty("display"); else el.style.setProperty("display", "none"); }
    },
    visible(el, value) {
      const on = toBool(value);
      if ((el.style.visibility === "") !== on) { if (on) el.style.removeProperty("visibility"); else el.style.setProperty("visibility", "hidden"); }
    },
    // DataViewRml: SetInnerRML when the string changed (it starts out as "", so an empty value keeps the markup's
    // content). The views of what it replaces die with it; what it inserts gets bound, as natively.
    rml(el, value, mod, view) {
      const v = toStr(value);
      if (view.last === v) return;
      for (const sub of view.model.views) if (sub !== view && !sub.dead && el.contains(sub.element)) dropView(sub);
      insertInert(el, v);
      view.children = bindChildren(view.model, el);
    },
    // DataViewChecked: a bool is the state; any other value checks only when it equals a non-empty value attribute
    checked(el, value) {
      const s = toStr(value);
      setChecked(el, typeof value === "boolean" ? value : s !== "" && s === (el.getAttribute("value") || ""));
    },
  };

  // data-rml in a browser: natively the string is parsed as RML, where nothing runs. A browser would run some of it, so
  // the shim parses it in a <template> (inert) and drops what acts in a browser and means nothing to RmlUi: script and
  // the other active elements, on* handlers, links and form targets, javascript:/vbscript:/data: values. Each drop is
  // reported; the rest is inserted node by node (never parsed again).
  const ACTIVE_TAGS = new Set(["script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "base",
    "link", "meta", "noscript", "template", "svg", "math", "portal"]);
  const ACTIVE_ATTRS = new Set(["href", "xlink:href", "action", "formaction", "srcdoc", "ping"]);

  function insertInert(el, html) {
    const t = el.ownerDocument.createElement("template");
    t.innerHTML = html;
    const dropped = new Set();
    (function clean(node) {
      for (const c of Array.from(node.childNodes)) {
        if (c.nodeType !== 1) continue;
        const tag = c.tagName.toLowerCase();
        if (ACTIVE_TAGS.has(tag)) { dropped.add("<" + tag + ">"); c.remove(); continue; }
        for (const a of Array.from(c.attributes)) {
          const name = a.name.toLowerCase();
          const value = a.value.replace(/[\u0000-\u0020\u007f-\u009f]+/g, "").toLowerCase();
          if (name.startsWith("on") || ACTIVE_ATTRS.has(name) || /^(javascript|vbscript|data):/.test(value)) {
            dropped.add(name);
            c.removeAttribute(a.name);
          }
        }
        clean(c);
      }
    })(t.content);
    while (el.firstChild) el.removeChild(el.firstChild);
    el.appendChild(t.content);
    if (dropped.size) warn("data-rml: dropped " + Array.from(dropped).join(", ") + " (it would act in a browser; RmlUi keeps it as inert markup)");
  }

  function updateView(view) {
    if (view.dead) return;
    if (view.kind === "for") return updateFor(view);
    if (view.kind === "alias") return;
    if (view.kind === "text") return updateText(view);
    const r = evaluate(view, null);
    if (!r.ok) return;
    VIEWS[view.kind](view.element, r.value, view.mod, view);
    view.last = toStr(r.value);
  }

  function updateText(view) {
    let changed = false;
    for (const entry of view.entries) {
      const r = run(entry.program, entry.addresses, makeIface(view.model, view.element.parentNode, null));
      const v = toStr(r.value);
      if (r.ok && entry.value !== v) { entry.value = v; changed = true; }
    }
    if (!changed) return;
    let out = "", prev = 0;
    for (const entry of view.entries) {
      out += view.text.slice(prev, entry.index) + entry.value;
      prev = entry.index;
    }
    out += view.text.slice(prev);
    view.element.nodeValue = out;
  }

  // DataViewText::Initialize: split "a {{x}} b" into literal text and expressions, with its bracket rules.
  function parseTextView(model, node) {
    const input = node.nodeValue;
    if (input.indexOf("{{") < 0) return null;
    let text = "", begin = 0, cur = 0, prev = "\0";
    let inBrackets = false, inString = false;
    const entries = [];
    for (let k = 0; k < input.length; k++) {
      let c = input[k];
      const wasIn = inBrackets;
      const err = dataBrackets(c, prev, inBrackets, inString);
      if (err.error) {
        warn("Failed to parse data view text '" + input + "'. " + err.error);
        return null;
      }
      inBrackets = err.inBrackets;
      inString = err.inString;
      if (!wasIn && inBrackets) begin = cur;
      else if (wasIn && !inBrackets) {
        const source = input.slice(begin + 1, cur - 1);
        const expr = compile(model, node.parentNode, source, false);
        if (expr) entries.push({ index: text.length, program: expr.program, addresses: expr.addresses, deps: expr.deps, value: "#rmlui#" });
        c = "\0";
      } else if (!inBrackets && prev !== "\0") text += prev;
      cur++;
      prev = c;
    }
    if (!inBrackets && prev !== "\0") text += prev;
    if (!entries.length) return null;
    const deps = new Set();
    for (const e of entries) for (const d of e.deps) deps.add(d);
    return { kind: "text", element: node, text, entries, deps };
  }

  function dataBrackets(c, prev, inBrackets, inString) {
    if (inBrackets) {
      if (c === "'") inString = !inString;
      if (!inString) {
        if (c === "}" && prev === "}") inBrackets = false;
        else if (c === "{" && prev === "{") return { error: "Nested double curly brackets are illegal." };
        else if (prev === "}" && c !== "}" && c !== "'") return { error: "Single closing curly bracket encountered, use double curly brackets to close an expression." };
      }
    } else if (c === "{" && prev === "{") inBrackets = true;
    else if (c === "}" && prev === "}") return { error: "Closing double curly brackets encountered outside an expression." };
    return { inBrackets, inString };
  }

  // BaseXMLParser reads each run of text between tags with the same bracket rules, and a mistake there ends the
  // whole parse: that text and everything after it never reach the native document. Mirror it here so a page
  // shows the same loss (and says why) instead of looking fine in WebUI. A run still inside {{ at its end is the
  // same failure: natively the parser would swallow the following markup as text.
  function xmlTextCheck(doc) {
    const body = doc.body;
    if (!body) return;
    const walker = doc.createTreeWalker(body, 4 /* NodeFilter.SHOW_TEXT */);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      if (t.parentNode && /^(script|style)$/i.test(t.parentNode.tagName)) continue;
      const s = t.nodeValue;
      let state = { inBrackets: false, inString: false }, prev = "\0", error = null;
      for (let k = 0; k < s.length && !error; k++) {
        const r = dataBrackets(s[k], prev, state.inBrackets, state.inString);
        if (r.error) error = r.error; else state = r;
        prev = s[k];
      }
      if (!error && state.inBrackets) error = "Closing double curly brackets not found before the next tag.";
      if (!error) continue;
      warn("XML parse error. " + error + " The native document stops loading at \"" + s.trim().slice(0, 60) +
        "\": this text and everything after it are missing in game, so they are removed here too.");
      truncateFrom(t, body);
      return;
    }
  }

  function truncateFrom(node, stop) {
    let n = node;
    while (n && n !== stop) {
      while (n.nextSibling) n.parentNode.removeChild(n.nextSibling);
      const parent = n.parentNode;
      if (n === node) parent.removeChild(n);
      n = parent;
    }
  }

  function insertAlias(model, el, name, address, fromAttr) {
    if (model.variables.has(name)) warn("Alias variable '" + name + "' is shadowed by a global variable.");
    const names = model.aliases.get(el) || new Map();
    names.set(name, address);
    model.aliases.set(el, names);
    if (fromAttr) model.attrAliases.set(el, (model.attrAliases.get(el) || new Set()).add(name));
  }

  // An HTML document lowercases attribute names; an XML one (a page served as XHTML) keeps them, as RmlUi does
  const htmlDocs = new WeakMap();
  function lowercasesAttributes(doc) {
    if (!htmlDocs.has(doc)) htmlDocs.set(doc, doc.createElement("a").tagName === "A");
    return htmlDocs.get(doc);
  }

  // data-for: the element becomes a hidden anchor; copies of it (without data-for) go in before it, one per entry.
  // StringUtilities::ExpandString: split at the delimiter outside quotes, trim blanks; an empty item counts, except
  // after the last delimiter
  function expandString(str, delimiter) {
    const out = [];
    let quote = "", start = -1, end = 0, lastDelimiter = true;
    for (let i = 0; i < str.length; i++) {
      const c = str[i];
      if (lastDelimiter && !quote && (c === '"' || c === "'")) quote = c;
      else if (c === quote && str[i - 1] !== "\\") quote = "";
      else if (c === delimiter && !quote) {
        out.push(start >= 0 ? str.slice(start, end + 1) : "");
        lastDelimiter = true;
        start = -1;
        continue;
      } else if (!/[\r\n \t]/.test(c) || quote) {
        if (start < 0) start = i;
        end = i;
        lastDelimiter = false;
        continue;
      }
    }
    if (start >= 0) out.push(str.slice(start, end + 1));
    return out;
  }

  // DataViewFor::Initialize: "it : list", "it, i : list" or "list"; any other count of names leaves the defaults
  function makeFor(model, el, source) {
    const halves = expandString(source, ":");
    if (!halves.length || halves.length > 2 || !halves[0] || !halves[halves.length - 1]) {
      warn("Invalid syntax in data-for '" + source + "'");
      return null;
    }
    let iterator = "", indexName = "";
    if (halves.length === 2) {
      const pair = expandString(halves[0], ",");
      if (!pair.length) { warn("Invalid syntax in data-for '" + source + "'"); return null; }
      if (pair.length === 1 || pair.length === 2) iterator = pair[0];
      if (pair.length === 2) indexName = pair[1];
    }
    const address = model.resolve(halves[halves.length - 1], el);
    if (!address) { warn("Could not find variable name '" + halves[halves.length - 1] + "' in data model. Could not add data-for view."); return null; }
    const content = el.ownerDocument.createDocumentFragment();
    while (el.firstChild) content.appendChild(el.firstChild);
    el.removeAttribute("data-for");
    const template = el.cloneNode(false);
    el.style.setProperty("display", "none");
    return {
      kind: "for", element: el, address, iterator: iterator || "it", indexName: indexName || "it_index",
      template, content, clones: [], deps: new Set([address[0]]),
    };
  }

  function updateFor(view) {
    const container = view.model.getContainer(view.address);
    let size = 0;
    if (isArrayLike(container)) size = Array.isArray(container) ? container.length : 0;
    else warn("Tried to get the size from a non-array data type.");
    const model = view.model;
    for (let i = 0; i < Math.max(size, view.clones.length); i++) {
      if (i >= view.clones.length) {
        const el = view.template.cloneNode(false);
        insertAlias(model, el, view.iterator, view.address.concat([i]));
        insertAlias(model, el, view.indexName, ["literal", "int", i]);
        el.appendChild(view.content.cloneNode(true));
        view.element.parentNode.insertBefore(el, view.element);
        view.clones.push({ element: el, views: bindTree(model, el) });
      }
      if (i >= size) {
        const gone = view.clones[i];
        for (const sub of gone.views) dropView(sub);
        gone.element.remove();
        view.clones[i] = null;
      }
    }
    if (view.clones.length > size) view.clones.length = size;
  }

  function dropView(view) {
    view.dead = true;
    if (view.clones) for (const c of view.clones) if (c) for (const sub of c.views) dropView(sub);
    for (const sub of view.children || []) dropView(sub);
  }

  // ---------------------------------------------------------------------------------------------------------
  // Binding a subtree: views and controllers from attributes, text views from text nodes.

  const CONTROLLER_EVENTS = {
    // RmlUi event name -> DOM event name; RmlUi fires "change" on every edit of a text field or slider
    click: "click", dblclick: "dblclick", mousedown: "mousedown", mouseup: "mouseup", mouseover: "mouseover",
    mouseout: "mouseout", mousemove: "mousemove", mousescroll: "wheel", keydown: "keydown", keyup: "keyup",
    focus: "focus", blur: "blur", submit: "submit", change: "change", textinput: "input",
  };

  function changeEventFor(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "textarea" || (tag === "input" && type !== "checkbox" && type !== "radio")) return "input";
    return "change";
  }

  const BUTTON_EVENTS = new Set(["mousedown", "mouseup", "click", "dblclick"]);
  const LOCK_KEYS = [["caps_lock_key", "CapsLock"], ["num_lock_key", "NumLock"], ["scroll_lock_key", "ScrollLock"]];
  const WHEEL_NOTCH = [100, 3, 1];   // DOM deltaMode pixels / lines / pages per wheel notch (Chromium: 100 px)

  // ev.* as RmlUi fills it (Context.cpp, the input widgets): mouse_x/mouse_y on mouse events; button (0 left, 1 right,
  // 2 middle) on mousedown/mouseup/click/dblclick only; the seven modifier keys as ints 0/1; wheel_delta_x/_y in
  // notches; a change's value (a number from a range input) and, from a checkbox or radio, checked.
  function eventParams(e) {
    const p = {};
    if ("clientX" in e) {
      p.mouse_x = e.clientX; p.mouse_y = e.clientY;
      if (BUTTON_EVENTS.has(e.type)) p.button = e.button === 1 ? 2 : e.button === 2 ? 1 : e.button;
    }
    if ("ctrlKey" in e) {
      p.ctrl_key = e.ctrlKey ? 1 : 0; p.shift_key = e.shiftKey ? 1 : 0; p.alt_key = e.altKey ? 1 : 0; p.meta_key = e.metaKey ? 1 : 0;
      for (const [name, key] of LOCK_KEYS) p[name] = typeof e.getModifierState === "function" && e.getModifierState(key) ? 1 : 0;
    }
    if ("deltaY" in e) {
      const notch = WHEEL_NOTCH[e.deltaMode] || 1;
      p.wheel_delta_x = e.deltaX / notch; p.wheel_delta_y = e.deltaY / notch;
    }
    const t = e.target;
    if ((e.type === "change" || e.type === "input") && t && "value" in t) {
      if (isToggle(t)) { p.value = t.checked ? t.value : ""; p.checked = t.checked; }
      else p.value = t.type === "range" ? parseFloat(t.value) : t.value;
    }
    return p;
  }

  function bindElement(model, el, out) {
    const attrs = Array.from(el.attributes);
    const forAttr = el.getAttribute("data-for");
    // data-for is structural: it cancels every other view and controller on its element, aliases included (its
    // copies carry those attributes and bind them, per entry), and its content is bound per copy. RmlUi keeps that
    // content as text, never as elements: when the view fails, the element stays, empty.
    if (forAttr !== null) {
      const view = makeFor(model, el, forAttr);
      if (view) out.push(addView(model, view));
      else while (el.firstChild) el.removeChild(el.firstChild);
      return false;
    }
    // aliases first: they serve the element's own other bindings
    for (const a of attrs) {
      if (!a.name.startsWith("data-alias-")) continue;
      const target = model.resolve(a.value, el);
      if (!target) { warn("Could not add data-alias-" + a.name.slice(11) + ": no data variable '" + a.value + "'"); continue; }
      insertAlias(model, el, a.name.slice(11), target, true);
    }
    for (const a of attrs) {
      const name = a.name;
      if (!name.startsWith("data-") || name === "data-model" || name.startsWith("data-alias-")) continue;
      const dash = name.indexOf("-", 5);
      const kind = dash < 0 ? name.slice(5) : name.slice(5, dash);
      const mod = dash < 0 ? "" : name.slice(dash + 1);
      if (kind === "event") {
        bindEvent(model, el, mod, a.value);
      } else if (kind === "value" || kind === "checked") {
        bindTwoWay(model, el, kind, a.value, out);
      } else if (kind in VIEWS && kind !== "checked") {
        if ((kind === "attr" || kind === "attrif" || kind === "class" || kind === "style") && !mod) continue;
        const expr = compile(model, el, a.value, false);
        if (expr) out.push(addView(model, { kind, element: el, mod, expr, deps: expr.deps, last: kind === "rml" ? "" : NONE }));
      }
    }
    return true;
  }

  function bindEvent(model, el, type, source) {
    const domType = CONTROLLER_EVENTS[type];
    if (!domType) { warn("Event type '" + type + "' is not mapped for WebUI (data-event-" + type + ")"); return; }
    const expr = compile(model, el, source, true);
    if (!expr) return;
    const real = type === "change" ? changeEventFor(el) : domType;
    el.addEventListener(real, (e) => {
      run(expr.program, expr.addresses, makeIface(model, el, eventParams(e)));
    });
  }

  function bindTwoWay(model, el, kind, source, out) {
    const address = model.resolve(source, el);
    if (!address) { warn("Could not find data variable with name '" + source + "'."); return; }
    const expr = { program: [[I.Variable, 0]], addresses: [address], deps: new Set([address[0]]) };
    out.push(addView(model, { kind: kind === "value" ? "attr" : "checked", element: el, mod: "value", expr, deps: expr.deps }));
    // DataControllerValue (data-value and data-checked alike): the element's own change event writes the variable
    el.addEventListener(changeEventFor(el), () => {
      const value = controllerValue(el);
      if (value === NONE) return;
      if (model.setValue(address, value)) send("lrbind:change", { model: model.name, path: addressString(address), value });
    });
  }

  // What the change event hands the controller (data-binding-override-value, else value): a checkbox its checked state,
  // a radio its value when it got checked (nothing when it got unchecked), a range input a number, any other its text.
  function controllerValue(el) {
    if (el.type === "checkbox") return el.checked;
    if (el.type === "radio") return el.checked ? el.value : NONE;
    return el.type === "range" ? parseFloat(el.value) : el.value;   // a slider hands over a float
  }

  function bindTree(model, root) {
    const out = [];
    walk(model, root, out);
    for (const v of out) updateView(v);
    return out;
  }

  function bindChildren(model, el) {
    const out = [];
    for (const c of Array.from(el.childNodes)) walk(model, c, out);
    for (const v of out) updateView(v);
    return out;
  }

  function walk(model, node, out) {
    if (node.nodeType === 3) {
      const view = parseTextView(model, node);
      if (view) out.push(addView(model, view));
      return;
    }
    if (node.nodeType !== 1) return;
    const tag = node.tagName.toLowerCase();
    if (tag === "script" || tag === "style" || tag === "template") return;
    if (!bindElement(model, node, out)) return;
    for (const c of Array.from(node.childNodes)) walk(model, c, out);
  }

  // ---------------------------------------------------------------------------------------------------------
  // Updates are batched to the end of the current task, like RmlUi's once-per-frame model update.

  let scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    Promise.resolve().then(flush);
  }

  function flush() {
    scheduled = false;
    for (const model of models.values()) {
      if (!model.dirty.size) continue;
      const dirty = model.dirty;
      model.dirty = new Set();
      model.views = model.views.filter((v) => !v.dead);
      const list = model.views.filter((v) => { for (const d of v.deps) if (dirty.has(d)) return true; return false; });
      list.sort((a, b) => (VIEW_ORDER[a.kind] ?? 2) - (VIEW_ORDER[b.kind] ?? 2));
      for (const v of list) updateView(v);
    }
  }

  // Lua paths come in already 0-based (lrbind.lua shifts them).
  // A path walks own members only (it cannot reach Object.prototype), and an index may append at the end of a list,
  // not leave a hole.
  function setPath(model, path, value) {
    const address = typeof path === "string" ? parseAddress(path) : null;
    if (!address || !model.variables.has(address[0])) { warn("set: no data variable '" + path + "' in model " + model.name); return; }
    let parent = model.data, key = address[0];
    for (let i = 1; i < address.length; i++) {
      let next = parent[key];
      const entry = address[i], last = i === address.length - 1;
      if (next === null || typeof next !== "object") { warn("set: '" + path + "' runs through a scalar"); return; }
      if (typeof entry === "number") {
        if (!Array.isArray(next)) {
          if (Object.keys(next).length) { warn("set: '" + path + "' indexes a struct"); return; }
          next = [];   // Lua's {} is an empty list
          setOwn(parent, key, next);
        }
        if (entry > next.length || (entry === next.length && !last)) { warn("set: '" + path + "' is past the end of its list"); return; }
      } else if (last ? Array.isArray(next) : !hasOwn(next, entry)) {
        warn("set: no member '" + entry + "' on the way to '" + path + "'");
        return;
      }
      parent = next;
      key = entry;
    }
    setOwn(parent, key, value);
    model.dirty.add(address[0]);
    schedule();
  }

  function arrayAt(model, path) {
    const address = typeof path === "string" ? parseAddress(path) : null;
    if (!address || !model.variables.has(address[0])) return null;
    let cur = model.data[address[0]];
    for (let i = 1; i < address.length && cur !== NONE; i++) cur = child(cur, address[i]);
    if (!isArrayLike(cur)) return null;
    if (!Array.isArray(cur)) {   // {} -> [] in place
      setPath(model, path, []);
      return arrayAt(model, path);
    }
    model.dirty.add(address[0]);
    schedule();
    return cur;
  }

  // ---------------------------------------------------------------------------------------------------------
  // Public face.

  const checkedDocs = new WeakSet();

  function bindDocument(doc) {
    if (!checkedDocs.has(doc)) { checkedDocs.add(doc); xmlTextCheck(doc); }
    for (const model of models.values()) {
      if (model.root) continue;
      const root = doc.querySelector('[data-model="' + model.name + '"]');
      if (!root) { warn("no element with data-model=\"" + model.name + "\""); continue; }
      model.root = root;
      root.__lrbindModel = model;
      root.addEventListener("change", syncToggle, true);
      bindTree(model, root);
    }
    doc.documentElement.classList.remove("lrbind-pending");
  }

  const LrBind = {
    // Define the models (Lua's create { models, events }) and bind the document. Calling it again with a
    // model already bound refreshes its data instead (a page reload re-sends the whole state).
    init(spec, doc) {
      doc = doc || global.document;
      const events = (spec && spec.events) || {};
      for (const [name, data] of Object.entries((spec && spec.models) || {})) {
        const old = models.get(name);
        if (old && old.root) {
          for (const [k, v] of Object.entries(data || {})) if (old.variables.has(k)) { setOwn(old.data, k, v); old.dirty.add(k); }
          schedule();
          continue;
        }
        models.set(name, new Model(name, data, events[name]));
      }
      bindDocument(doc);
    },
    set(name, path, value) { const m = models.get(name); if (m) setPath(m, path, value); else warn("set: no model " + name); },
    // merge takes top-level fields of the model (set takes a path)
    merge(name, fields) {
      const m = models.get(name);
      if (!m) return warn("merge: no model " + name);
      if (!fields || typeof fields !== "object") return warn("merge: no fields for model " + name);
      for (const k of Object.keys(fields)) {
        if (!m.variables.has(k)) { warn("merge: no data variable '" + k + "' in model " + name + " (merge takes top-level fields)"); continue; }
        setOwn(m.data, k, fields[k]);
        m.dirty.add(k);
      }
      schedule();
    },
    push(name, path, value) { const m = models.get(name); const a = m && arrayAt(m, path); if (a) a.push(value); else warn("push: '" + path + "' is not an array"); },
    removeAt(name, path, index) {
      const m = models.get(name);
      const a = m && arrayAt(m, path);
      if (a && Number.isInteger(index) && index >= 0 && index < a.length) a.splice(index, 1);
      else warn("removeAt: no entry " + index + " in '" + path + "'");
    },
    get(name) { const m = models.get(name); return m ? m.data : NONE; },
    flush,
    onError(fn) { errorSink = fn; },
    reset() { models.clear(); },   // for tests
    // exposed for the parity harness
    _expr: { Parser, run, toStr, toNum, toBool, fixed, parseAddress },
  };

  function send(event, payload) {
    if (bridge) bridge.emit(event, payload);
  }

  global.LrBind = LrBind;

  // Wire to the Open77 bridge when the page runs in the game; a plain browser (a mockup) calls LrBind.init itself.
  const open77 = global.Open77;
  if (open77 && typeof open77.on === "function") {
    bridge = open77;
    errorSink = (message) => open77.emit("lrbind:error", { message: String(message).slice(0, 400) });
    const doc = global.document;
    if (doc && doc.documentElement) {
      // nothing bound shows raw {{x}} until the first lrbind:init
      doc.documentElement.classList.add("lrbind-pending");
      const style = doc.createElement("style");
      style.textContent = ".lrbind-pending [data-model] { visibility: hidden; }";
      (doc.head || doc.documentElement).appendChild(style);
    }
    open77.on("lrbind:init", (spec) => LrBind.init(spec));
    open77.on("lrbind:set", (m) => LrBind.set(m.model, m.path, m.value));
    open77.on("lrbind:merge", (m) => LrBind.merge(m.model, m.fields));
    open77.on("lrbind:push", (m) => LrBind.push(m.model, m.path, m.value));
    open77.on("lrbind:removeAt", (m) => LrBind.removeAt(m.model, m.path, m.index));
    open77.emit("lrbind:ready", {});
  }
})(typeof window !== "undefined" ? window : globalThis);
