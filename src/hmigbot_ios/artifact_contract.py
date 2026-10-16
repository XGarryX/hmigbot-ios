"""Versioned, read-only checks for authored Spec artifacts.

The catalog is the executable inventory shared with the writing rules. These
checks establish shape, identity and evidence links, never source equivalence.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .core import MigrationError, digest, json_bytes, read_json, safe_child

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / 'schemas/spec-plan-artifacts.json'
SCHEMA_PATH = ROOT / 'schemas/spec-artifacts.schema.json'
SOURCE_REF = re.compile(r'(?P<path>[^:\n;|`]+?\.(?:swift|mm|m|h|storyboard|xib|plist|entitlements|xcstrings|strings|json)):(?P<line>\d+)(?:-(?P<end>\d+))?')
NA = re.compile(r'^\s*(?:not_applicable|N/A|不适用)\s*[:：]', re.I)
UNKNOWN = re.compile(r'(?im)^\s*(?:unknown|TBD|TODO|待确定|待补充)\s*[:：]|\b(?:TBD|TODO)\b')


def _primary_feature(path):
    return bool(re.match(r'F\d+', path.name)) and not re.match(r'F\d+[-_].+\..+\.md$', path.name)


def _artifact_paths(project, entry):
    paths = sorted(Path(project).glob(entry['glob'])) if 'glob' in entry else [Path(project) / entry['path']]
    return [path for path in paths if not entry.get('primary_features') or _primary_feature(path)]


def catalog():
    """Read on demand so installed bundles consume the shipped contract."""
    return read_json(CATALOG_PATH)


def contract_version(project):
    config = read_json(Path(project) / '.migbot/config.json')
    version = config.get('ios_harness', {}).get('spec_contract_version', 1)
    if type(version) is not int or version not in (1, 2):
        raise MigrationError('ios_harness.spec_contract_version must be integer 1 or 2')
    return version


def revision(project=None):
    """Freeze both inventory and field rules; profile is part of the revision."""
    resources = [CATALOG_PATH, SCHEMA_PATH, Path(__file__), Path(__file__).with_name('spec_contract.py')]
    resources += list((ROOT / 'skills/a2h-spec/templates').glob('*.md'))
    resources += [ROOT / 'skills/a2h-spec/references' / name for name in (
        'spec-delivery-contract.md', 'artifact-contracts.md', 'action-contracts.md', 'spec-content-review.md')]
    return digest(json_bytes({'profile': contract_version(project) if project else 2,
                              'resources': {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) if p.is_file() else None
                                            for p in sorted(resources)}}))


def _visible_lines(text):
    """Yield non-code lines with one-based positions, respecting fence kind/size."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        opening = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', line):
                fence = None
            continue
        if opening:
            fence = (opening[1][0], len(opening[1]))
            continue
        yield number, line


def markdown_sections(text):
    """Keep duplicate headings visible and include each section's descendants."""
    lines = text.splitlines()
    headings = []
    for number, line in _visible_lines(text):
        match = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if match:
            headings.append({'title': match[2], 'level': len(match[1]), 'line': number})
    result = []
    for index, heading in enumerate(headings):
        end = next((h['line'] - 1 for h in headings[index + 1:] if h['level'] <= heading['level']), len(lines))
        result.append({**heading, 'body': '\n'.join(lines[heading['line']:end]).strip()})
    return result


def _cells(line):
    line = line.strip()
    if not line.startswith('|'):
        return None
    line = line[1:]
    if line.endswith('|') and not line.endswith('\\|'):
        line = line[:-1]
    cells, current, escaped, ticks = [], [], False, 0
    index = 0
    while index < len(line):
        char = line[index]
        if escaped:
            if char != '|':
                current.append('\\')
            current.append(char); escaped = False; index += 1; continue
        if char == '\\':
            escaped = True; index += 1; continue
        if char == '`':
            stop = index + 1
            while stop < len(line) and line[stop] == '`':
                stop += 1
            count = stop - index
            ticks = 0 if ticks == count else count if not ticks else ticks
            current.append(line[index:stop]); index = stop; continue
        if char == '|' and not ticks:
            cells.append(''.join(current).strip()); current = []
        else:
            current.append(char)
        index += 1
    if escaped:
        current.append('\\')
    cells.append(''.join(current).strip())
    return cells


