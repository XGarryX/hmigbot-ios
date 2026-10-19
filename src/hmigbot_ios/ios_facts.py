"""Deterministic source signals. Token evidence is never compiler or runtime proof."""
from __future__ import annotations

import re
from pathlib import Path
import xml.etree.ElementTree as ET

from .core import MigrationError, digest, json_bytes, read_json, snapshot, write_json
from .swiftui import tokenize
from .source_scope import import_token_lines
from .xcode import project_inventory, dependency_inventory
from .resources import asset_inventory

RULES = read_json(Path(__file__).with_name('ios_rules.json'))['rules']
SOURCE_KINDS = {'.swift', '.m', '.mm', '.h', '.c', '.cpp'}


def _is_task_priority_argument(values, index):
    """True only when a 'priority' token is the keyword argument of a Task constructor.

    Task.detached/Task/Task.init schedule work by priority; that is concurrency, not
    layout, so the enclosing 'Task' token already emits the task/concurrency obligation
    and its token window carries the priority literal. Every other 'priority' (property
    access, unknown callee, non-call) keeps its original constraint signal: lexical context
    alone cannot prove a scheduling meaning, so we do not exempt it.
    """
    if values[index] != 'priority' or index == 0 or index + 1 >= len(values):
        return False
    if values[index - 1] not in {'(', ','} or values[index + 1] != ':':
        return False
    open_index = index - 1
    if values[open_index] == ',':  # Later argument: walk back past balanced groups to the call's '('.
        depth, scan = 0, open_index - 1
        while scan >= 0:
            if values[scan] in {')', ']', '}'}:
                depth += 1
            elif values[scan] in {'(', '[', '{'}:
                if depth == 0:
                    break
                depth -= 1
            scan -= 1
        else:
            return False
        open_index = scan
    if values[open_index] != '(':
        return False
    if open_index >= 1 and values[open_index - 1] == 'Task':
        head = open_index - 1  # Task(priority: ...) initializer
    elif (open_index >= 3 and values[open_index - 1] in {'detached', 'init'}
          and values[open_index - 2] == '.' and values[open_index - 3] == 'Task'):
        head = open_index - 3  # Task.detached / Task.init
    else:
        return False
    return head == 0 or values[head - 1] != '.'  # An unknown qualified callee keeps protection.


def _is_button_cancel_role(values, index):
    """Recognize only the exact .cancel value of a bare Button's role argument.

    Calls, unknown member references and handler tokens keep their task signals.
    The Button event still carries the role value in its evidence window.
    """
    if (index < 4 or values[index - 3:index + 1] != ['role', ':', '.', 'cancel']
            or index + 1 >= len(values) or values[index + 1] not in {',', ')'}):
        return False
    open_index = index - 4
    if values[open_index] == ',':
        depth, scan = 0, open_index - 1
        while scan >= 0:
            if values[scan] in {')', ']', '}'}:
                depth += 1
            elif values[scan] in {'(', '[', '{'}:
                if depth == 0:
                    break
                depth -= 1
            scan -= 1
        else:
            return False
        open_index = scan
    return (open_index >= 1 and values[open_index] == '(' and values[open_index - 1] == 'Button'
            and (open_index == 1 or values[open_index - 2] != '.'))


