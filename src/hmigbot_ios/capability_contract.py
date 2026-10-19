"""Optional plan-time capability references; no runtime or lifecycle proof."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from .artifact_contract import _json
from .core import MigrationError, safe_child

FIELDS = {'key', 'kind', 'symbol', 'path', 'slot', 'lifecycle', 'provider', 'provenance'}
KINDS = {'runtime-slot', 'scoped', 'artifact-only'}


def _blocks(text):
    # Same fence boundary rules as artifact_contract.json_blocks. Its public
    # iterator only yields action fences, so keep this optional kind separate.
    fence, body = None, []
    for number, line in enumerate(text.splitlines(), 1):
        if fence:
            if re.match(r'^ {0,3}' + re.escape(fence['char']) + '{' + str(fence['size']) + r',}\s*$', line):
                if fence['kind'] == 'capability-declarations':
                    yield '\n'.join(body)
                fence, body = None, []
            else:
                body.append(line)
            continue
        opening = re.match(r'^ {0,3}(`{3,}|~{3,})(.*?)\s*$', line)
        if opening:
            fence = {'char': opening[1][0], 'size': len(opening[1]),
                     'kind': opening[2], 'line': number}
    if fence and fence['kind'] == 'capability-declarations':
        raise MigrationError('capability-declaration-invalid: unclosed fence at line ' + str(fence['line']))


def _relative(project, value):
    if value != value.strip() or any(char in value for char in '*?['):
        raise MigrationError('capability-declaration-invalid: expected exact relative POSIX path: ' + value)
    safe_child(project, value)
    return value


def validate_declarations(project, plans, units):
    """Bind optional declarations to already validated plan units and ownership."""
    blocks = [block for path in plans
              for block in _blocks(path.read_text(encoding='utf-8-sig'))]
    if not blocks:
        return None
    if len(blocks) != 1:
        raise MigrationError('capability-declaration-ambiguous: expected exactly one fence across validated plans')
    try:
        value = _json(blocks[0])
    except MigrationError as exc:
        raise MigrationError('capability-declaration-invalid: ' + str(exc)) from exc
    if not isinstance(value, dict) or set(value) != {'declarations', 'seams'}:
        raise MigrationError('capability-declaration-invalid: expected declarations and seams only')
    if value['seams'] != 'none':
        raise MigrationError('capability-declaration-invalid: only seams="none" is supported')
    declarations = value['declarations']
    if not isinstance(declarations, list) or not declarations:
        raise MigrationError('capability-declaration-invalid: declarations must be a nonempty array')
    files = {item['path'] for item in units.values()}
    seen = set()
    for entry in declarations:
        if not isinstance(entry, dict) or set(entry) != FIELDS:
            raise MigrationError('capability-declaration-invalid: expected exactly the eight declaration fields')
        if any(not isinstance(item, str) for item in entry.values()):
            raise MigrationError('capability-declaration-invalid: declaration fields must be strings')
        if entry['kind'] not in KINDS or any(not entry[key].strip() for key in FIELDS - {'slot'}):
            raise MigrationError('capability-declaration-invalid: unknown kind or empty field')
        if entry['kind'] == 'runtime-slot' and not entry['slot'].strip():
            raise MigrationError('capability-declaration-invalid: runtime-slot needs a slot')
        if entry['key'] in seen:
            raise MigrationError('capability-declaration-invalid: duplicate key: ' + entry['key'])
        seen.add(entry['key'])
        output = _relative(project, entry['path'])
        if entry['provider'].count('#') != 1:
            raise MigrationError('capability-provider-unknown: expected file#full-item_id')
        source, ident = entry['provider'].split('#')
        _relative(project, source)
        if '/' not in source:
            matches = [path for path in files if PurePosixPath(path).name == source]
            if len(matches) > 1:
                raise MigrationError('capability-provider-ambiguous: ' + source)
            source = matches[0] if matches else source
        unit = units.get(ident)
        if unit is None or unit['path'] != source or unit['scope'] != 'product':
            raise MigrationError('capability-provider-unknown: ' + entry['provider'])
        if output not in unit['ownership']:
            raise MigrationError('capability-provider-owner-mismatch: ' + entry['key'])
    return {'status': 'static_references_validated', 'declarations': len(declarations),
            'runtime_verified': False}