def markdown_tables(text):
    visible = list(_visible_lines(text))
    found, index = [], 0
    while index + 1 < len(visible):
        number, line = visible[index]
        headers, delimiter = _cells(line), _cells(visible[index + 1][1])
        if (not headers or not delimiter or visible[index + 1][0] != number + 1
                or len(headers) != len(delimiter)
                or not all(re.fullmatch(r':?-{3,}:?', cell) for cell in delimiter)):
            index += 1; continue
        rows, cursor = [], index + 2
        previous = number + 1
        while cursor < len(visible):
            row_number, row_text = visible[cursor]
            cells = _cells(row_text)
            if cells is None or row_number != previous + 1:
                break
            rows.append(cells); previous = row_number; cursor += 1
        found.append({'headers': headers, 'rows': rows, 'line': number})
        index = cursor
    return found


def _json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise MigrationError('Duplicate JSON key: ' + key)
            value[key] = item
        return value
    def invalid(value):
        raise MigrationError('Non-finite JSON number: ' + value)
    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)
    except ValueError as exc:
        raise MigrationError(str(exc)) from exc


def json_blocks(text):
    """Only explicit action fences are contracts; ordinary code is not parsed."""
    fence, body, heading = None, [], ''
    for number, line in enumerate(text.splitlines(), 1):
        if fence:
            if re.match(r'^ {0,3}' + re.escape(fence['char']) + '{' + str(fence['size']) + r',}\s*$', line):
                if fence['kind'] in ('action-contract', 'action-use'):
                    yield {**fence, 'heading': heading, 'body': '\n'.join(body)}
                fence, body = None, []
            else:
                body.append(line)
            continue
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*?)\s*$', line)
        if match:
            fence = {'char': match[1][0], 'size': len(match[1]), 'kind': match[2], 'line': number}
            continue
        match = re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        if match:
            heading = match[1]
    if fence and fence['kind'] in ('action-contract', 'action-use'):
        raise MigrationError('Unclosed action block at line ' + str(fence['line']))


def validate_json(value, definition):
    """Validate the shipped schema subset without optional third-party packages.

    An unknown schema keyword fails closed: declarations cannot silently outrun
    the validator. Arbitrary project data is never interpreted as a schema.
    """
    root = read_json(SCHEMA_PATH)
    supported = {'$ref', 'type', 'const', 'enum', 'required', 'properties', 'additionalProperties',
                 'minLength', 'pattern', 'minimum', 'minItems', 'uniqueItems', 'items', 'description'}
    types = {'object': lambda v: isinstance(v, dict), 'array': lambda v: isinstance(v, list),
             'string': lambda v: isinstance(v, str), 'integer': lambda v: type(v) is int,
             'number': lambda v: type(v) in (int, float), 'boolean': lambda v: type(v) is bool,
             'null': lambda v: v is None}

    def visit(item, rule, location):
        if set(rule) - supported:
            raise MigrationError('Unsupported spec schema keyword: ' + ', '.join(sorted(set(rule) - supported)))
        if '$ref' in rule:
            ref = rule['$ref']
            if not ref.startswith('#/$defs/') or ref[8:] not in root['$defs']:
                raise MigrationError('Unsupported schema reference: ' + ref)
            return visit(item, root['$defs'][ref[8:]], location)
        kinds = rule.get('type')
        if kinds:
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if any(kind not in types for kind in kinds) or not any(types[kind](item) for kind in kinds):
                raise MigrationError(location + ': expected ' + '/'.join(kinds))
        if 'const' in rule and (type(item) is not type(rule['const']) or item != rule['const']):
            raise MigrationError(location + ': wrong constant')
        if 'enum' in rule and item not in rule['enum']:
            raise MigrationError(location + ': unsupported value')
        if isinstance(item, str):
            if len(item.strip()) < rule.get('minLength', 0) or ('pattern' in rule and not re.search(rule['pattern'], item)):
                raise MigrationError(location + ': empty or invalid string')
        if type(item) in (int, float) and 'minimum' in rule and item < rule['minimum']:
            raise MigrationError(location + ': below minimum')
        if isinstance(item, list):
            if len(item) < rule.get('minItems', 0):
                raise MigrationError(location + ': insufficient items')
            if rule.get('uniqueItems') and len({json_bytes(v) for v in item}) != len(item):
                raise MigrationError(location + ': duplicate items')
            for index, child in enumerate(item):
                visit(child, rule.get('items', {}), f'{location}[{index}]')
        if isinstance(item, dict):
            missing = set(rule.get('required', [])) - set(item)
            if missing:
                raise MigrationError(location + ': missing ' + ', '.join(sorted(missing)))
            props = rule.get('properties', {})
            if rule.get('additionalProperties') is False and set(item) - set(props):
                raise MigrationError(location + ': unknown fields ' + ', '.join(sorted(set(item) - set(props))))
            for key, child in item.items():
                if key in props:
                    visit(child, props[key], location + '.' + key)
    if definition not in root['$defs']:
        raise MigrationError('Unknown spec schema definition: ' + definition)
    visit(value, root['$defs'][definition], '$')