def extract(source: Path, variant: dict | None = None, *, manifest_evidence: Path | None = None):
    """Repository scope is explicit; effective configuration remains unresolved without tools."""
    snap = snapshot(source)
    variant = variant or {'scope': 'repository', 'effective_build': 'unresolved'}
    if not isinstance(variant, dict) or variant.get('scope') not in {'repository', 'selected-build', 'project-targets'}:
        raise MigrationError('Variant must declare repository, selected-build or project-targets scope')
    if variant['scope'] == 'project-targets':
        from .project_scope import resolve
        variant = resolve(source, variant)
    if variant['scope'] == 'selected-build':
        # Membership needs an explicit path set; caller cannot promote guessed settings.
        if not isinstance(variant.get('source_files'), list) or not variant.get('evidence_path'):
            raise MigrationError('Selected build requires source_files and captured evidence_path')
        if not set(variant['source_files']) <= {f['path'] for f in snap['files']}:
            raise MigrationError('Variant contains unknown source files')
        from .evidence import validate
        bundle = Path(variant['evidence_path'])
        captured = validate(source, bundle)
        membership = read_json(bundle / 'artifacts/source-files.json')
        manifest = read_json(bundle / 'manifest.json')
        if captured['kind'] != 'source_build' or 'artifacts/source-files.json' not in manifest['artifacts'] or membership.get('source_files') != variant['source_files']:
            raise MigrationError('Selected membership must match hashed source-build evidence')
    evaluated_manifests, evidence_ref = None, None
    if manifest_evidence is not None:
        from .manifest_evidence import validate
        bundle = Path(manifest_evidence).resolve()
        report_path = bundle / 'manifest.json' if bundle.is_dir() else bundle
        evaluation = validate(source, bundle)
        evaluated_manifests = evaluation['manifests']
        evidence_ref = {'path': str(report_path), 'report_sha256': digest(report_path.read_bytes())}
    facts, issues = [], []
    occurrence = {}

    def add(file, kind, line, end, symbol, value, owner='unresolved', evidence='token_signal'):
        key = (file['path'], kind, owner, symbol)
        occurrence[key] = occurrence.get(key, 0) + 1
        ident = 'IF-' + digest(json_bytes([*key, occurrence[key]]))[:16]
        raw = (source / file['path']).read_bytes()
        try:
            text = raw.decode('utf-8-sig')
            snippet = '\n'.join(text.splitlines()[line - 1:end])
        except UnicodeError:
            if kind != 'resource':
                raise MigrationError('Non-text source needs an explicit parser: ' + file['path'])
            snippet = 'binary resource sha256:' + file['sha256']
            value = {**value, 'encoding': 'binary', 'content_validation': 'unresolved'}
        facts.append({'id': ident, 'kind': kind, 'symbol': symbol, 'owner': owner,
                      'value': value, 'resolution': evidence, 'variant': variant['scope'],
                      'anchor': {'path': file['path'], 'line': line, 'end_line': end,
                                 'file_sha256': file['sha256'], 'snippet_sha256': digest(snippet.encode()),
                                 'snippet': snippet}})

    for file in snap['files']:
        path = source / file['path']
        if variant['scope'] == 'selected-build' and path.suffix in SOURCE_KINDS and file['path'] not in variant['source_files']:
            continue
        if (variant['scope'] == 'project-targets' and path.suffix in SOURCE_KINDS - {'.h'}
                and file['path'] not in variant['source_files']):
            continue  # Declared product membership; implicit headers remain conservatively included.
        if path.suffix in SOURCE_KINDS:
            text = path.read_text(encoding='utf-8-sig')
            tokens = tokenize(text)
            import_lines = import_token_lines(tokens)
            values = [t.value for t in tokens]
            owner, pending_owner, depth, stack, wrapper_vars = 'file', None, 0, [], set()
            storage = {'State', 'StateObject', 'ObservedObject', 'EnvironmentObject', 'Environment', 'Binding', 'AppStorage', 'SceneStorage'}
            for i, token in enumerate(tokens):
                v = token.value
                if v in {'class', 'struct', 'enum', 'extension'} and i + 1 < len(tokens):
                    pending_owner = values[i + 1]
                if v == '{':
                    depth += 1
                    if pending_owner:
                        stack.append((depth, owner)); owner = pending_owner; pending_owner = None
                if v == '}':
                    if stack and stack[-1][0] == depth:
                        _, owner = stack.pop()
                    depth -= 1
                # No comment/string scans: only syntax tokens can activate a rule.
                if token.kind == 'string':
                    continue
                if token.line in import_lines:
                    if v == ';':
                        import_lines.remove(token.line)
                    continue  # A dependency import is not an executable persistence/event operation.
                after = values[i + 1:i + 24]
                window = ' '.join(after)
                if v == '@' and after and after[0] in storage:
                    start = i + 2
                    while start < len(tokens) and start < i + 16 and values[start] not in {'var', '{', '}'}:
                        start += 1
                    if start >= len(tokens) or values[start] != 'var':
                        issues.append({'rule': 'IOS.STATE_UNRESOLVED', 'path': file['path'], 'line': token.line})
                        continue
                    wrapper_vars.add(start)
                    end = start + 1
                    while end < len(tokens) and tokens[end].line == tokens[start].line and values[end] not in {'{', '}', ';'}:
                        end += 1
                    declaration = values[i + 1:end]
                    if 'var' not in declaration:
                        issues.append({'rule': 'IOS.STATE_UNRESOLVED', 'path': file['path'], 'line': token.line})
                    else:
                        k = declaration.index('var')
                        name = declaration[k + 1] if k + 1 < len(declaration) else 'unresolved'
                        init = ' '.join(declaration[declaration.index('=') + 1:]) if '=' in declaration else None
                        type_ = ' '.join(declaration[declaration.index(':') + 1:declaration.index('=') if '=' in declaration else len(declaration)]) if ':' in declaration else None
                        add(file, 'binding' if after[0] == 'Binding' else 'state', token.line, tokens[end - 1].line,
                            name, {'storage': after[0], 'type': type_, 'initializer': init}, owner)
                if v == 'var' and i not in wrapper_vars and stack and depth == stack[-1][0]:
                    end = i + 1
                    while end < len(tokens) and tokens[end].line == token.line and values[end] not in {'{', '}', ';'}:
                        end += 1
                    decl = values[i + 1:end]
                    if '=' in decl and decl:
                        k = decl.index('=')
                        type_ = ' '.join(decl[decl.index(':') + 1:k]) if ':' in decl else None
                        add(file, 'state', token.line, token.line, decl[0], {'storage': 'stored_property', 'type': type_, 'initializer': ' '.join(decl[k + 1:])}, owner)
                if v in {'Button', 'onTapGesture', 'addTarget', 'IBAction'}:
                    add(file, 'event', token.line, min(tokens[min(i + 12, len(tokens) - 1)].line, token.line + 3), v,
                        {'trigger': v, 'tokens': window, 'handler_resolution': 'unresolved'}, owner)
                if v in {'=', '+=', '-='} and i > 0:
                    if values[i - 1] not in {'=', '<', '>', '!', '+', '-'}:
                        add(file, 'write', token.line, token.line, values[i - 1], {'operator': v, 'tokens': window}, owner)
                if v in {'if', 'guard', 'switch', 'catch', 'throw'}:
                    add(file, 'branch', token.line, token.line, v, {'condition_tokens': window}, owner)
                if v in {'task', 'Task', 'async', 'await', 'MainActor', 'cancel'}:
                    if not (v == 'cancel' and _is_button_cancel_role(values, i)):
                        add(file, 'task', token.line, token.line, v, {'tokens': window, 'binding': 'unresolved'}, owner)
                if v in {'NavigationLink', 'navigationDestination', 'sheet', 'fullScreenCover', 'pushViewController', 'present', 'performSegue'}:
                    add(file, 'navigation', token.line, token.line, v, {'tokens': window, 'destination': 'unresolved'}, owner)
                if v in {'UserDefaults', 'AppStorage', 'SceneStorage', 'CoreData', 'SwiftData', 'Keychain', 'SecItemAdd', 'SecItemCopyMatching'}:
                    add(file, 'persistence', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'URLSession', 'Alamofire', 'AVPlayer', 'CLLocationManager', 'StoreKit', 'WKWebView', 'requestAuthorization'}:
                    add(file, 'service', token.line, token.line, v, {'tokens': window, 'contract': 'unresolved'}, owner)
                if v in {'viewDidLoad', 'viewWillAppear', 'viewDidAppear', 'viewWillDisappear', 'viewDidDisappear', 'deinit', 'onAppear', 'onDisappear'}:
                    add(file, 'lifecycle', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'constraint', 'NSLayoutConstraint', 'priority'}:
                    if not (v == 'priority' and _is_task_priority_argument(values, i)):
                        add(file, 'constraint', token.line, token.line, v, {'tokens': window, 'relation': 'unresolved'}, owner)
                if v == 'ForEach' or v == 'id' and i and values[i - 1] == '.':
                    add(file, 'identity', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'VStack', 'HStack', 'ZStack', 'List', 'ScrollView', 'Text', 'Image', 'UIView', 'UILabel', 'UIButton', 'UIStackView'}:
                    add(file, 'composition', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'frame', 'padding', 'background', 'overlay', 'clipShape', 'offset', 'position', 'opacity', 'transition', 'animation'} and i and values[i - 1] == '.':
                    add(file, 'modifier', token.line, token.line, v, {'token_index': i, 'tokens': window, 'order': 'lexical_only'}, owner)
                if v in {'Environment', 'EnvironmentObject', 'environment', 'environmentObject'}:
                    add(file, 'environment', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'nil', 'nullable', 'nonnull', '_Nullable', '_Nonnull'} or v == '?' and i and tokens[i - 1].kind == 'identifier':
                    add(file, 'language', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'weak', 'unowned', 'copy', 'assign', 'strong'}:
                    add(file, 'ownership', token.line, token.line, v, {'tokens': window}, owner)
                if v in {'delegate', 'dataSource', 'performSelector', 'valueForKey', 'setValue'}:
                    add(file, 'delegate', token.line, token.line, v, {'tokens': window, 'receiver': 'unresolved'}, owner)
            if depth != 0:
                issues.append({'rule': 'IOS.TOKEN_BALANCE', 'path': file['path'], 'message': 'Use a syntax provider; token scope is incomplete'})
            if any(ord(t.value[0]) > 127 and t.kind != 'string' for t in tokens if t.value):
                issues.append({'rule': 'IOS.TOKEN_IDENTIFIER_UNRESOLVED', 'path': file['path'], 'message': 'Unicode identifiers require a syntax provider and explicit review'})
            if re.search(r'^\s*#\s*(if|ifdef|ifndef)', text, re.M):
                issues.append({'rule': 'IOS.CONDITIONAL_BUILD', 'path': file['path'], 'message': 'Resolve active branches using selected configuration'})
        elif path.suffix in {'.storyboard', '.xib'}:
            text = path.read_text(encoding='utf-8-sig')
            if '<!DOCTYPE' in text or '<!ENTITY' in text:
                raise MigrationError('Interface Builder DTD/entities are not supported')
            try:
                tree = ET.fromstring(text)
                for element in tree.iter():
                    kind = {'action': 'event', 'segue': 'navigation', 'constraint': 'constraint'}.get(element.tag)
                    if kind:
                        # XML parser verifies structure; textual location is a locator only.
                        ident = element.get('id', element.get('selector', element.tag))
                        line = next((n for n, s in enumerate(text.splitlines(), 1) if ident in s), 1)
                        add(file, kind, line, line, ident, dict(element.attrib), evidence='structured_xml')
            except ET.ParseError as exc:
                issues.append({'rule': 'IOS.IB_PARSE', 'path': file['path'], 'message': str(exc)})
        elif path.name == 'Contents.json' or path.suffix in {'.xcstrings', '.stringsdict', '.xcprivacy', '.entitlements', '.plist'}:
            add(file, 'resource', 1, 1, path.name, {'resource_type': path.suffix or path.name}, evidence='resource_locator')
    project, pi = project_inventory(source, snap['files'])
    dependencies, di = dependency_inventory(source, snap['files'], manifest_evaluations=evaluated_manifests)
    assets, ai = asset_inventory(source, snap['files'])
    graph = {'schema_version': 2, 'source_platform': 'ios', 'source_sha256': snap['sha256'],
            'variant': variant, 'facts': facts, 'issues': issues + pi + di + ai,
            'project': project, 'dependencies': dependencies, 'assets': assets,
            'capabilities': {'syntax': 'token_signal', 'symbol_binding': 'unresolved',
                             'effective_build': 'unresolved', 'runtime': 'unavailable'}}
    if evidence_ref is not None:
        graph['manifest_evidence'] = evidence_ref
    return graph


