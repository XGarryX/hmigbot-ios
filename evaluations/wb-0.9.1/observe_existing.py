"""Capture independently reviewed host observations without resuming control state."""
import argparse
import json
from pathlib import Path
import subprocess

from run_evaluation import (HERE, MODEL, PAGE, ac_inventory, digest, read_json,
                            verify, write_json)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--deveco', type=Path, default=Path('D:/Program Files/DevEco Studio'))
    args = parser.parse_args()
    out = args.attempt.resolve()
    target, source = out / 'target', out / 'source'
    graph = read_json(target / 'spec/baseline/ios-facts.json')
    review = read_json(HERE / 'review.json')
    if graph['source_sha256'] != review['source_sha256'] or any(
            digest((target / p).read_bytes()) != expected for p, expected in review['target_hashes'].items()):
        raise SystemExit('Independent source/target review no longer matches.')
    node = str(args.deveco / 'tools/node/node.exe')
    typescript = str(args.deveco / 'tools/hvigor/hvigor/node_modules/typescript/lib/typescript.js')
    command = [node, str(HERE / 'host-behavior.cjs'), typescript, str(target / MODEL)]
    event = next(f for f in graph['facts'] if f['kind'] == 'event')
    def anchor(path, symbol):
        text = (target / path).read_text(encoding='utf-8')
        line = next(i for i, content in enumerate(text.splitlines(), 1) if symbol in content)
        return {'path': path, 'line': line, 'symbol': symbol, 'sha256': digest((target / path).read_bytes())}
    payload = {'schema_version': 2, 'source_sha256': graph['source_sha256'],
        'chains': [{'source_fact': event['id'], 'input': anchor(PAGE, 'onClick'), 'processing': anchor(MODEL, 'add'),
            'feedback': anchor(PAGE, 'Text'), 'review': {'status': 'reviewed', 'reviewer': review['reviewer']}}],
        'cases': [{'id': 'counter-prefix', 'ac_ids': ['F001-AC01'], 'runner': 'unit', 'command': command,
            'target_hashes': {MODEL: digest((target / MODEL).read_bytes())}, 'input': None,
            'oracle': {'source_fact': next(f['id'] for f in graph['facts'] if f['kind'] == 'state'),
                'expected': review['expected'], 'reviewer': review['reviewer']}}]}
    write_json(target / 'spec/verification/ios-behavior.json', payload)
    result, code = verify(target, source, graph, ac_inventory(target), run=True)
    write_json(out / 'behavior-reviewed.json', result)
    original = (target / MODEL).read_text(encoding='utf-8')
    if original.count('+= 1') != 1: raise SystemExit('Mutation anchor is ambiguous.')
    mutant = out / 'CounterModel-mutant-reviewed.ets'
    mutant.write_text(original.replace('+= 1', '+= 2'), encoding='utf-8')
    probe = subprocess.run([*command[:-1], str(mutant)], capture_output=True, check=False)
    actual = json.loads(probe.stdout)
    write_json(out / 'mutation-reviewed.json', {'mutation': 'actual production increment +1 becomes +2',
        'original_sha256': digest((target / MODEL).read_bytes()), 'mutant_sha256': digest(mutant.read_bytes()),
        'exit_code': probe.returncode, 'actual': actual, 'oracle': review['expected'],
        'discriminated': probe.returncode == 0 and actual != review['expected']})
    print(json.dumps({'status': result['status'], 'exit_code': code, 'observations': result['observations'],
        'pending': result['unverified_ac_ids'], 'mutation_discriminated': actual != review['expected']}, indent=2))


if __name__ == '__main__': main()