def _anchor(source, anchor):
    path = safe_child(source, anchor['path'])
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    if not 1 <= anchor['line'] <= len(lines):
        raise MigrationError('Source line outside file: ' + anchor['path'])


def _evidence(source, text):
    matches = list(SOURCE_REF.finditer(text))
    if not matches:
        raise MigrationError('Provide a real source path:line and a reason')
    for match in matches:
        _anchor(source, {'path': match['path'].strip(), 'line': int(match['line'])})
        if match['end']:
            end = int(match['end'])
            if end < int(match['line']):
                raise MigrationError('Source range ends before it starts')
            _anchor(source, {'path': match['path'].strip(), 'line': end})
    return [(match['path'].strip(), int(match['line']), int(match['end'] or match['line'])) for match in matches]


def authored_inputs(project):
    """Additional v2 authored artifacts to freeze, not a new writable ledger."""
    if contract_version(project) != 2:
        return {}
    found = {}
    for entry in catalog()['spec']:
        paths = _artifact_paths(project, entry)
        for path in paths:
            if path.is_file():
                found[path.relative_to(project).as_posix()] = digest(path.read_bytes())
    for path in (Path(project) / 'spec/baseline/ui-snapshots').glob('*/meta.json'):
        found[path.relative_to(project).as_posix()] = digest(path.read_bytes())
    return found


def external_contracts(project):
    """Resolve authored JSON links into the same transitive MD dependency graph."""
    from .spec_contract import references
    if contract_version(project) != 2:
        return []
    refs = set()

    def collect(value):
        if isinstance(value, dict):
            ref = value.get('contract_ref')
            if isinstance(ref, str):
                refs.add(ref)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    for entry in catalog()['spec']:
        if 'schema' not in entry:
            continue
        paths = _artifact_paths(project, entry)
        for path in paths:
            if path.is_file():
                collect(read_json(path))
    return [target for target, _, _ in references(project, project,
            'contract_refs: ' + json.dumps(sorted(refs)))]


