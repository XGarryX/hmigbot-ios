"""Schema-driven scaffold from a reviewed source index to spec candidates.

This module breaks the F001 missing-prerequisite deadlock. ``native_authoring.prepare``
refuses to run while ``feature-index.md`` / ``ui-manifest.md`` reference documents that
do not yet exist ("Indexed authoring document is missing"). It also refuses documents
without real ``source_anchors``. The scaffold derives real candidate skeletons
(pages / components / bridges / extensions) straight from the reviewed source index
and facts, so ``prepare`` can discover them.

Classification is scoped to each declaration's OWN header tokens (comments and string
literals are skipped by the tokenizer), so a model struct in the same file as a View,
or ``: View`` / ``UIViewController`` appearing only in a comment or string, never
becomes a UI page.

Every artifact is explicitly unreviewed:

* ``candidate = True``, ``needs_review = True``
* ``spec_complete = False``, ``behavior_verified = False``
* ``enterable_plan = False``

so the spec/harness never mistakes a scaffold candidate for an enterable plan. Unknown
templates (a struct with no UI conformance/subclass/bridge) are listed in the candidate
JSON but are never written as pages and never entered into ``ui-manifest.md``.

The module only reads the source index and source files; it never changes the baseline,
source, findings or scheduler ledger. ``apply_scaffold`` never trusts the supplied
candidate: it re-derives the canonical candidate from the current reviewed source,
compares identity / content / source hash against the supplied one, and refuses any
foreign artifact, path escape, content/path change, stale index or duplicate FID.
"""
from __future__ import annotations

import re
from pathlib import Path

from .core import MigrationError, digest, json_bytes, read_json, safe_child, snapshot
from .native_pipeline import CODE, context
from .swiftui import tokenize

DECL_KEYWORDS = {'struct', 'class', 'enum', 'actor', 'extension'}
BRIDGE_SYMBOLS = ('UIViewRepresentable', 'UIViewControllerRepresentable', 'UIHostingController')
UIKIT_BASE = ('UIViewController', 'UINavigationController', 'UITableViewController',
              'UICollectionViewController', 'UIView')
SCAFFOLD_BANNER = (
    "脚手架候选（scaffold candidate）。非已验收规格：spec_complete=false，"
    "behavior_verified=false，needs_review=true。"
    "未经独立源码/内容审查与 source-check --harness 不得进入 plan。"
)
UNKNOWN_BANNER = (
    "未知模板(Unknown template)：未识别为 UI 页面，不列入可进入 plan 的页面，"
    "需审查者确认其 UI 语义后再决定是否成页。"
)


# --------------------------------------------------------------------------- #
# Source discovery (header-scoped, comment/string immune)
# --------------------------------------------------------------------------- #
def _header_values(tokens, start, end):
    """Non-string token values of a declaration header (keyword .. opening brace)."""
    return [t.value for t in tokens[start:end] if t.kind != 'string']


def _top_level_types(text):
    """Return ``(name, decl_kind, line, header_values)`` for each top-level type.

    Uses the token stack discipline from ``ios_facts``: a declaration only becomes a
    candidate when its opening brace lifts the depth 0 -> 1, so nested types are
    ignored. ``header_values`` carries only the declaration's own signature tokens,
    excluding comments and string literals.
    """
    tokens = tokenize(text)
    found, pending_owner, decl_kind, decl_start, depth = [], None, None, None, 0
    for i, tok in enumerate(tokens):
        v = tok.value
        if v in DECL_KEYWORDS and i + 1 < len(tokens) and tokens[i + 1].kind != 'string':
            name = None
            for nxt in tokens[i + 1:i + 4]:
                if nxt.kind == 'string' or nxt.value in {':', 'where'}:
                    break
                if re.match(r'^[A-Za-z_]\w*$', nxt.value):
                    name = nxt.value
                    break
            if name:
                pending_owner, decl_kind, decl_start = name, v, i
        if v == '{':
            depth += 1
            if pending_owner is not None and depth == 1:
                found.append((pending_owner, decl_kind, tok.line, _header_values(tokens, decl_start, i)))
            pending_owner = None
        elif v == '}':
            if depth > 0:
                depth -= 1
    return found


