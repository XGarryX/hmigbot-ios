// Host oracle for uikit-ib. Transpiles and executes the ACTUAL target
// CounterController.ets. Business paths run on the real candidate; guard paths
// prove the mutation actually applied before counting a discrimination.
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

function mutate(pattern, replacement) {
  const out = orig.replace(pattern, replacement);
  return { out, applied: out !== orig };
}
const cases = [];

// UI-AC01 (business): viewDidLoad init + two taps increment and refresh the
// label. Covers the IBAction event wiring (touchUpInside -> add) and the
// countLabel outlet resource. Executed on the REAL candidate.
{
  const ex = load(orig);
  const c = new ex.CounterController();
  c.viewDidLoad();
  const initCount = c.count, initLabel = c.countLabel;
  c.add(); const a1 = { count: c.count, label: c.countLabel };
  c.add(); const a2 = { count: c.count, label: c.countLabel };
  const pass = initCount === 0 && initLabel === 'Count: 0' &&
    a1.count === 1 && a1.label === 'Count: 1' &&
    a2.count === 2 && a2.label === 'Count: 2';
  cases.push({ id: 'UI-AC01', kind: 'normal',
    expected: { init: [0, 'Count: 0'], tap1: [1, 'Count: 1'], tap2: [2, 'Count: 2'] },
    actual: { init: [initCount, initLabel], tap1: [a1.count, a1.label], tap2: [a2.count, a2.label] }, pass });
}
// UI-AC02 (guard): increment +1 becomes +2 -> count must diverge from source.
{
  const { out, applied } = mutate('this.count += 1;', 'this.count += 2;');
  const ex = load(out);
  const c = new ex.CounterController();
  c.viewDidLoad(); c.add(); c.add();
  const actual = { count: c.count, label: c.countLabel };
  const expected = { count: 2, label: 'Count: 2' };
  const divergence = actual.count !== expected.count || actual.label !== expected.label;
  cases.push({ id: 'UI-AC02', kind: 'mutation', mutation: 'increment +2', applied,
    expected, actual, discriminated: divergence, pass: applied && divergence });
}
// UI-AC03 (guard / missing-evidence): countLabel update dropped -> label
// silently lost. Detection must be real and the mutation must have applied.
{
  const { out, applied } = mutate(/this\.countLabel = "Count: " \+ this\.count;/, '/* label update dropped */');
  const ex = load(out);
  const c = new ex.CounterController();
  c.viewDidLoad(); c.add();
  const actual = { count: c.count, label: c.countLabel };
  const labelReflects = actual.label === ('Count: ' + actual.count);
  const detected = !labelReflects;
  cases.push({ id: 'UI-AC03', kind: 'missing-evidence', mutation: 'drop countLabel update', applied,
    expected: { count: 1, label: 'Count: 1' }, actual,
    detected, pass: applied && detected });
}
console.log(JSON.stringify({ sample: 'uikit-ib', source: 'CounterController.{h,m,xib}', target: targetPath, cases }, null, 2));