def obligations(graph):
    return {'schema_version': 2, 'source_sha256': graph['source_sha256'],
            'graph_sha256': digest(json_bytes(graph)), 'rules_sha256': digest(json_bytes(RULES)),
            'obligations': [{'id': 'IO-' + fact['id'][3:], 'fact_id': fact['id'], 'kind': fact['kind'],
                             **RULES[fact['kind']]} for fact in graph['facts']]}


def refresh(project, source, variant=None, provider_plan=None, manifest_evidence=None):
    if manifest_evidence is not None:
        manifest_evidence = Path(manifest_evidence).resolve()
        if not manifest_evidence.is_relative_to((project / 'spec/ref/ios-manifest-evidence').resolve()):
            raise MigrationError('Manifest evidence must be under project/spec/ref/ios-manifest-evidence for pinned consumption')
    graph = extract(source, variant, manifest_evidence=manifest_evidence)
    if provider_plan:
        from .atoms import run_atom
        providers = read_json(provider_plan)
        if not isinstance(providers, dict) or providers.get('schema_version') != 2 or not isinstance(providers.get('providers'), list):
            raise MigrationError('Provider plan requires v2 providers array')
        graph['provider_artifacts'] = []
        for provider in providers['providers']:
            if provider.get('operation') not in {'swift-syntax', 'clang-ast', 'build-settings', 'interface-builder', 'asset-inventory', 'localization-inventory'}:
                raise MigrationError('Unsupported source provider operation')
            name = provider['operation']
            output = project / 'spec/ref/provider-runs' / name / graph['source_sha256']
            if output.exists():
                raise MigrationError('Existing provider capture is immutable; choose fresh source or review retained artifacts')
            try:
                config = Path(provider['config']) if provider.get('config') else None
                input_path = Path(provider['input']) if provider.get('input') else None
                report = run_atom(name, source, output, provider_config=config, input_path=input_path)
            except (MigrationError, OSError, ValueError) as exc:
                write_json(output / 'failure.json', {'operation': name, 'status': 'failed', 'source_sha256': graph['source_sha256'], 'error': str(exc)})
                raise MigrationError('Provider failed; retained diagnostics: ' + str(output)) from exc
            artifact = (output / 'artifact.json').relative_to(project).as_posix()
            graph['provider_artifacts'].append({'path': artifact, 'sha256': digest((output / 'artifact.json').read_bytes()), 'operation': name})
            if report.get('issues'):
                graph['issues'].extend({'rule': 'IOS.PROVIDER_UNRESOLVED', 'operation': name, 'detail': issue} for issue in report['issues'])
    base = project / 'spec/baseline'
    if (base / 'ios-facts.json').exists():
        previous = read_json(base / 'ios-facts.json')
        if previous != graph:
            archive = project / 'spec/.a2h/history' / digest(json_bytes(previous))
            write_json(archive / 'ios-facts.json', previous)
    write_json(base / 'ios-facts.json', graph)
    write_json(base / 'ios-obligations.json', obligations(graph))
    if snapshot(source)['sha256'] != graph['source_sha256']:
        raise MigrationError('Source changed while extracting; retained graph is invalid until refreshed')
    return graph


