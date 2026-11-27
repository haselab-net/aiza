// The page's scripts share one global scope (the deployment notes): which
// file uses which other file's top-level names, and how. Reads
// [[file, text], ...] in the page's load order (JSON on stdin) and prints
// {"declared": {file: [names]}, "uses": [{file, name, owner, write, load, line}]}
// -- every use of a name another file declares at its top level: `write`
// when it is assigned, `load` when it runs while the file loads (outside
// any function). For tests/test_page_scopes.py.
"use strict";
const path = require("path");
const acorn = require(path.join(__dirname, "vendor", "acorn.js"));

const files = JSON.parse(require("fs").readFileSync(0, "utf8"));

function patternNames(p, out) {
  if (!p) return out;
  if (p.type === "Identifier") out.push(p.name);
  else if (p.type === "ObjectPattern") for (const q of p.properties) patternNames(q.type === "RestElement" ? q.argument : q.value, out);
  else if (p.type === "ArrayPattern") for (const q of p.elements) patternNames(q, out);
  else if (p.type === "RestElement") patternNames(p.argument, out);
  else if (p.type === "AssignmentPattern") patternNames(p.left, out);
  return out;
}

// The names a block (or the program) declares itself: let/const/class/function.
function blockNames(body) {
  const out = [];
  for (const s of body) {
    const d = s.type === "ExportNamedDeclaration" ? s.declaration : s;
    if (!d) continue;
    if (d.type === "VariableDeclaration" && d.kind !== "var") for (const x of d.declarations) patternNames(x.id, out);
    else if ((d.type === "FunctionDeclaration" || d.type === "ClassDeclaration") && d.id) out.push(d.id.name);
  }
  return out;
}

// The var names a function (or the program) hoists, not looking into inner functions.
function varNames(node, out = []) {
  if (!node || typeof node.type !== "string") return out;
  if (node.type === "VariableDeclaration" && node.kind === "var") for (const x of node.declarations) patternNames(x.id, out);
  for (const k of Object.keys(node)) {
    if (k === "type" || k === "loc") continue;
    const v = node[k];
    const kids = Array.isArray(v) ? v : [v];
    for (const c of kids) {
      if (!c || typeof c.type !== "string") continue;
      if (/Function/.test(c.type)) continue;
      varNames(c, out);
    }
  }
  return out;
}

const asts = files.map(([name, text]) => [name, acorn.parse(text, { ecmaVersion: "latest", sourceType: "script", locations: true })]);
const declared = {};
for (const [name, ast] of asts) declared[name] = [...new Set([...blockNames(ast.body), ...varNames(ast)])];
const owner = new Map();
for (const [name] of asts) for (const n of declared[name]) if (!owner.has(n)) owner.set(n, name);

const uses = [];
for (const [file, ast] of asts) {
  const scopes = [];   // the local scopes inside the file (its top level is the global one)
  let fnDepth = 0;
  const local = (n) => scopes.some((s) => s.has(n));
  const ref = (id, write) => {
    const n = id.name;
    if (local(n) || !owner.has(n) || owner.get(n) === file) return;
    uses.push({ file, name: n, owner: owner.get(n), write, load: fnDepth === 0, line: id.loc.start.line });
  };
  const writeTarget = (p) => {
    if (!p) return;
    if (p.type === "Identifier") ref(p, true);
    else if (p.type === "MemberExpression") visit(p);
    else if (p.type === "ObjectPattern") for (const q of p.properties) writeTarget(q.type === "RestElement" ? q.argument : q.value);
    else if (p.type === "ArrayPattern") for (const q of p.elements) writeTarget(q);
    else if (p.type === "RestElement") writeTarget(p.argument);
    else if (p.type === "AssignmentPattern") { writeTarget(p.left); visit(p.right); }
  };
  const fn = (node) => {
    const s = new Set();
    if (node.id && node.type !== "FunctionDeclaration") s.add(node.id.name);
    for (const p of node.params) patternNames(p, []).forEach((x) => s.add(x));
    if (node.type !== "ArrowFunctionExpression") s.add("arguments");
    if (node.body.type === "BlockStatement") {
      varNames(node.body).forEach((x) => s.add(x));
    }
    scopes.push(s);
    fnDepth++;
    for (const p of node.params) { if (p.type === "AssignmentPattern") visit(p.right); }
    if (node.body.type === "BlockStatement") block(node.body.body); else visit(node.body);
    fnDepth--;
    scopes.pop();
  };
  const block = (body) => {
    scopes.push(new Set(blockNames(body)));
    for (const s of body) visit(s);
    scopes.pop();
  };
  function visit(node) {
    if (!node || typeof node.type !== "string") return;
    switch (node.type) {
      case "Identifier": ref(node, false); return;
      case "FunctionDeclaration": case "FunctionExpression": case "ArrowFunctionExpression": fn(node); return;
      case "BlockStatement": block(node.body); return;
      case "StaticBlock": block(node.body); return;
      case "ClassDeclaration": case "ClassExpression":
        if (node.superClass) visit(node.superClass);
        for (const m of node.body.body) {
          if (m.computed) visit(m.key);
          if (m.value) { if (m.type === "PropertyDefinition") { fnDepth++; visit(m.value); fnDepth--; } else visit(m.value); }
          if (m.type === "StaticBlock") visit(m);
        }
        return;
      case "VariableDeclaration":
        for (const d of node.declarations) { if (d.id.type !== "Identifier") writeTarget(d.id); visit(d.init); }
        return;
      case "AssignmentExpression": writeTarget(node.left); visit(node.right); return;
      case "UpdateExpression": writeTarget(node.argument); return;
      case "MemberExpression": visit(node.object); if (node.computed) visit(node.property); return;
      case "Property": if (node.computed) visit(node.key); visit(node.value); return;
      case "MethodDefinition": case "PropertyDefinition": if (node.computed) visit(node.key); visit(node.value); return;
      case "LabeledStatement": visit(node.body); return;
      case "BreakStatement": case "ContinueStatement": case "MetaProperty": return;
      case "CatchClause": {
        const s = new Set(patternNames(node.param, []));
        scopes.push(s); visit(node.body); scopes.pop(); return;
      }
      case "ForStatement": case "ForInStatement": case "ForOfStatement": {
        const d = node.init || node.left;
        const s = new Set(d && d.type === "VariableDeclaration" && d.kind !== "var" ? d.declarations.flatMap((x) => patternNames(x.id, [])) : []);
        scopes.push(s);
        if (node.type === "ForStatement") { visit(node.init); visit(node.test); visit(node.update); }
        else { if (node.left.type === "VariableDeclaration") visit(node.left); else writeTarget(node.left); visit(node.right); }
        visit(node.body);
        scopes.pop();
        return;
      }
      case "SwitchStatement": {
        visit(node.discriminant);
        scopes.push(new Set(blockNames(node.cases.flatMap((c) => c.consequent))));
        for (const c of node.cases) { visit(c.test); for (const s of c.consequent) visit(s); }
        scopes.pop();
        return;
      }
    }
    for (const k of Object.keys(node)) {
      if (k === "type" || k === "loc" || k === "start" || k === "end") continue;
      const v = node[k];
      if (Array.isArray(v)) v.forEach(visit); else if (v && typeof v.type === "string") visit(v);
    }
  }
  for (const s of ast.body) visit(s);
}
process.stdout.write(JSON.stringify({ declared, uses }));
