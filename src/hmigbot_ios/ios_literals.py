"""Source-backed literals, with dynamic text and symbolic colors kept distinct."""
import json
import re
from pathlib import Path
from .core import snapshot, digest, write_json
from .swiftui import tokenize


def extract(source):
    snap = snapshot(source)
    ledger = {'schema_version': 2, 'source_platform': 'ios', 'source_sha256': snap['sha256'],
              'texts': [], 'colors': [], 'dims': [], 'durations_ms': [], 'dynamic_texts': [],
              'numeric_constants': [], 'symbolic_colors': [], 'files_scanned': 0,
              'scope': 'source token literals; not runtime values, layout conversion or complete localization'}
    for file in snap['files']:
        if Path(file['path']).suffix not in {'.swift', '.m', '.mm', '.h'}:
            continue
        ledger['files_scanned'] += 1
        tokens = tokenize((source / file['path']).read_text(encoding='utf-8-sig'))
        for i, token in enumerate(tokens):
            anchor = {'sources': [file['path'] + ':' + str(token.line)], 'file_sha256': file['sha256']}
            if token.kind == 'string':
                raw = token.value
                if '\\(' in raw or raw.startswith('"""'):
                    ledger['dynamic_texts'].append({'source_expression': raw, **anchor})
                    continue
                try:
                    value = json.loads(raw)
                except ValueError:
                    ledger['dynamic_texts'].append({'source_expression': raw, **anchor})
                    continue
                if not value:
                    continue
                group = 'colors' if re.fullmatch(r'#[0-9a-fA-F]{6,8}', value) else 'texts'
                ledger[group].append({'value': value, 'page_level': True, **anchor})
            elif re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', token.value):
                value = float(token.value) if '.' in token.value else int(token.value)
                ledger['numeric_constants'].append({'value': value, **anchor})
                context = {t.value for t in tokens[max(0, i - 8):i] if token.line - t.line <= 1}
                if context & {'spacing', 'systemFont', 'fontSize', 'constant', 'padding', 'width', 'height'}:
                    ledger['dims'].append({'value': value, 'unit': 'source_point_or_context_unresolved', **anchor})
            elif token.value in {'white', 'black', 'red', 'blue', 'clear', 'systemBackground', 'label', 'secondaryLabel'} and i and tokens[i - 1].value == '.':
                ledger['symbolic_colors'].append({'value': token.value, 'resolved_rgba': None, **anchor})
    return ledger


def run(project, output=None):
    from .native_pipeline import context
    source, project = context(project)
    ledger = extract(source)
    write_json(output or project / 'spec/baseline/literal-ledger.json', ledger)
    return ledger