def _file_imports(text):
    """Token-based file-level import detection (comment/string immune)."""
    tokens = tokenize(text)
    swiftui = uikit = False
    for i, tok in enumerate(tokens):
        if tok.value == 'import' and i + 1 < len(tokens) and tokens[i + 1].kind != 'string':
            mod = tokens[i + 1].value
            if mod == 'SwiftUI':
                swiftui = True
            elif mod == 'UIKit':
                uikit = True
    return swiftui, uikit


def _has_conformance(header_values, name):
    """True only if ``name`` is an inherited type in THIS declaration's header.

    Conformances appear as ``: Name`` or ``, Name`` in the inheritance list, so the
    preceding token must be ``:`` or ``,``. Comments/strings are already excluded.
    """
    for i, v in enumerate(header_values):
        if v == name and i > 0 and header_values[i - 1] in (':', ','):
            return True
    return False


def classify_type(name, decl_kind, header_values, imports_swiftui, imports_uikit):
    """Classify a single declaration from its OWN header evidence.

    Returns ``(candidate_type, framework, confidence, is_ui, is_extension, is_bridge,
    unknown_template)``. A declaration with no UI conformance / UIKit subclass / bridge
    symbol is ``unknown`` even when the file imports SwiftUI/UIKit -- a model struct in
    a UI file stays ``unknown`` and is never turned into a page.
    """
    is_view = imports_swiftui and _has_conformance(header_values, 'View')
    subclass_uikit = any(_has_conformance(header_values, base) for base in UIKIT_BASE)
    is_bridge = any(symbol in header_values for symbol in BRIDGE_SYMBOLS)

    if decl_kind == 'extension':
        return ('extension', 'unknown', 'low', False, True, False, False)
    if is_bridge:
        framework = 'uikit' if (imports_uikit or subclass_uikit) else ('swiftui' if imports_swiftui else 'unknown')
        return ('bridge', framework, 'low', True, False, True, False)
    if subclass_uikit:
        return ('page', 'uikit', 'low', True, False, False, False)
    if is_view:
        screenish = bool(re.search(r'(Screen|Page|ViewController|Root|Main|Home|Detail|Scene|Flow)$', name))
        if screenish:
            return ('page', 'swiftui', 'low', True, False, False, False)
        return ('component', 'swiftui', 'low', True, False, False, False)
    return ('unknown', 'unknown', 'none', False, False, False, True)


def discover_candidates(source, index):
    """Discover candidate types from the reviewed source index, deterministically."""
    known = {f['path']: f for f in index.get('files', [])}
    candidates = []
    for path, meta in known.items():
        if Path(path).suffix.lower() not in CODE:
            continue
        file = safe_child(source, path)
        if not file.is_file():
            continue
        text = file.read_text(encoding='utf-8-sig')
        imports_swiftui, imports_uikit = _file_imports(text)
        for name, decl_kind, line, header in _top_level_types(text):
            (ctype, framework, confidence, is_ui, is_ext, is_bridge, unknown) = classify_type(
                name, decl_kind, header, imports_swiftui, imports_uikit)
            candidates.append({
                'name': name, 'decl_kind': decl_kind,
                'anchor': {'path': path, 'line': line, 'sha256': meta['sha256']},
                'candidate_type': ctype, 'framework': framework, 'confidence': confidence,
                'is_ui': is_ui, 'is_extension': is_ext, 'is_bridge': is_bridge, 'unknown_template': unknown,
            })
    # Stable ordering: same source -> same IDs. Source change detection is separate.
    candidates.sort(key=lambda c: (c['anchor']['path'], c['anchor']['line'], c['name']))
    return candidates


