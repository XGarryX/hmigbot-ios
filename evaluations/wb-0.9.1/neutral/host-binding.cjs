// Host oracle for binding-navigation. Transpiles and executes the ACTUAL target
// EnabledStore.ets (no ArkUI renderer, like host-behavior.cjs). Runs a normal
// case plus mutants that break the two-way binding; the independent baseline must
// discriminate each mutant (pass=true means the bad behavior was correctly rejected).
const fs = require('fs');
const vm = require('vm');
const ts = require(process.argv[2]);
const targetPath = process.argv[3];

function load(src) {
  const compiled = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 }
  }).outputText;
  const ex = {};
  vm.runInNewContext(compiled, { exports: ex, console }, { filename: targetPath });
  return ex;
}
const orig = fs.readFileSync(targetPath, 'utf8');
const cases = [];

// Normal: single shared backing store (two-way binding source).
{
  const ex = load(orig);
  const s = new ex.EnabledStore();
  const initial = s.enabled;
  s.toggle(); const afterFirst = s.enabled;
  s.toggle(); const afterSecond = s.enabled;
  const pass = initial === false && afterFirst === true && afterSecond === false;
  cases.push({ id: 'BN-AC01', kind: 'normal',
    expected: { initial: false, afterFirstToggle: true, afterSecondToggle: false },
    actual: { initial, afterFirstToggle: afterFirst, afterSecondToggle: afterSecond }, pass });
}
// Mutant: disable() becomes a no-op -> Disable button no longer resets (broken write-back).
{
  const mutated = orig.replace('this.enabled = false;', '/* dropped */');
  const ex = load(mutated);
  const s = new ex.EnabledStore();
  s.toggle(); s.disable();
  const actual = s.enabled;
  cases.push({ id: 'BN-AC02', kind: 'mutation', mutation: 'disable() no-op',
    expected: false, actual, discriminated: actual !== false, pass: actual !== false });
}
// Mutant: toggle() always sets true -> second toggle must NOT stay true.
{
  const mutated = orig.replace('this.enabled = !this.enabled;', 'this.enabled = true;');
  const ex = load(mutated);
  const s = new ex.EnabledStore();
  s.toggle(); s.toggle();
  const actual = s.enabled;
  cases.push({ id: 'BN-AC03', kind: 'mutation', mutation: 'toggle always true',
    expected: false, actual, discriminated: actual !== false, pass: actual !== false });
}
console.log(JSON.stringify({ sample: 'binding-navigation', source: 'BindingNavigation.swift', target: targetPath, cases }, null, 2));