def check_artifacts(project, source, fail, inputs):
    """Append findings through the existing caller and record consumed inputs."""
    from .spec_contract import AC, contract_refs, declared_symbols, references, sections
    project, source = Path(project), Path(source)
    features = {re.match(r'F\d+', p.name)[0]: p for p in (project / 'spec/baseline/features').glob('F*.md') if _primary_feature(p)}
    acs, all_docs = {}, {}
    for path in (project / 'spec/baseline').rglob('*.md'):
        if 'plans' in path.relative_to(project / 'spec/baseline').parts:
            continue
        all_docs[path] = path.read_text(encoding='utf-8-sig')
        for ident, _ in AC.findall(all_docs[path]):
            acs[ident] = path
    # Shared contracts are active only through the same explicit reference
    # closure used by downstream tasks. A ref/ scratch file is not an input;
    # a nested referenced contract must be read at any directory depth.
    pending, visited = list(all_docs), set()
    try:
        pending.extend(external_contracts(project))
    except (MigrationError, OSError, UnicodeError):
        # Malformed optional JSON and its links receive their typed finding
        # below; they cannot turn unrelated ref/ notes into active contracts.
        pass
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        try:
            if path not in all_docs:
                all_docs[path] = path.read_text(encoding='utf-8-sig')
                inputs[path.relative_to(project).as_posix()] = digest(path.read_bytes())
            for target, _, _ in references(project, path, all_docs[path]):
                pending.append(target)
        except (MigrationError, OSError, UnicodeError) as exc:
            fail('REFERENCE_INVALID', path.relative_to(project).as_posix(), str(exc))

    def consume(path):
        inputs[path.relative_to(project).as_posix()] = digest(path.read_bytes())

    def reference(ref):
        resolved = references(project, project, 'contract_refs: ' + json.dumps([ref]))
        return resolved[0]

    def inspect_json(value, subject):
        """Verify all typed evidence and cross-file refs, including nested ones."""
        if isinstance(value, dict):
            for anchor in value.get('source_anchors', []):
                _anchor(source, anchor)
            if 'contract_ref' in value:
                target, _, _ = reference(value['contract_ref']); consume(target)
            for ident in value.get('ac_ids', []):
                if ident not in acs:
                    raise MigrationError('Unknown stable AC: ' + ident)
            for ident in value.get('feature_ids', []) + ([value['feature_id']] if 'feature_id' in value else []):
                if ident not in features:
                    raise MigrationError('Unknown stable feature: ' + ident)
            for child in value.values():
                inspect_json(child, subject)
        elif isinstance(value, list):
            for child in value:
                inspect_json(child, subject)

    for entry in catalog()['spec']:
        paths = _artifact_paths(project, entry)
        if not paths and entry.get('required'):
            fail('ARTIFACT_MISSING', entry.get('glob', entry.get('path')), 'Required artifact is absent')
        for path in paths:
            subject = path.relative_to(project).as_posix()
            if not path.is_file():
                if entry.get('required'):
                    fail('ARTIFACT_MISSING', subject, 'Required artifact is absent')
                continue
            consume(path)
            if 'schema' in entry:
                try:
                    value = read_json(path); validate_json(value, entry['schema']); inspect_json(value, subject)
                    if entry['schema'] == 'state_machine':
                        for transition in value['transitions']:
                            if transition['from'] not in value['states'] or transition['to'] not in value['states']:
                                raise MigrationError('State transition references undefined state')
                    if entry['schema'] == 'api_contract_links':
                        ids = [row['id'] for row in value['endpoints']]
                        if len(ids) != len(set(ids)):
                            raise MigrationError('Duplicate endpoint ID')
                        inventory_path = project / 'spec/baseline/api-inventory.json'
                        if not inventory_path.is_file():
                            raise MigrationError('API links require the original services inventory')
                        inventory = read_json(inventory_path)
                        validate_json(inventory, 'api_inventory')
                        actual = {endpoint.get('id') for service in inventory['services'] for endpoint in service['endpoints']}
                        if not set(ids) <= actual:
                            raise MigrationError('API links refer to endpoint IDs absent from the original inventory')
                except (MigrationError, OSError, UnicodeError, KeyError, TypeError) as exc:
                    fail('ARTIFACT_JSON', subject, str(exc))
                continue
            text = all_docs.get(path, path.read_text(encoding='utf-8-sig'))
            parsed = markdown_sections(text)
            titles = [section['title'] for section in parsed]
            for title in sorted(set(titles)):
                if titles.count(title) > 1:
                    fail('ARTIFACT_HEADING_DUPLICATE', subject + '#' + title, 'Exact headings must resolve uniquely')
            for requirement in entry.get('sections', []):
                matches = [section for section in parsed if section['title'] == requirement['title']]
                body = matches[0]['body'] if matches else ''
                section_subject = subject + '#' + requirement['title']
                if not body:
                    fail('ARTIFACT_SECTION', section_subject, 'Supply the required nonempty section using the catalog/template')
                    continue
                if UNKNOWN.search('\n'.join(line for _, line in _visible_lines(body))):
                    fail('ARTIFACT_UNRESOLVED', section_subject, 'Resolve unknown content or retain a blocking finding before planning')
                is_na = bool(NA.match(body))
                if is_na:
                    try:
                        if requirement.get('allow_na') is False:
                            raise MigrationError('This section is required for every visible page')
                        _evidence(source, body)
                    except (MigrationError, OSError, UnicodeError) as exc:
                        fail('ARTIFACT_NA_EVIDENCE', section_subject, str(exc))
                    continue
                if 'headers' not in requirement:
                    continue
                table = next((table for table in markdown_tables(body) if table['headers'] == requirement['headers']), None)
                if not table or not table['rows'] or any(len(row) != len(table['headers']) or any(not cell.strip() for cell in row) for row in table['rows']):
                    fail('ARTIFACT_TABLE', section_subject, 'Use the exact catalog headers and at least one complete data row, or an evidenced applicable N/A')
                    continue
                evidence_index = next((i for i, header in enumerate(table['headers']) if header in ('源证据', '源依据', '源文件:行')), None)
                if evidence_index is not None:
                    for row in table['rows']:
                        try:
                            _evidence(source, row[evidence_index])
                        except (MigrationError, OSError, UnicodeError) as exc:
                            fail('ARTIFACT_SOURCE', section_subject, str(exc))
                if requirement['title'] == '组件层级':
                    ids = [row[0] for row in table['rows']]
                    parents = {row[0]: row[1] for row in table['rows']}
                    if len(set(ids)) != len(ids) or not any(parent == '-' for parent in parents.values()) or any(parent != '-' and parent not in ids for parent in parents.values()):
                        fail('ARTIFACT_TABLE', section_subject, 'Node IDs must be unique and parents must resolve to a rooted hierarchy')
                    for ident in ids:
                        visited, current = set(), ident
                        while current in parents and current not in visited:
                            visited.add(current); current = parents[current]
                        if current in visited:
                            fail('ARTIFACT_TABLE', section_subject, 'Component hierarchy contains a parent cycle'); break
            if entry.get('page_meta'):
                page_id = re.match(r'page_\d+', path.stem)[0]
                meta = project / ('spec/baseline/ui-snapshots/' + page_id + '/meta.json')
                if not meta.is_file():
                    fail('ARTIFACT_MISSING', meta.relative_to(project).as_posix(), 'Each page requires typed source/runtime metadata')
                    continue
                consume(meta)
                try:
                    value = read_json(meta); validate_json(value, 'page_meta'); inspect_json(value, subject)
                    if value['page_id'] != page_id:
                        raise MigrationError('Metadata page_id does not match its page')
                except (MigrationError, OSError, UnicodeError, KeyError, TypeError) as exc:
                    fail('ARTIFACT_JSON', subject + ':meta', str(exc)); continue
                try:
                    ranges = []
                    for ref in value['source_refs']:
                        ranges.extend(_evidence(source, ref))
                    for anchor in value['source_anchors']:
                        if not any(path == anchor['path'] and start <= anchor['line'] <= end for path, start, end in ranges):
                            raise MigrationError('source_refs and source_anchors must identify overlapping source evidence')
                    if {path for path, _, _ in ranges} != {anchor['path'] for anchor in value['source_anchors']}:
                        raise MigrationError('source_refs and source_anchors must identify the same source files')
                    if 'semantics_ref' in value:
                        relative, _, ident = value['semantics_ref'].partition('#')
                        semantics = safe_child(project, relative)
                        if ident != page_id or not any(document.get('id') == ident for document in read_json(semantics).get('documents', [])):
                            raise MigrationError('semantics_ref must resolve to this page in the native semantics document')
                        consume(semantics)
                    if value['runtime'] == 'not_run' and value['screenshot'] is not None:
                        raise MigrationError('not_run metadata must keep screenshot=null')
                    if value['runtime'] != 'not_run' and value['screenshot'] is None:
                        raise MigrationError('Captured/verified metadata needs an actual screenshot')
                    if value['screenshot'] is not None and not safe_child(project, value['screenshot']).is_file():
                        raise MigrationError('Screenshot evidence does not exist')
                except (MigrationError, OSError, UnicodeError) as exc:
                    fail('ARTIFACT_META_EVIDENCE', subject, str(exc))

    definitions, uses, by_document = {}, [], {}
    for path, text in all_docs.items():
        try:
            blocks = list(json_blocks(text))
        except MigrationError as exc:
            fail('ACTION_JSON', path.relative_to(project).as_posix(), str(exc)); continue
        for block in blocks:
            subject = path.relative_to(project).as_posix() + ':' + str(block['line'])
            consume(path)
            try:
                value = _json(block['body']); validate_json(value, block['kind'].replace('-', '_'))
            except (MigrationError, OSError, UnicodeError) as exc:
                fail('ACTION_JSON', subject, str(exc)); continue
            by_document.setdefault(path, []).append(value['action_id'])
            if block['kind'] == 'action-use':
                uses.append((path, block, value)); continue
            ident = value['action_id']
            if ident in definitions:
                fail('ACTION_DUPLICATE', ident, 'Define a shared action exactly once; consumers use action-use')
                prior = definitions[ident][2]
                if any(prior[key] != value[key] for key in ('owner', 'target', 'immediate_effect', 'completion_event', 'final_effect', 'failure_cancel', 'scope')):
                    fail('ACTION_CONFLICT', ident, 'Duplicate action definitions disagree on owner, target or completion semantics')
            else:
                definitions[ident] = (path, block, value)
            if value['owner'] not in features or not ident.startswith(value['owner'] + '-'):
                fail('ACTION_OWNER', ident, 'Action ID and owner must resolve to the same stable feature')
            if value['scope'] == 'skipped':
                try:
                    skip_ref, decision_ref = value.get('skip_ref', ''), value.get('decision_ref', '')
                    if not skip_ref.startswith('spec/baseline/skip-list.md#'):
                        raise MigrationError('Skipped action requires an exact skip_ref into the existing skip-list')
                    target, _, body = reference(skip_ref); consume(target); _evidence(source, body)
                    relative, _, title = decision_ref.partition('#')
                    if relative != 'spec/decision-ledger.md' or not title:
                        raise MigrationError('Skipped action requires decision_ref into the existing decision-ledger')
                    decision = safe_child(project, relative)
                    candidates = [s for s in markdown_sections(decision.read_text(encoding='utf-8-sig')) if s['title'] == title and s['body']]
                    if len(candidates) != 1:
                        raise MigrationError('Decision reference must resolve to an exact nonempty unique heading')
                    consume(decision)
                    # Do not broaden source exclusion semantics. Only the existing
                    # reviewed Preview disposition is executable in this harness.
                    from .source_scope import preview_lines
                    coverage = read_json(project / 'spec/baseline/ios-coverage.json')
                    facts = read_json(project / 'spec/baseline/ios-facts.json')['facts']
                    mappings = {row['obligation_id']: row for row in coverage['mappings']}
                    for anchor in value['source_anchors']:
                        source_path = safe_child(source, anchor['path'])
                        if anchor['line'] not in preview_lines(source_path.read_text(encoding='utf-8-sig')):
                            raise MigrationError('Production action exclusion is not supported by the current source-disposition contract; retain blocking scope review')
                        relevant = [fact for fact in facts if fact['anchor']['path'] == anchor['path'] and fact['anchor']['line'] == anchor['line']]
                        if not relevant:
                            raise MigrationError('Skipped action has no exact reviewed source disposition')
                        for fact in relevant:
                            row = mappings.get('IO-' + fact['id'][3:], {})
                            if (row.get('disposition') != 'preview-only' or row.get('skip_ref') != skip_ref
                                    or row.get('source_sha256') != digest(source_path.read_bytes())
                                    or row.get('source_review', {}).get('status') != 'reviewed'):
                                raise MigrationError('Skipped action needs the existing current reviewed Preview disposition; action scope never removes obligations')
                except (MigrationError, OSError, UnicodeError, KeyError, TypeError) as exc:
                    fail('ACTION_SKIPPED_SCOPE', ident, str(exc))
            if value['target'] not in declared_symbols(sections(text)):
                # A definition can share the ordinary contract_refs closure.
                try:
                    refs = references(project, path, text)
                    if not any(value['target'] in declared_symbols({heading: body}) for _, heading, body in refs):
                        fail('ACTION_TARGET', ident, 'Action target must be declared in its contract or an explicit shared reference')
                except MigrationError as exc:
                    fail('ACTION_TARGET', ident, str(exc))
            for ac in value['ac_ids']:
                if ac not in acs or not ac.startswith(value['owner'] + '-AC'):
                    fail('ACTION_AC', ident, 'Action AC must resolve to its owner feature: ' + ac)
            try:
                for anchor in value['source_anchors']:
                    _anchor(source, anchor)
            except (MigrationError, OSError, UnicodeError) as exc:
                fail('ACTION_SOURCE', ident, str(exc))
            if any(UNKNOWN.search(value[key]) for key in ('immediate_effect', 'completion_event', 'final_effect', 'failure_cancel')):
                fail('ACTION_UNRESOLVED', ident, 'Action timing and outcomes must be resolved before planning')
    for path, block, value in uses:
        ident = value['action_id']
        try:
            if value['contract_ref'] not in contract_refs(all_docs[path]):
                raise MigrationError('Declare action contract_ref in contract_refs so task inputs include the definition')
            target, heading, _ = reference(value['contract_ref']); consume(target)
            if ident not in definitions or definitions[ident][0] != target or definitions[ident][1]['heading'] != heading:
                raise MigrationError('Action use must reference the exact unique definition heading')
            definition = definitions[ident][2]
            if definition['scope'] == 'skipped':
                fail('ACTION_SKIPPED', ident, 'Active consumer cannot depend on an excluded action')
            for ac in value['ac_ids']:
                if ac not in acs or ac not in definition['ac_ids']:
                    fail('ACTION_AC', ident, 'Use ACs must be declared by the referenced action: ' + ac)
        except (MigrationError, OSError, UnicodeError) as exc:
            fail('ACTION_REFERENCE', ident, str(exc))
    for ident, path in features.items():
        text = all_docs[path]
        match = re.search(r'^action_contracts:\s*(\w+)\s*$', text, re.M)
        mode = match[1] if match else None
        if mode == 'required':
            if not by_document.get(path):
                fail('ACTION_REQUIRED', ident, 'Applicable high-risk actions need definitions or exact action-use references')
        elif mode == 'not_applicable':
            reason = re.search(r'^action_contracts_reason:\s*(.+)$', text, re.M)
            try:
                if not reason:
                    raise MigrationError('Provide a reason for not-applicable actions')
                _evidence(source, reason[1])
            except (MigrationError, OSError, UnicodeError) as exc:
                fail('ACTION_NA_EVIDENCE', ident, str(exc))
        else:
            fail('ACTION_APPLICABILITY', ident, 'Declare action_contracts: required or evidenced not_applicable; risk selection still requires independent source review')
