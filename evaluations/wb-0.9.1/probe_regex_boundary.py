"""Record an explicitly unsupported lexical boundary; never accept it as parsed."""
import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'src'))
from hmigbot_ios.core import MigrationError, write_json
from hmigbot_ios.swiftui import tokenize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise SystemExit('Preserve the earlier probe; choose a fresh path.')
    examples = [
        'let text = "\\("x".contains(#/[(]/#))"\nlet after = "After"\n',
        'let text = #"\\#("x".contains(#/[(]/#))"#\nlet after = "After"\n',
    ]
    observations = []
    for source in examples:
        try:
            tokens = tokenize(source)
            observations.append({'source': source, 'status': 'unexpectedly_tokenized',
                'tokens': [{'kind': token.kind, 'value': token.value, 'line': token.line} for token in tokens]})
        except MigrationError as error:
            observations.append({'source': source, 'status': 'blocked_unsupported', 'error': str(error),
                'partial_tokens_returned': False})
    write_json(args.output, {'observations': observations, 'swift_compile': 'not_run',
        'source_basis': ['https://docs.swift.org/latest/documentation/the-swift-programming-language/lexicalstructure/',
                         'https://developer.apple.com/documentation/swift/regex'],
        'scope': 'Regex literals inside string interpolation are outside this lexical adapter; errors block source extraction, not accept truncated literals. Error location may point to the following line. Full Swift front-end coverage is still required.'})


if __name__ == '__main__': main()
