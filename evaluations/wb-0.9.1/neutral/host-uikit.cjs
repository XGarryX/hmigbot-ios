// Host oracle for uikit-ib. Transpiles and executes the ACTUAL target
// CounterController.ets. Runs normal + mutation (+2) + missing-evidence (label dropped).
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

// Normal: viewDidLoad initializes, two taps increment and refresh the label.
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
// Mutant: increment +1 becomes +2 -> counts must diverge from source oracle.
{
  const mutated = orig.replace('this.count += 1;', 'this.count += 2;');
  const ex = load(mutated);
  const c = new ex.CounterController();
  c.viewDidLoad(); c.add(); c.add();
  const actual = { count: c.count, label: c.countLabel };
  const expected = { count: 2, label: 'Count: 2' };
  const divergence = actual.count !== expected.count || actual.label !== expected.label;
  cases.push({ id: 'UI-AC02', kind: 'mutation', mutation: 'increment +2',
    expected, actual, discriminated: divergence, pass: divergence });
}
// Missing-evidence: outlet/label update dropped -> count increments but label silently lost.
{
  const mutated = orig.replace(/this\.countLabel = "Count: " \+ this\.count;/, '/* label update dropped */');
  const ex = load(mutated);
  const c = new ex.CounterController();
  c.viewDidLoad(); c.add();
  const actual = { count: c.count, label: c.countLabel };
  const labelReflects = actual.label === ('Count: ' + actual.count);
  cases.push({ id: 'UI-AC03', kind: 'missing-evidence', mutation: 'drop countLabel update',
    expected: { count: 1, label: 'Count: 1' }, actual,
    detected: !labelReflects, pass: !labelReflects });
}
console.log(JSON.stringify({ sample: 'uikit-ib', source: 'CounterController.{h,m,xib}', target: targetPath, cases }, null, 2));
