"""Xcode/OpenStep structure, without pretending to evaluate an Xcode build."""
from pathlib import Path
import re

from .core import MigrationError, read_json


class OpenStep:
    def __init__(self, text):
        self.tokens = []
        pos = 0
        while pos < len(text):
            if text[pos].isspace() or text[pos] == '\ufeff':
                pos += 1
            elif text.startswith('//', pos):
                end = text.find('\n', pos)
                pos = end if end >= 0 else len(text)
            elif text.startswith('/*', pos):
                end = text.find('*/', pos + 2)
                if end < 0:
                    raise MigrationError('Unterminated OpenStep comment')
                pos = end + 2
            elif text[pos] == '"':
                pos += 1
                chars = []
                while pos < len(text) and text[pos] != '"':
                    if text[pos] == '\\':
                        pos += 1
                        if pos >= len(text):
                            raise MigrationError('Unterminated OpenStep escape')
                        escape = text[pos]
                        if escape in {'n', 'r', 't', '"', '\\'}:
                            chars.append({'n': '\n', 'r': '\r', 't': '\t'}.get(escape, escape))
                        elif escape in '01234567':
                            match = re.match('[0-7]{1,3}', text[pos:])
                            chars.append(chr(int(match.group(), 8)))
                            pos += len(match.group()) - 1
                        elif escape == 'U' and re.fullmatch('[0-9A-Fa-f]{4}', text[pos + 1:pos + 5]):
                            chars.append(chr(int(text[pos + 1:pos + 5], 16)))
                            pos += 4
                        else:
                            raise MigrationError(f'Unsupported OpenStep escape: {escape}')
                    else:
                        chars.append(text[pos])
                    pos += 1
                if pos >= len(text):
                    raise MigrationError('Unterminated OpenStep string')
                self.tokens.append(('value', ''.join(chars)))
                pos += 1
            elif text[pos] in '{}()=;,':
                self.tokens.append(('punctuation', text[pos]))
                pos += 1
            else:
                match = re.match(r'[^\s{}()=;,"]+', text[pos:])
                if not match:
                    raise MigrationError('Invalid OpenStep input')
                self.tokens.append(('value', match.group()))
                pos += len(match.group())
        self.pos = 0

    def is_punctuation(self, value):
        return self.pos < len(self.tokens) and self.tokens[self.pos] == ('punctuation', value)

    def take(self, punctuation=None):
        if self.pos == len(self.tokens):
            raise MigrationError('Unexpected end of OpenStep document')
        token = self.tokens[self.pos]
        if punctuation is not None and token != ('punctuation', punctuation):
            raise MigrationError(f'Expected OpenStep {punctuation}, found {token[1]}')
        self.pos += 1
        return token

    def value(self, depth=0):
        if depth > 128:
            raise MigrationError('OpenStep nesting limit exceeded')
        if self.is_punctuation('{'):
            self.take('{')
            result = {}
            while not self.is_punctuation('}'):
                kind, key = self.take()
                if kind != 'value' or key in result:
                    raise MigrationError('Invalid or duplicate OpenStep dictionary key')
                self.take('=')
                result[key] = self.value(depth + 1)
                self.take(';')
            self.take('}')
            return result
        if self.is_punctuation('('):
            self.take('(')
            result = []
            while not self.is_punctuation(')'):
                result.append(self.value(depth + 1))
                if not self.is_punctuation(')'):
                    self.take(',')
            self.take(')')
            return result
        kind, value = self.take()
        if kind != 'value':
            raise MigrationError('Expected OpenStep scalar')
        return value

    def parse(self):
        value = self.value()
        if self.pos != len(self.tokens):
            raise MigrationError('Trailing OpenStep content')
        return value


