// Host oracle for binding-navigation. Transpiles and executes the ACTUAL target
// EnabledStore.ets (no ArkUI renderer, like host-behavior.cjs).
//
// Two kinds of checks, kept in separate denominators:
//  * normal   -> business paths executed against the REAL candidate target.
//    These are the acceptance criteria derived from BindingNavigation.swift and
//    they must FAIL when the candidate is wrong (e.g. disable() is a no-op).
//  * mutation  -> guard checks that prove the oracle can discriminate a real
//    defect. Each mutant first proves it actually changed the source; a guard
//    whose mutation did not apply is itself a FAIL, never a silent GUARD-OK.
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

// Apply a mutation and report whether it actually changed the source. A guard
// that cannot change the source (e.g. the candidate is already broken there)
// cannot claim to have discriminated anything.
function mutate(pattern, replacement) {
  const out = orig.replace(pattern, replacement);
  return { out, applied: out !== orig };
}
const cases = [];

// BN-AC01 (business): single shared backing store alternation on the real target.
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
// BN-AC02 (business): Detail 'Disable' must write false back to the shared
// binding (cross-navigation write-back). Executed on the REAL candidate; a
// no-op disable() is a business defect and must FAIL here.
{
  const ex = load(orig);
  const s = new ex.EnabledStore();
  s.toggle();            // shared state becomes true
  s.disable();           // Detail Disable button writes false back
  const actual = s.enabled;
  cases.push({ id: 'BN-AC02', kind: 'normal',
    expectation: 'Detail Disable writes false to the shared binding (cross-navigation write-back).',
    expected: false, actual, pass: actual === false });
}
// BN-AC03 (guard): oracle must discriminate a toggle-constant mutant.
{
  const { out, applied } = mutate('this.enabled = !this.enabled;', 'this.enabled = true;');
  const ex = load(out);
  const s = new ex.EnabledStore();
  s.toggle(); s.toggle();
  const actual = s.enabled;
  const discriminated = actual !== false;
  cases.push({ id: 'BN-AC03', kind: 'mutation', mutation: 'toggle always true', applied,
    expected: false, actual, discriminated, pass: applied && discriminated });
}
// BN-AC04 (guard): oracle must discriminate a disable-no-op mutant, and must
// prove the mutation actually changed the disable body. If the candidate is
// already a no-op disable, the mutation cannot apply and this guard FAILS
// (instead of a false GUARD-OK), which is exactly the bug THEF-16 fixes.
{
  const { out, applied } = mutate('this.enabled = false;', '/* dropped */');
  const ex = load(out);
  const s = new ex.EnabledStore();
  s.toggle(); s.disable();
  const actual = s.enabled;
  const discriminated = actual !== false;
  cases.push({ id: 'BN-AC04', kind: 'mutation', mutation: 'disable() no-op', applied,
    expected: false, actual, discriminated, pass: applied && discriminated });
}
console.log(JSON.stringify({ sample: 'binding-navigation', source: 'BindingNavigation.swift', target: targetPath, cases }, null, 2));
