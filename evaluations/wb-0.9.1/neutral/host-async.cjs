// Host oracle for cross-page-async. Transpiles and executes the ACTUAL target
// SharedSave.ets. Host injects setTimeout/clearTimeout/Promise (ArkUI provides
// taskpool + preferences). Runs normal, cancellation, exception, and two mutants.
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

function prefsStub(throwOnSet) {
  return { _v: undefined,
    set(v) { if (throwOnSet) throw new Error('persist failed'); this._v = v; },
    get() { return this._v; } };
}
const cases = [];

async function run() {
  // Normal: add then save (no cancel) -> Saved and persisted.
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
  // Cancellation: save then cancel before the 200ms write -> Cancelled, nothing persisted.
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
  // Exception: persistence fault -> message Failed, never Saved.
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
  // Mutant: cancel() disabled -> cancellation must NOT protect persistence; baseline rejects.
  {
    const mutated = orig.replace(/token\.cancelled = true;[\s\S]*?\n  \}/, '/* cancel disabled */\n  }');
    const ex = load(mutated);
    const m = new ex.SharedSave();
    const prefs = prefsStub(false);
    m.add();
    const token = { cancelled: false, onCancel: null };
    const p = m.save(prefs, token);
    m.cancel(token);
    let caught = false;
    try { await p; } catch (e) { caught = true; }
    const writePrevented = prefs.get() === undefined;
    cases.push({ id: 'CA-AC04', kind: 'mutation', mutation: 'cancel() no-op',
      expected: { savedCount: undefined, message: 'Cancelled' },
      actual: { savedCount: prefs.get(), message: m.message },
      discriminated: !writePrevented, pass: !writePrevented });
  }
  // Missing-evidence: persistence dropped -> savedCount never written; baseline rejects.
  {
    const mutated = orig.replace('prefs.set(captured);', '/* persistence dropped */');
    const ex = load(mutated);
    const m = new ex.SharedSave();
    const prefs = prefsStub(false);
    m.add();
    const token = { cancelled: false, onCancel: null };
    await m.save(prefs, token);
    const persisted = prefs.get() === 1;
    cases.push({ id: 'CA-AC05', kind: 'missing-evidence', mutation: 'remove prefs.set',
      expected: { savedCount: 1 }, actual: { savedCount: prefs.get(), message: m.message },
      detected: !persisted, pass: !persisted });
  }
  console.log(JSON.stringify({ sample: 'cross-page-async', source: 'SharedSave.swift', target: targetPath, cases }, null, 2));
}
run();
