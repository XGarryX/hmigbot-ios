"""Capture actual lexical/structured signals without promoting them to semantics."""
import argparse
from collections import Counter
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import digest, snapshot, write_json
from hmigbot_ios.ios_facts import extract, obligations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists(): raise SystemExit('Choose a fresh capture directory.')
    cases = {}
    for source in sorted((HERE / 'sources').iterdir()):
        graph = extract(source)
        write_json(output / source.name / 'ios-facts.json', graph)
        write_json(output / source.name / 'ios-obligations.json', obligations(graph))
        cases[source.name] = {'source_sha256': graph['source_sha256'], 'source_files': snapshot(source)['files'],
            'fact_kinds': dict(sorted(Counter(f['kind'] for f in graph['facts']).items())),
            'issues': graph['issues'], 'runtime': 'not_run',
            'semantics': 'Authored source-review.md; lexical extraction does not prove these interpretations'}
    write_json(output / 'matrix-capture.json', {'cases': cases,
        'review_sha256': digest((HERE / 'source-review.md').read_bytes()), 'behavior_verified': False})
    print(output / 'matrix-capture.json')


if __name__ == '__main__': main()
