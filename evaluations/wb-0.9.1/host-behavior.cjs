// Executes the actual production model; this is not a device or ArkUI renderer.
const fs = require('fs');
const vm = require('vm');
const ts = require(process.argv[2]);
const source = fs.readFileSync(process.argv[3], 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 }
}).outputText;
const modelExports = {};
vm.runInNewContext(compiled, { exports: modelExports }, { filename: process.argv[3] });
const counter = new modelExports.CounterModel();
const actual = [counter.count];
counter.add(); actual.push(counter.count);
counter.add(); actual.push(counter.count);
process.stdout.write(JSON.stringify({ counts: actual }));