def project_inventory(root, files):
    projects, issues = [], []
    for item in files:
        if not item['path'].endswith('.pbxproj'):
            continue
        path = root / item['path']
        try:
            document = OpenStep(path.read_text(encoding='utf-8-sig')).parse()
            objects = document.get('objects', {})
            if not isinstance(objects, dict):
                raise MigrationError('Xcode objects must be a dictionary')
            parents = {}
            for key, obj in objects.items():
                if not isinstance(obj, dict):
                    raise MigrationError('Invalid Xcode object')
                for child in obj.get('children', []):
                    parents.setdefault(child, []).append(key)
            project_base = path.parent.parent

            def file_path(key, visited=()):
                if key in visited:
                    raise MigrationError('Cyclic Xcode groups')
                obj = objects.get(key, {})
                tree, local = obj.get('sourceTree', '<group>'), obj.get('path', '')
                if tree == 'SOURCE_ROOT':
                    result = project_base / local
                elif tree == '<group>':
                    parent = parents.get(key, [])
                    if len(parent) > 1:
                        return None
                    base = file_path(parent[0], visited + (key,)) if parent else project_base
                    if base is None:
                        return None
                    result = base / local
                else:
                    return None  # SDKROOT, BUILT_PRODUCTS_DIR and external references remain logical.
                return result.resolve()

            def reference(key):
                obj = objects.get(key, {})
                actual = file_path(key)
                relative = actual.relative_to(root).as_posix() if actual is not None and actual.is_relative_to(root) else None
                return {'id': key, 'name': obj.get('name', obj.get('path')), 'source_tree': obj.get('sourceTree'),
                        'path': relative, 'exists': bool(actual and actual.is_file()),
                        'resolution': 'repository_path' if relative is not None else 'unresolved'}

            targets = []
            for key, obj in objects.items():
                if obj.get('isa') not in {'PBXNativeTarget', 'PBXAggregateTarget', 'PBXLegacyTarget'}:
                    continue
                phases = []
                for phase_id in obj.get('buildPhases', []):
                    phase = objects.get(phase_id, {})
                    entries = []
                    for build_file in phase.get('files', []):
                        file = objects.get(build_file, {})
                        entry = reference(file.get('fileRef', file.get('productRef', '')))
                        entry['build_file_id'] = build_file
                        entry['settings'] = file.get('settings', {})
                        entries.append(entry)
                    phases.append({'id': phase_id, 'kind': phase.get('isa'), 'files': entries})
                    if phase.get('isa') == 'PBXShellScriptBuildPhase':
                        issues.append({'code': 'build_script_not_executed', 'path': item['path'], 'target': obj.get('name')})
                configurations = []
                configuration_list = objects.get(obj.get('buildConfigurationList'), {})
                for config_id in configuration_list.get('buildConfigurations', []):
                    config = objects.get(config_id, {})
                    configurations.append({'name': config.get('name'), 'inline_settings': config.get('buildSettings', {}),
                        'base_config': reference(config['baseConfigurationReference']) if config.get('baseConfigurationReference') else None})
                targets.append({'id': key, 'name': obj.get('name'), 'product_type': obj.get('productType'),
                                'phases': phases, 'configurations': configurations,
                                'effective_settings': 'unresolved'})
                if obj.get('fileSystemSynchronizedGroups'):
                    issues.append({'code': 'synchronized_groups_need_xcode_resolution', 'path': item['path'], 'target': obj.get('name')})
            projects.append({'path': item['path'], 'sha256': item['sha256'], 'targets': targets,
                             'object_version': document.get('objectVersion')})
        except (MigrationError, UnicodeError, AttributeError, TypeError) as exc:
            issues.append({'code': 'project_parse_failed', 'path': item['path'], 'message': str(exc)})
    return {'projects': projects, 'effective_build': 'unresolved'}, issues


def dependency_inventory(root, files, *, manifest_evaluations=None):
    dependencies, issues = [], []
    evaluated = {item['path']: item for item in manifest_evaluations or []}
    consumed = []
    for item in files:
        path = root / item['path']
        try:
            if path.name == 'Package.resolved':
                value = read_json(path)
                for pin in value.get('pins', value.get('object', {}).get('pins', [])):
                    dependencies.append({'manager': 'SwiftPM', 'identity': pin.get('identity', pin.get('package')),
                        'location': pin.get('location', pin.get('repositoryURL')), 'state': pin.get('state', {}),
                        'source_path': item['path'], 'evidence': 'lockfile'})
            elif path.name == 'Podfile.lock':
                in_pods = False
                for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
                    if line == 'PODS:':
                        in_pods = True
                    elif line and not line.startswith(' '):
                        in_pods = False
                    if in_pods:
                        match = re.fullmatch(r'  - ([^ (]+) \(([^)]+)\):?', line)
                        if match:
                            dependencies.append({'manager': 'CocoaPods', 'identity': match[1], 'state': {'version': match[2]},
                                'source_path': item['path'], 'line': number, 'evidence': 'lockfile'})
                issues.append({'code': 'pod_dependency_edges_unresolved', 'path': item['path']})
            elif path.name == 'Cartfile.resolved':
                for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
                    match = re.fullmatch(r'(github|git|binary) "([^"]+)" "([^"]+)"', line.strip())
                    if match:
                        dependencies.append({'manager': 'Carthage', 'kind': match[1], 'location': match[2],
                                             'state': {'resolved': match[3]}, 'source_path': item['path'], 'line': number, 'evidence': 'lockfile'})
                    elif line.strip() and not line.strip().startswith('#'):
                        issues.append({'code': 'carthage_line_unresolved', 'path': item['path'], 'line': number})
            elif path.name in {'Package.swift', 'Podfile', 'Cartfile'}:
                evaluation = evaluated.get(item['path']) if path.name == 'Package.swift' else None
                if (evaluation is not None and evaluation.get('status') == 'manifest_evaluated'
                        and evaluation.get('manifest_sha256') == item['sha256']):
                    consumed.append(evaluation)
                else:
                    issues.append({'code': 'executable_manifest_not_evaluated', 'path': item['path']})
        except (MigrationError, UnicodeError, AttributeError, TypeError) as exc:
            issues.append({'code': 'dependency_parse_failed', 'path': item['path'], 'message': str(exc)})
    result = {'dependencies': dependencies, 'complete_graph': False}
    if consumed:
        result['manifest_evaluations'] = consumed
    return result, issues