def validate_graph(source, project):
    graph = read_json(project / 'spec/baseline/ios-facts.json')
    manifest = graph.get('manifest_evidence')
    evidence_path = None
    if manifest is not None:
        if (not isinstance(manifest, dict) or set(manifest) != {'path', 'report_sha256'}
                or not isinstance(manifest['path'], str)):
            raise MigrationError('Invalid manifest evaluation evidence reference')
        evidence_path = Path(manifest['path']).resolve()
        if not evidence_path.is_relative_to((project / 'spec/ref/ios-manifest-evidence').resolve()):
            raise MigrationError('Manifest evidence reference escapes the pinned project evidence directory')
        if digest(evidence_path.read_bytes()) != manifest['report_sha256']:
            raise MigrationError('Manifest evaluation evidence changed')
    current = extract(source, graph.get('variant'), manifest_evidence=evidence_path)
    if graph.get('provider_artifacts'):
        from .core import safe_child
        current['provider_artifacts'] = graph['provider_artifacts']
        for item in graph['provider_artifacts']:
            path = safe_child(project, item['path'])
            if digest(path.read_bytes()) != item['sha256']:
                raise MigrationError('Provider evidence changed')
            report = read_json(path)
            if report.get('source_sha256') != current['source_sha256']:
                raise MigrationError('Provider evidence source is stale')
            current['issues'].extend({'rule': 'IOS.PROVIDER_UNRESOLVED', 'operation': item['operation'], 'detail': issue} for issue in report.get('issues', []))
    if graph != current:
        raise MigrationError('Source facts are stale or edited; re-extract and re-review affected coverage')
    expected = obligations(graph)
    if read_json(project / 'spec/baseline/ios-obligations.json') != expected:
        raise MigrationError('Obligations must be machine-derived from current facts and rules')
    return graph, expected


def view(project, source, scope):
    graph, obs = validate_graph(source, project)
    selections = {
        'project': set(),
        'ui': {'state', 'binding', 'event', 'navigation', 'lifecycle', 'constraint', 'identity', 'composition', 'modifier', 'environment', 'delegate'},
        'feature': {'state', 'write', 'branch', 'task', 'persistence', 'service', 'language', 'ownership', 'lifecycle'},
        'api': {'service', 'persistence', 'task', 'delegate', 'resource'}
    }
    if scope not in selections:
        raise MigrationError('Unknown source analysis scope')
    value = {'schema_version': 2, 'scope': scope, 'source_sha256': graph['source_sha256'],
             'graph_sha256': digest(json_bytes(graph)), 'issues': graph['issues'], 'capabilities': graph['capabilities'],
             'facts': [f for f in graph['facts'] if f['kind'] in selections[scope]]}
    if scope == 'project':
        value.update(project=graph['project'], dependencies=graph['dependencies'], assets=graph['assets'])
    ids = {f['id'] for f in value['facts']}
    value['obligations'] = [o for o in obs['obligations'] if o['fact_id'] in ids]
    write_json(project / f'spec/ref/ios-{scope}-signals.json', value)
    return value