def assign_ids(candidates):
    """Assign stable page_/F IDs. Every UI candidate gets one feature (its behavior)."""
    page_n = feat_n = 0
    for c in candidates:
        if c['is_ui']:
            page_n += 1
            c['page_id'] = f'page_{page_n:04d}'
            feat_n += 1
            c['feature_id'] = f'F{feat_n:03d}'
        else:
            c['page_id'] = None
            c['feature_id'] = None
    return candidates


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #
def _yaml_block(anchor, candidate_type):
    return (
        "```yaml\n"
        "source_platform: ios\n"
        f"candidate_type: {candidate_type}\n"
        "scaffold: true\n"
        "needs_review: true\n"
        "spec_complete: false\n"
        "behavior_verified: false\n"
        "source_anchors:\n"
        f'  - path: "{anchor}"\n'
        "```\n"
    )


def render_feature_md(c):
    return (
        f"# {c['feature_id']}: {c['name']}\n\n"
        + _yaml_block(c['anchor']['path'], 'feature')
        + f"> {SCAFFOLD_BANNER}\n\n"
        "## 范围\n"
        f"涉及页面: {c['page_id'] or '待审查'}。由审查者填写功能范围与依赖。\n\n"
        "## 对接点\n"
        "待审查（scaffold 不推断业务行为/AC）。\n"
    )


def render_page_md(c):
    banner = SCAFFOLD_BANNER
    if c['unknown_template']:
        banner = banner + ' ' + UNKNOWN_BANNER
    return (
        f"# {c['page_id']}: {c['name']}\n\n"
        + _yaml_block(c['anchor']['path'], c['candidate_type'])
        + f"> {banner}\n\n"
        "## 溯源\n"
        f"- iOS {c['framework']} {c['decl_kind']}: {c['name']}\n"
        f"- 源码布局: {c['anchor']['path']} (line {c['anchor']['line']})\n"
        "- 输出文件: 待审查（未生成 ArkTS 路径）\n\n"
        "## 页面结构\n"
        "待审查（scaffold 不推断布局/业务行为）。\n\n"
        "## 状态接口\n"
        "待审查。\n\n"
        "## 导航关系\n"
        "待审查。\n"
    )


def render_feature_index(candidates):
    rows = []
    for c in candidates:
        if c.get('feature_id'):
            rows.append(f"| {c['feature_id']} | {c['name']} | feature | {c['page_id']} | pending |")
    table = "\n".join(rows)
    return (
        "# Feature Index\n\n"
        "source_platform: ios。脚手架候选索引，由 native_scaffold 从已审查源码索引派生；非已验收规格，待独立审查。\n\n"
        "## 功能清单\n"
        "| ID | 功能 | 候选类型 | 涉及页面 | 状态 |\n"
        "|----|------|---------|---------|------|\n"
        f"{table}\n"
    )


def render_ui_manifest(candidates):
    rows = []
    for c in candidates:
        if c['is_ui']:
            rows.append(f"| {c['page_id']} | {c['name']} | 待审查 | {c['candidate_type']} | {c['confidence']} | pending |")
    table = "\n".join(rows)
    return (
        "# UI Manifest\n\n"
        "source_platform: ios。脚手架候选清单，由 native_scaffold 派生；非已验收规格。"
        "未知模板(Unknown)不列入，避免被误当可进入 plan 的页面。\n\n"
        "## 页面清单\n"
        "| page_id | iOS | ArkTS 产出 | 候选类型 | confidence | 状态 |\n"
        "|---------|---------|-----------|---------|-----------|------|\n"
        f"{table}\n\n"
        "### 页面状态生命周期\n"
        "pending -> converted -> verified。只有实际执行和验收后才能更新状态。\n"
    )


