"""Value identity reads do not erase independent view identity obligations."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_ios_task_priority import extract_case
from hmigbot_ios import ios_facts
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, write_json


MIXED = '''struct Screen {
    func render() {
        ForEach(rows, id: \\.id) { value in Text(value.id) }.id(value.id)
        let same = left.id == right?.id
        api.id(value.id)
    }
}
'''


def identities(graph):
    return [fact for fact in graph['facts'] if fact['kind'] == 'identity']


def identity_obligations(graph):
    return [item for item in ios_facts.obligations(graph)['obligations'] if item['kind'] == 'identity']


class IdentityJudgmentTests(unittest.TestCase):
    def test_model_lookup_comparison_optional_chain_and_keypath_accept_logic_oracles(self):
        graph, _ = extract_case('''struct Catalog {
    func find(_ id: String) -> Item? { items.first { $0.id == id } }
    func same() -> Bool { left.id == right?.id }
    func differs() -> Bool { left.id != right.id }
    func keys() { let key = \\Item.id; let id = item?.id; let forced = item!.id }
}
''')
        self.assertEqual(len(identities(graph)), 8)
        self.assertTrue(all(f['value']['identity_usage'] == 'member_read' for f in identities(graph)))
        self.assertTrue(all(o['judgments'] == ['unit', 'contract', 'ui'] for o in identity_obligations(graph)))
        self.assertTrue(all(f['resolution'] == 'token_signal' for f in identities(graph)))

    def test_same_line_reads_calls_and_foreach_keep_separate_oracles(self):
        graph, _ = extract_case(MIXED)
        facts, obs = identities(graph), identity_obligations(graph)
        self.assertEqual([f['value']['identity_usage'] for f in facts],
                         ['for_each', 'member_read', 'member_read', 'member_call', 'member_read',
                          'member_read', 'member_read', 'member_call', 'member_read'])
        self.assertEqual(len({f['value']['token_index'] for f in facts}), 9)
        self.assertEqual([o['judgments'] for o in obs],
                         [['ui'] if f['value']['identity_usage'] != 'member_read' else ['unit', 'contract', 'ui']
                          for f in facts])
        self.assertEqual([f['symbol'] for f, o in zip(facts, obs) if o['judgments'] == ['ui']],
                         ['ForEach', 'id', 'id'])

    def test_unknown_callees_optional_calls_and_ambiguous_forms_stay_ui(self):
        graph, _ = extract_case('''func unknown() {
    api.id(value)
    api?.id(value)
    callback.id?(value)
    callback.id!(value)
    api.id<Int>(value)
    api.id { value }
    item.id = value
    item.id += value
}
''')
        self.assertEqual(len(identities(graph)), 8)
        self.assertTrue(all(o['judgments'] == ['ui'] for o in identity_obligations(graph)))

    def test_missing_legacy_and_unknown_metadata_keep_default(self):
        graph, _ = extract_case('let result = item.id')
        fact = identities(graph)[0]
        for metadata in ({'tokens': ''}, {'tokens': '', 'identity_usage': 'unknown'},
                         {'tokens': '', 'identity_usage': 'future_usage'}):
            with self.subTest(metadata=metadata):
                fact['value'] = metadata
                self.assertEqual(identity_obligations(graph)[0]['judgments'], ['ui'])

    def test_forged_usage_and_token_location_are_rejected_by_source_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, project = root / 'source', root / 'project'
            source.mkdir()
            (source / 'Sample.swift').write_text('api.id(value.id)', encoding='utf-8')
            for field, value in [('identity_usage', 'member_read'), ('token_index', 999)]:
                with self.subTest(field=field):
                    ios_facts.refresh(project, source)
                    path = project / 'spec/baseline/ios-facts.json'
                    graph = read_json(path)
                    identities(graph)[0]['value'][field] = value
                    write_json(path, graph)
                    write_json(project / 'spec/baseline/ios-obligations.json', ios_facts.obligations(graph))
                    with self.assertRaisesRegex(MigrationError, 'stale or edited'):
                        ios_facts.validate_graph(source, project)
            ios_facts.refresh(project, source)
            ios_facts.validate_graph(source, project)

    def test_context_selector_and_judgments_are_in_rules_digest(self):
        graph, obs = extract_case('let result = item.id')
        self.assertEqual(obs['rules_sha256'], digest(json_bytes(ios_facts.RULESET)))
        self.assertNotEqual(obs['rules_sha256'], digest(json_bytes(ios_facts.RULES)))
        for change in ('selector', 'rule'):
            ruleset = copy.deepcopy(ios_facts.RULESET)
            if change == 'selector':
                ruleset['context_rules'][0]['selector']['value']['identity_usage'] = 'unknown'
            else:
                ruleset['context_rules'][0]['rule']['judgments'] = ['ui']
            with mock.patch.object(ios_facts, 'RULESET', ruleset):
                updated = ios_facts.obligations(graph)
            self.assertNotEqual(updated['rules_sha256'], obs['rules_sha256'])
            self.assertEqual(next(o for o in updated['obligations'] if o['kind'] == 'identity')['judgments'], ['ui'])

    def test_neutral_fixture_fact_ids_and_count_match_pre_metadata_baseline(self):
        # Captured from origin/main before adding identity usage metadata.
        graph, _ = extract_case(MIXED)
        self.assertEqual(len(graph['facts']), 12)
        self.assertEqual([f['id'] for f in graph['facts']], [
            'IF-2a63e75dd8f980b0', 'IF-5398869ee91733b9', 'IF-f6e848627b32bf2b',
            'IF-73cc181e6ee87367', 'IF-f4cc20b39db5c63d', 'IF-d42a2391ddff0116',
            'IF-bd9b1f12958eb2ee', 'IF-63ece37827fb3031', 'IF-6dfab83d5a656185',
            'IF-3189e0283cac0a55', 'IF-3274f24edee53a48', 'IF-738bb1ef50521c97'])


if __name__ == '__main__':
    unittest.main()
