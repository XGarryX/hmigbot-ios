// Host oracle for cross-page-async. Transpiles and executes the ACTUAL target
// SharedSave.ets. Host injects setTimeout/clearTimeout/Promise (ArkUI provides
// taskpool + preferences). Business paths run on the real candidate; guard paths
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
  vm.runInNewContext(compiled, { exports: ex, setTimeout, clearTimeout, Promise, console }, { filename: targetPath });
  return ex;
}
const orig = fs.readFileSync(targetPath, 'utf8');

function mutate(pattern, replacement) {
  const out = orig.replace(pattern, replacement);
  return { out, applied: out !== orig };
}
const cases = [];

async function run() {
  // CA-AC01 (business): add then save (no cancel) -> Saved and persisted.
  {
    const ex = load(orig);
    const m = new ex.SharedSave();
    const prefs = prefsStub(false);
    m.add();
    const token = { cancelled: false, onCancel: null };
    await m.save(prefs, token);
    const pass = m.message === 'Saved' && prefs.get() === 1;
    cases.push({ id: 'CA-AC01', kind: 'normal',
      expected: { message: 'Saved', savedCount: 1 },
      actual: { message: m.message, savedCount: prefs.get() }, pass });
  }
  // CA-AC02 (business): save then cancel before the 200ms write -> Cancelled.
  {
    const ex = load(orig);
    const m = new ex.SharedSave();
    const prefs = prefsStub(false);
    m.add();
    const token = { cancelled: false, onCancel: null };
    const p = m.save(prefs, token);
    m.cancel(token);
    let caught = false;
    try { await p; } catch (e) { caught = true; }
    const pass = caught && m.message === 'Cancelled' && prefs.get() === undefined;
    cases.push({ id: 'CA-AC02', kind: 'normal-cancel',
      expected: { message: 'Cancelled', savedCount: undefined },
      actual: { message: m.message, savedCount: prefs.get() }, pass });
  }
  // CA-AC03 (business / exception): persistence fault -> message Failed.
  {
    const ex = load(orig);
    const m = new ex.SharedSave();
    const prefs = prefsStub(true);
    m.add();
    const token = { cancelled: false, onCancel: null };
    let caught = false;
    try { await m.save(prefs, token); } catch (e) { caught = true; }
    const pass = m.message === 'Failed' && caught;
    cases.push({ id: 'CA-AC03', kind: 'exception',
      expected: { message: 'Failed' }, actual: { message: m.message }, pass });
  }
  // CA-AC04 (guard): cancel() disabled -> cancellation must NOT protect
  // persistence. Mutation must have applied to count as a real discrimination.
  {
    const { out, applied } = mutate(/token\.cancelled = true;[\s\S]*?\n  \}/, '/* cancel disabled */\n  }');
    const ex = load(out);
    const m = new ex.SharedSave();
    const prefs = prefsStub(false);
    m.add();
    const token = { cancelled: false, onCancel: null };
    const p = m.save(prefs, token);
    m.cancel(token);
    let caught = false;
    try { await p; } catch (e) { caught = true; }
    const writePrevented = prefs.get() === undefined;
    cases.push({ id: 'CA-AC04', kind: 'mutation', mutation: 'cancel() no-op', applied,
      expected: { savedCount: undefined, message: 'Cancelled' },
      actual: { savedCount: prefs.get(), message: m.message },
      discriminated: !writePrevented, pass: applied && !writePrevented });
  }
  // CA-AC05 (guard / missing-evidence): persistence dropped -> savedCount never
  // written. Detection must be real and the mutation must have applied.
  {
    const { out, applied } = mutate('prefs.set(captured);', '/* persistence dropped */');
    const ex = load(out);
    const m = new ex.SharedSave();
    const prefs = prefsStub(false);
    m.add();
    const token = { cancelled: false, onCancel: null };
    await m.save(prefs, token);
    const persisted = prefs.get() === 1;
    cases.push({ id: 'CA-AC05', kind: 'missing-evidence', mutation: 'remove prefs.set', applied,
      expected: { savedCount: 1 }, actual: { savedCount: prefs.get(), message: m.message },
      detected: !persisted, pass: applied && !persisted });
  }
  console.log(JSON.stringify({ sample: 'cross-page-async', source: 'SharedSave.swift', target: targetPath, cases }, null, 2));
}
function prefsStub(throwOnSet) {
  return { _v: undefined,
    set(v) { if (throwOnSet) throw new Error('persist failed'); this._v = v; },
    get() { return this._v; } };
}
run();
