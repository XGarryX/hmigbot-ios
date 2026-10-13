"""Source-review and MCP failure boundaries, with a real local protocol subprocess."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json
from hmigbot_ios.expertise import audit, make_plan, prepare, record
from hmigbot_ios.ios_harness import check
from hmigbot_ios.source_mcp import capture, validate_captures
from test_ios_harness import fixture

SERVER = '''import json,sys,time
mode=sys.argv[1]
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 method=m['method']
 if method=='initialize':
  result={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'test-only-source-server','version':'1'}}
 elif method=='tools/list':
  result={'tools':[{'name':'find_symbol','inputSchema':{'type':'object','required':['name_path_pattern']},'annotations':{'readOnlyHint':mode!='mutating'}}]}
 elif method=='tools/call':
  if mode=='timeout': time.sleep(2)
  if mode=='invalid': print('not-json',flush=True); continue
  if mode=='rpc-error': print(json.dumps({'jsonrpc':'2.0','id':m['id'],'error':{'code':-32603,'message':'index unavailable'}}),flush=True); continue
  result={'content':[{'type':'text','text':'Counter owns count at Counter.swift:3'}],'isError':mode=='error'}
 else: result={}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':result}),flush=True)
'''


class ExpertiseMCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ios expertise protocol ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.project, self.graph = fixture(self.root)
        self.server = self.root / 'test_server.py'; self.server.write_text(SERVER)
        self.server_config = self.root / 'server.json'
        self.request = self.root / 'request.json'
        self.ids = [next(f['id'] for f in self.graph['facts'] if f['kind'] == 'state')]
        write_json(self.request, {'source_sha256': self.graph['source_sha256'], 'graph_sha256': digest(json_bytes(self.graph)),
                                 'fact_ids': self.ids, 'tool': 'find_symbol', 'arguments': {'name_path_pattern': 'Counter'}})
        self.config()

    def config(self, mode='success', timeout=5):
        write_json(self.server_config, {'provider': 'serena', 'transport': 'stdio',
                                        'command': [sys.executable, str(self.server), mode], 'timeout_seconds': timeout})

    def test_pinned_pack_integrity_and_framework_routing(self):
        manifest, files = audit()
        self.assertEqual(len(manifest['packs']), 3)
        self.assertGreater(len(files), 50)
        plan = make_plan(self.source, self.graph)
        self.assertEqual([r['pack'] for r in plan['reviews']], ['swiftui'])
        (self.source / 'Service.swift').write_text('import UIKit\nclass Service: UIViewController { func load() async { await Task.yield() } }')
        from hmigbot_ios.ios_facts import extract
        packs = {r['pack'] for r in make_plan(self.source, extract(self.source))['reviews']}
        self.assertEqual(packs, {'swiftui', 'uikit', 'concurrency'})

    def test_missing_review_blocks_source_gate(self):
        (self.project / 'spec/ref/ios-expertise-reviews.json').unlink()
        report, code = check(self.project)
        self.assertNotEqual(code, 0)
        self.assertTrue(any('ios-expertise-reviews' in f['detail'] for f in report['findings']))

    def test_legacy_or_disabled_review_cannot_bypass_source_gate(self):
        path = self.project / '.migbot/config.json'
        config = read_json(path)
        for setting in (None, {'version': 1, 'required': False}):
            with self.subTest(setting=setting):
                config.pop('ios_expertise', None)
                if setting is not None:
                    config['ios_expertise'] = setting
                write_json(path, config)
                report, code = check(self.project)
                self.assertNotEqual(code, 0)
                self.assertTrue(any('adopt before continuing legacy plans' in f['detail'] for f in report['findings']))
        prepare(self.project)
        report, code = check(self.project)
        self.assertEqual(code, 0, report)

    def test_serena_cache_does_not_invalidate_source_but_app_edit_does(self):
        from hmigbot_ios.core import snapshot
        cache = self.source / '.serena/cache'
        cache.mkdir(parents=True)
        (cache / 'symbols.json').write_text('{"index": "generated"}')
        self.assertEqual(snapshot(self.source)['sha256'], self.graph['source_sha256'])
        result = capture(self.project, self.server_config, self.request)
        validate_captures(self.project, self.graph, [result['id']], self.ids)
        app = self.source / 'Counter.swift'
        app.write_text(app.read_text() + '\n// actual source revision\n')
        with self.assertRaises(MigrationError):
            capture(self.project, self.server_config, self.request)

    def test_foreign_line_and_missing_resource_cannot_record_review(self):
        path = self.project / 'spec/ref/ios-expertise-reviews.json'
        original = path.read_bytes()
        data = read_json(path); data['reviews'][0]['observations'][0]['source']['line'] = 99999
        write_json(self.root / 'bad.json', data)
        with self.assertRaises(MigrationError): record(self.project, self.root / 'bad.json')
        self.assertEqual(path.read_bytes(), original)
        data = read_json(path); data['reviews'][0]['resources'].pop()
        write_json(self.root / 'bad.json', data)
        with self.assertRaises(MigrationError): record(self.project, self.root / 'bad.json')

    def test_skill_hash_change_blocks_adoption(self):
        from unittest.mock import patch
        import shutil
        import hmigbot_ios.expertise as module
        copy = self.root / 'bundle'; shutil.copytree(module.BUNDLE, copy)
        (copy / 'swiftui/skills/swiftui-expert-skill/SKILL.md').write_text('changed instructions')
        with patch.object(module, 'BUNDLE', copy):
            with self.assertRaises(MigrationError): prepare(self.project)

    def test_comment_cannot_enable_a_framework(self):
        (self.source / 'Plain.swift').write_text('// import UIKit actor await\nlet description = "UIViewController Task"\n')
        from hmigbot_ios.ios_facts import extract
        packs = {r['pack'] for r in make_plan(self.source, extract(self.source))['reviews']}
        self.assertEqual(packs, {'swiftui'})

    def test_actual_stdio_capture_is_linkable_but_not_behavior_proof(self):
        result = capture(self.project, self.server_config, self.request)
        self.assertEqual(result['resolution'], 'tool_response')
        self.assertFalse(result['behavior_verified'])
        validate_captures(self.project, self.graph, [result['id']], self.ids)
        semantics = self.project / 'spec/baseline/ios-semantics.json'
        data = read_json(semantics)
        data['documents'][1]['facts']['state_ownership']['tool_evidence_ids'] = [result['id']]
        write_json(semantics, data)
        report, code = check(self.project)
        self.assertEqual(code, 0, report)
        self.assertFalse(report['behavior_verified'])

    def test_edited_and_unrelated_capture_are_rejected(self):
        result = capture(self.project, self.server_config, self.request)
        with self.assertRaises(MigrationError): validate_captures(self.project, self.graph, [result['id']], ['unrelated'])
        path = Path(result['path']) / 'artifact.json'
        data = read_json(path); data['response']['content'][0]['text'] = 'invented result'; write_json(path, data)
        with self.assertRaises(MigrationError): validate_captures(self.project, self.graph, [result['id']])

    def test_unknown_capture_and_stale_query_are_rejected(self):
        result = capture(self.project, self.server_config, self.request)
        with self.assertRaises(MigrationError): validate_captures(self.project, self.graph, ['MCP-invented'])
        graph = {**self.graph, 'source_sha256': '0' * 64}
        with self.assertRaises(MigrationError): validate_captures(self.project, graph, [result['id']])
        request = read_json(self.request); request['source_sha256'] = '0' * 64; write_json(self.request, request)
        with self.assertRaises(MigrationError): capture(self.project, self.server_config, self.request)

    def test_mutating_tool_and_invalid_protocol_never_create_success(self):
        for mode in ('mutating', 'invalid', 'rpc-error', 'error', 'timeout'):
            with self.subTest(mode=mode):
                self.config(mode, timeout=0.3 if mode == 'timeout' else 5)
                with self.assertRaises(MigrationError): capture(self.project, self.server_config, self.request)
        self.assertFalse((self.project / 'spec/ref/ios-mcp-index.json').exists())
        self.assertEqual(len(list((self.project / 'spec/ref/mcp-runs').glob('*/failure.json'))), 5)

    def test_unlisted_tool_cannot_be_called(self):
        data = read_json(self.request); data['tool'] = 'replace_symbol_body'; write_json(self.request, data)
        with self.assertRaises(MigrationError): capture(self.project, self.server_config, self.request)
        self.assertFalse((self.project / 'spec/ref/mcp-runs').exists())


if __name__ == '__main__':
    unittest.main()
