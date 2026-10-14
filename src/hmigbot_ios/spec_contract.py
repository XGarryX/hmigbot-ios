"""Read-only content/consumer contract checks over authoritative Markdown.

This gate detects structural and evidenced counterexamples, not full semantic
equivalence. It does not generate business assertions or mark model reviews PASS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .core import MigrationError, digest, read_json, safe_child
from .source_scope import import_token_lines, preview_lines
from .swiftui import tokenize

FEATURE_SECTIONS = ('范围', '数据流', '服务层', '实现映射', '状态管理', '对接点', '验收标准')
PAGE_SECTIONS = ('页面', '结构', '状态接口', '导航', '映射', '资源', '验收')
COMMON = ('feature-base.md', 'feature-index.md', 'ui-manifest.md', 'skip-list.md', 'source-coverage-report.md')
AC = re.compile(r'^- \[[ xX]\]\s+(F\d+-AC\d+)\s+(.+)$', re.M)
SYMBOL = re.compile(r'\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b')
DEFERRED = re.compile(r'其余\s*\d+\s*处.*(?:见|审阅)|\(详见.*\.md|对源赋值/运算的边界输入|按源modifier调用顺序检查')


def sections(text):
    """Return headings and bodies, without treating headings in code as sections."""
    lines, found, current, fenced = text.splitlines(), [], None, False
    for line in lines:
        if re.match(r'^\s*(```|~~~)', line):
            fenced = not fenced
        match = None if fenced else re.match(r'^#{1,6}\s+(.+?)\s*$', line)
        if match:
            current = [match[1], []]
            found.append(current)
        elif current is not None:
            current[1].append(line)
    return {heading: '\n'.join(body).strip() for heading, body in found}


def contract_refs(text):
    lines, refs, active, declared = text.splitlines(), [], False, False
    for line in lines:
        field = re.match(r'^contract_refs:\s*(.*?)\s*$', line)
        if field:
            if declared:
                raise MigrationError('Duplicate contract_refs field')
            declared = True
            active = True
            if field[1]:
                try:
                    inline = json.loads(field[1])
                except ValueError as exc:
                    raise MigrationError('Inline contract_refs must be a JSON string list, or use the multiline YAML form') from exc
                if not isinstance(inline, list) or any(not isinstance(ref, str) for ref in inline):
                    raise MigrationError('contract_refs must contain strings')
                refs.extend(inline)
                active = False
            continue
        if active:
            match = re.match(r'^\s+-\s+[\'\"]?([^\'\"]+?)[\'\"]?\s*$', line)
            if match:
                refs.append(match[1])
            elif line.strip():
                active = False
    return refs


def references(project, document, text):
    resolved = []
    for ref in contract_refs(text):
        relative, _, heading = ref.partition('#')
        target = safe_child(project, relative)
        if (not relative.startswith(('spec/baseline/', 'spec/ref/'))
                or relative.startswith('spec/baseline/plans/')
                or relative in {'spec/baseline/ui-manifest.md', 'spec/baseline/feature-index.md'}
                or target.suffix != '.md' or not target.is_file()):
            raise MigrationError('Contract reference must be an existing baseline/ref Markdown file: ' + ref)
        contents = target.read_text(encoding='utf-8-sig')
        if not heading or heading not in sections(contents):
            raise MigrationError('Contract reference needs an exact existing heading: ' + ref)
        resolved.append((target, heading, sections(contents)[heading]))
    return resolved


def dependency_inputs(project):
    """Freeze explicit shared contracts transitively, including references under ref/."""
    base = project / 'spec/baseline'
    pending = [base / name for name in COMMON]
    pending += list((base / 'features').glob('*.md')) + list((base / 'ui').glob('*.md'))
    pending.append(project / 'spec/decision-ledger.md')
    seen, hashes = set(), {}
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        hashes[path.relative_to(project).as_posix()] = digest(path.read_bytes())
        for target, _, _ in references(project, path, path.read_text(encoding='utf-8-sig')):
            pending.append(target)
    return hashes


def declared_symbols(parts):
    declared = set()
    for heading, body in parts.items():
        if not any(key in heading for key in ('服务层', '公共服务与状态', '目标接口', '公开接口', '实现映射', '状态管理', '状态接口')):
            continue
        indexes = None
        for line in body.splitlines():
            if not line.startswith('|'):
                if any(key in heading for key in ('状态管理', '接口', '服务层', '公共服务与状态')):
                    declared.update(SYMBOL.findall(line))
                continue
            # Only target columns define target symbols; source snippets cannot.
            cells = [c.strip() for c in line.strip('|').split('|')]
            if any('目标' in c for c in cells):
                indexes = [i for i, c in enumerate(cells) if '目标' in c]
            elif indexes is None:
                indexes = [1] if '实现映射' in heading else [0]
            for index in indexes:
                if index < len(cells):
                    declared.update(SYMBOL.findall(cells[index]))
    return declared


def check(project):
    from .native_pipeline import context, findings_module, source_paths
    source, project = context(Path(project))
    queue, findings, inputs, acceptance = findings_module(), [], {}, 0
    base = project / 'spec/baseline'
    graph_path = base / 'ios-facts.json'
    state_paths = {f['anchor']['path'] for f in read_json(graph_path).get('facts', []) if f.get('kind') == 'state'} if graph_path.is_file() else set()
    source_views = {}

    def fail(rule, subject, detail):
        findings.append(queue.make('IOS.SPEC_' + rule, 'spec', subject, detail))

    def read(path):
        if not path.is_file():
            fail('DOCUMENT_MISSING', path.relative_to(project).as_posix(), 'Required migration contract is missing')
            return ''
        inputs[path.relative_to(project).as_posix()] = digest(path.read_bytes())
        return path.read_text(encoding='utf-8-sig')

    for name in COMMON:
        contents = read(base / name)
        if contents and not any(line.strip() and not line.startswith('#') for line in contents.splitlines()):
            fail('COMMON_EMPTY', name, 'State the applicable contract or an evidenced not-applicable assessment')
    read(project / 'spec/decision-ledger.md')
    documents = [(p, 'feature') for p in sorted((base / 'features').glob('F*.md')) if not re.match(r'F\d+[-_].+\..+\.md$', p.name)]
    documents += [(p, 'page') for p in sorted((base / 'ui').glob('page_*.md'))]
    if not documents:
        fail('DOCUMENT_MISSING', 'baseline', 'No page or feature contracts exist')
    seen = set()
    for path, kind in documents:
        text = read(path)
        parts = sections(text)
        required = FEATURE_SECTIONS if kind == 'feature' else PAGE_SECTIONS
        for key in required:
            if not any(key in name and body for name, body in parts.items()):
                fail('SECTION_MISSING', path.name + ':' + key, 'Supply the behavior/target contract, a precise shared reference, or an evidenced not-applicable statement')
        if kind == 'feature':
            for field, allowed in {'complexity': {'simple', 'complex'}, 'tier': {'core', 'standard', 'peripheral'}, 'depth': {'full', 'stub'}}.items():
                match = re.search(r'^' + field + r':\s*(\w+)\s*$', text, re.M)
                if not match or match[1] not in allowed:
                    fail('METADATA', path.name + ':' + field, 'Declare a supported scheduling value: ' + '/'.join(sorted(allowed)))
        for heading, body in parts.items():
            if any(key in heading for key in ('服务层', '实现映射', '状态接口', '对接点')) and re.search(r'\bTBD\b|\bTODO\b|待确定|待计划阶段', body):
                fail('UNRESOLVED', path.name + ':' + heading, 'Resolve public target contracts before planning implementation; preserve unrelated unknowns separately')
        shared = {}
        pending, visited = [path], set()
        try:
            while pending:
                parent = pending.pop()
                if parent in visited:
                    continue
                visited.add(parent)
                for target, heading, body in references(project, parent, parent.read_text(encoding='utf-8-sig')):
                    inputs[target.relative_to(project).as_posix()] = digest(target.read_bytes())
                    shared[heading] = shared.get(heading, '') + '\n' + body
                    pending.append(target)
        except (MigrationError, OSError, UnicodeError) as exc:
            fail('REFERENCE_INVALID', path.name, str(exc))
        symbols = declared_symbols(parts) | declared_symbols(shared)
        if kind == 'page':
            state = next((body for name, body in parts.items() if '状态接口' in name), '')
            headers = []
            targets = []
            for row in state.splitlines():
                if not row.startswith('|'):
                    continue
                cells = [c.strip() for c in row.strip('|').split('|')]
                if any('目标' in c for c in cells):
                    headers = [i for i, c in enumerate(cells) if '目标' in c]
                elif headers and not all(re.fullmatch(r'[-: ]*', c) for c in cells):
                    targets.extend(cells[i] for i in headers if i < len(cells))
            if not headers or not targets or any(not SYMBOL.search(v) for v in targets):
                if set(source_paths(text)) & state_paths or not re.search(r'无状态|stateless', state, re.I):
                    fail('UI_TARGET_STATE', path.name, 'State table needs explicit target owner.symbol mapping, or a reviewed stateless contract')
            continue
        assertions = AC.findall(text)
        if not assertions:
            fail('AC_MISSING', path.name, 'The main feature must retain stable independently judgeable acceptance criteria')
        for ident, body in assertions:
            acceptance += 1
            if ident in seen:
                fail('AC_DUPLICATE', ident, 'Stable AC IDs must be globally unique')
            seen.add(ident)
            target = re.search(r'标:\s*([^`\s]+)', body)
            symbol = target[1].split('(', 1)[0].rstrip(',;') if target else ''
            if not symbol or symbol not in symbols:
                fail('TARGET_UNDEFINED', ident, 'Declare target owner.symbol in this feature or an explicitly referenced target contract: ' + symbol)
            expected = re.search(r'判:(?:static|unit|contract|route|ui|visual|device)\s*\|\s*([^`]+)', body)
            if not expected or not expected[1].strip() or re.match(r'真:', expected[1].strip()):
                fail('AC_EXPECTED', ident, 'Acceptance needs its own concrete expected result before the truth anchor')
            if DEFERRED.search(body):
                fail('AC_DEFERRED', ident, 'Expand concrete independently judgeable assertions; do not defer unspecified expressions')
            truth = re.search(r'真:src:([^`\s]+?):(\d+)(?:-\d+)?', body)
            if truth:
                try:
                    source_file = safe_child(source, truth[1])
                    if source_file not in source_views:
                        source_text = source_file.read_text(encoding='utf-8-sig')
                        source_views[source_file] = (source_text.splitlines(), preview_lines(source_text), import_token_lines(tokenize(source_text)))
                    source_lines, preview, imports = source_views[source_file]
                    line = int(truth[2])
                    if not 1 <= line <= len(source_lines):
                        raise MigrationError('Source truth line outside file')
                    if line in imports:
                        fail('TRUTH_IMPORT', ident, 'An import is a dependency locator, not evidence of a business operation')
                    if line in preview:
                        fail('TRUTH_PREVIEW', ident, 'Preview-only code cannot establish production behavior')
                except (MigrationError, OSError, UnicodeError) as exc:
                    fail('TRUTH_INVALID', ident, str(exc))
    report = {'schema_version': 1, 'status': 'FAIL' if findings else 'PASS',
              'scope': 'Markdown migration content and consumer contracts; not semantic or runtime equivalence',
              'behavior_verified': False, 'findings': findings, 'inputs': inputs,
              'counts': {'features': sum(k == 'feature' for _, k in documents),
                         'pages': sum(k == 'page' for _, k in documents), 'acceptance': acceptance}}
    return report, 2 if findings else 0