def build_files(candidates):
    """Map output-relative paths to rendered content for every derived artifact."""
    files = {}
    for c in candidates:
        if c.get('feature_id'):
            path = f"spec/baseline/features/{c['feature_id']}-{c['name']}.md"
            files[path] = {'kind': 'feature', 'content': render_feature_md(c), 'candidate_id': c['feature_id']}
        if c['is_ui']:
            path = f"spec/baseline/ui/{c['page_id']}_{c['name']}.md"
            files[path] = {'kind': 'page', 'content': render_page_md(c), 'candidate_id': c['page_id']}
    files['spec/baseline/feature-index.md'] = {'kind': 'index', 'content': render_feature_index(candidates)}
    files['spec/baseline/ui-manifest.md'] = {'kind': 'manifest', 'content': render_ui_manifest(candidates)}
    return files


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def scaffold(project, *, source_sha256=None):
    """Build the canonical derived scaffold candidate for a reviewed project.

    Does not write any file. Raises ``MigrationError`` if the source index is missing,
    the source changed since the index, or no UI surface candidate was discovered
    (we never fabricate a feature/page to fill the gap).
    """
    source, project = context(project)
    index_path = project / 'spec/baseline/ios-source-index.json'
    if not index_path.is_file():
        raise MigrationError('Source index missing: run source-index/refresh and review before scaffolding')
    index = read_json(index_path)
    current = snapshot(source)
    source_change = index.get('source_sha256') != current['sha256']
    if source_change:
        raise MigrationError('Source changed since index; re-review the source baseline before scaffolding')
    if source_sha256 is not None and source_sha256 != current['sha256']:
        raise MigrationError('Provided source_sha256 does not match current source')

    candidates = assign_ids(discover_candidates(source, index))
    if not any(c['is_ui'] for c in candidates):
        raise MigrationError('Scaffold found no UI surface candidate; author features/pages manually '
                             'rather than fabricating them')
    files = build_files(candidates)

    ui = [c for c in candidates if c['is_ui']]
    summary = {
        'total_candidates': len(candidates),
        'pages': len(ui),
        'features': len([c for c in candidates if c.get('feature_id')]),
        'components': len([c for c in candidates if c['candidate_type'] == 'component']),
        'bridges': len([c for c in candidates if c['is_bridge']]),
        'extensions': len([c for c in candidates if c['is_extension']]),
        'unknown_templates': len([c for c in candidates if c['unknown_template']]),
    }
    candidate_list = [{
        'id': c.get('feature_id') or c.get('page_id') or c['name'],
        'name': c['name'], 'decl_kind': c['decl_kind'],
        'candidate_type': c['candidate_type'], 'framework': c['framework'],
        'confidence': c['confidence'], 'is_ui': c['is_ui'],
        'is_extension': c['is_extension'], 'is_bridge': c['is_bridge'],
        'unknown_template': c['unknown_template'], 'page_id': c.get('page_id'),
        'feature_id': c.get('feature_id'), 'anchor': c['anchor'],
        'stable_key': digest(json_bytes([c['decl_kind'], c['name'], c['anchor']['path'], c['anchor']['line']]))[:16],
        'enterable_plan': False,
    } for c in candidates]

    return {
        'schema_version': 1, 'kind': 'spec-scaffold-candidate',
        'scaffold_schema': 'schemas/spec-scaffold.schema.json',
        'source_platform': 'ios', 'source_sha256': current['sha256'],
        'candidate': True, 'needs_review': True, 'spec_complete': False, 'behavior_verified': False,
        'enterable_plan': False, 'source_change_detected': source_change,
        'summary': summary, 'candidates': candidate_list,
        'files': {path: {'kind': meta['kind'], 'candidate_id': meta.get('candidate_id')} for path, meta in files.items()},
        'file_contents': {path: meta['content'] for path, meta in files.items()},
        'inventory_diff': {
            'new_pages': [c['page_id'] for c in ui],
            'new_features': [c['feature_id'] for c in candidates if c.get('feature_id')],
            'unknown_templates': [c['name'] for c in candidates if c['unknown_template']],
            'extensions': [c['name'] for c in candidates if c['is_extension']],
        },
    }


# --------------------------------------------------------------------------- #
# Apply: re-derive and verify before writing anything
# --------------------------------------------------------------------------- #
_ALLOWED_INDEX = re.compile(r'^spec/baseline/(?:feature-index\.md|ui-manifest\.md)$')
_ALLOWED_FEATURE = re.compile(r'^spec/baseline/features/F\d{3}-.+\.md$')
_ALLOWED_PAGE = re.compile(r'^spec/baseline/ui/page_\d{4}_.+\.md$')


def _allowed_path(path):
    return bool(_ALLOWED_INDEX.match(path) or _ALLOWED_FEATURE.match(path) or _ALLOWED_PAGE.match(path))


def _fid_conflict(base, path):
    """Return the occupied ID if a different main document already owns it."""
    target = Path(path)
    if _ALLOWED_FEATURE.match(path):
        fid = target.stem.split('-', 1)[0]
        for existing in (base / 'features').glob(f'{fid}-*.md'):
            if existing.name != target.name:
                return fid
    elif _ALLOWED_PAGE.match(path):
        pid = target.stem.split('_', 1)[0]
        for existing in (base / 'ui').glob(f'{pid}_*.md'):
            if existing.name != target.name:
                return pid
    return None


def apply_scaffold(project, candidate):
    """Materialize only missing scaffold files, never trusting the supplied candidate.

    Security / integrity contract (per in-scope review):

    * The supplied ``candidate`` is verified, never executed. The canonical candidate
      is re-derived from the current reviewed source and compared against it.
    * Any path outside the four allowed scaffold outputs (e.g. ``ios-semantics.json``
      or other pseudo-approved artifacts) is rejected outright.
    * Identity (``stable_key`` set), source hash and file content must match the
      re-derived candidate exactly; a drift, hand-inserted baseline, stale index or
      tampered content is refused.
    * All paths and conflicts (duplicate FID / page_id owned by a different main
      document) are pre-checked before any file is written, so apply is all-or-nothing.
    * Existing documents are never overwritten; only same-content idempotent fills are
      permitted.
    """
    source, project = context(project)
    if not isinstance(candidate, dict) or candidate.get('kind') != 'spec-scaffold-candidate':
        raise MigrationError('apply requires a spec-scaffold-candidate produced by native_scaffold.scaffold')
    # 1. reject foreign / pseudo-approved artifacts up front
    for path in candidate.get('file_contents', {}):
        if not _allowed_path(path):
            raise MigrationError('Candidate carries non-scaffold artifact (possible pseudo-approved baseline): ' + path)
    # 2. re-derive canonical candidate from current reviewed source
    rederived = scaffold(project)
    # 3. consistency: supplied candidate must match the derived identity/hash/content
    if candidate.get('source_sha256') != rederived['source_sha256']:
        raise MigrationError('Provided candidate source_sha256 does not match currently derived source')
    if {c['stable_key'] for c in candidate.get('candidates', [])} != {c['stable_key'] for c in rederived['candidates']}:
        raise MigrationError('Candidate identity drift vs derived source candidates; refuse apply')
    expected = rederived['file_contents']
    provided = candidate.get('file_contents', {})
    if set(provided.keys()) != set(expected.keys()):
        raise MigrationError('Candidate file set differs from derived source files; refuse apply')
    for path, content in expected.items():
        if provided.get(path) != content:
            raise MigrationError('Candidate content differs from derived source content: ' + path)
    # 4. pre-check every path / conflict, then write only missing (idempotent)
    baseline = (project / 'spec/baseline').resolve()
    plan, skipped = [], []
    for path, content in expected.items():
        target = safe_child(project, path)
        if not target.is_relative_to(baseline):
            raise MigrationError('Scaffold path escapes spec/baseline: ' + path)
        if target.exists():
            if target.read_text(encoding='utf-8-sig') != content:
                raise MigrationError('Existing document conflicts with candidate (would overwrite): ' + path)
            skipped.append(path)
            continue
        fid = _fid_conflict(baseline, path)
        if fid is not None:
            raise MigrationError('Conflicting main document for ' + fid + '; refuse to create duplicate ID')
        plan.append((target, content))
    created = []
    for target, content in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        created.append(target.relative_to(project).as_posix())
    return {'created': sorted(created), 'skipped': sorted(skipped), 'refused': [],
            'spec_complete': False, 'behavior_verified': False}
