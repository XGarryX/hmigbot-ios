"""Integrity replay from captured compiler bytes; no Xcode or application conversion."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios import source_build_membership as membership
from hmigbot_ios.core import MigrationError, digest, json_bytes, snapshot
from hmigbot_ios.evidence import pack
from test_source_build_membership import MembershipBase


class MembershipEvidenceValidationTests(MembershipBase):
    def setUp(self):
        super().setUp()
        self.standard_build()
        self.document = self.collect()

    def check(self, document=None):
        return membership.validate(self.source, self.document if document is None else document, capture=self.capture)

    def reseal_log(self, document, text):
        record = document['evidence']['captured_build_log']
        raw = text.encode('utf-8')
        (self.capture / record['artifact']).write_bytes(raw)
        parsed = membership.parse_compile_invocations(text)
        record.update(sha256=digest(raw), bytes=len(raw), ambiguous_lines=len(parsed['ambiguous']))
        for key, origin in (('swift_entries', membership.ORIGIN_BUILD_LOG_SWIFT),
                            ('clang_entries', membership.ORIGIN_BUILD_LOG_CLANG),
                            ('other_entries', membership.ORIGIN_BUILD_LOG_OTHER)):
            record[key] = sum(item['origin'] == origin for item in parsed['entries'])
        (self.capture / 'compile-invocations.json').write_bytes(json_bytes({
            'schema_version': 1, 'kind': 'source_build_compile_invocations',
            'captured_build_log': record, 'entries': parsed['entries'],
            'ambiguous': parsed['ambiguous'][:20], 'ambiguous_total': len(parsed['ambiguous'])}))

    def test_collect_and_packed_raw_evidence_both_replay(self):
        self.assertTrue(self.check()['integrity_passed'])
        bundle = self.root / 'bundle'
        pack(self.source, self.capture, bundle, 'source_build', 'synthetic compiler')
        checked = membership.validate(self.source, self.document, capture=bundle / 'artifacts')
        self.assertTrue(checked['integrity_passed'])
        self.assertEqual(checked['build_authenticity'], 'not_verified')
        self.assertEqual(checked['behavior_equivalence'], 'not_verified')

    def test_real_relocation_replays_original_paths_without_opening_old_source(self):
        bundle = self.root / 'relocated-bundle'
        pack(self.source, self.capture, bundle, 'source_build', 'synthetic compiler')
        original = self.source
        relocated = self.root / 'different-checkout'
        self.source.rename(relocated)
        self.assertFalse(original.exists())
        self.assertEqual(snapshot(relocated)['sha256'], self.document['source_sha256'])
        checked = membership.validate(relocated, self.document, capture=bundle / 'artifacts')
        self.assertTrue(checked['integrity_passed'])
        self.assertEqual(checked['source_files'], self.document['source_files'])

    def test_mac_style_capture_prefixes_map_exactly_to_current_windows_fixture(self):
        document = deepcopy(self.document)
        old_root = self.source.as_posix()
        captured_root = '/Users/builder/NativeApp'
        for item in document['evidence']['sources']:
            path = self.capture / item['artifact']
            entries = membership.parse_file_list(path.read_bytes())
            raw = ('\n'.join(entry.replace(old_root + '/', captured_root + '/') for entry in entries) + '\n').encode()
            path.write_bytes(raw)
            item.update(sha256=digest(raw), bytes=len(raw))
        log = self.capture / document['evidence']['captured_build_log']['artifact']
        text = log.read_text().replace(str(self.source), captured_root).replace(old_root, captured_root)
        self.reseal_log(document, text)
        document['capture_roots'] = {'source': captured_root, 'derived_data': '/Users/builder/DerivedData'}
        self.assertTrue(self.check(document)['integrity_passed'])

    def test_old_v1_without_roots_only_replays_at_original_root(self):
        legacy = deepcopy(self.document)
        del legacy['capture_roots']
        self.assertTrue(self.check(legacy)['integrity_passed'])
        original = self.source
        relocated = self.root / 'relocated-legacy'
        original.rename(relocated)
        with self.assertRaisesRegex(MigrationError, 'lack raw compiler evidence'):
            membership.validate(relocated, legacy, capture=self.capture)

    def test_wrong_or_missing_capture_source_root_cannot_replay_after_relocation(self):
        relocated = self.root / 'moved-source'
        self.source.rename(relocated)
        for change in ('wrong', 'absent', 'missing-key'):
            with self.subTest(change=change):
                document = deepcopy(self.document)
                if change == 'wrong':
                    document['capture_roots']['source'] += '/wrong-root'
                elif change == 'absent':
                    del document['capture_roots']
                else:
                    del document['capture_roots']['source']
                with self.assertRaises(MigrationError):
                    membership.validate(relocated, document, capture=self.capture)

    def test_traversal_relative_or_malformed_capture_roots_are_rejected(self):
        for value in ('relative/source', '/capture/../source', 'D:/capture/../source', '/capture/./source',
                      '/capture//source', 'D:\\capture\\source', 1, None):
            with self.subTest(value=value):
                document = deepcopy(self.document)
                document['capture_roots']['source'] = value
                with self.assertRaisesRegex(MigrationError, 'Capture root'):
                    self.check(document)

    def test_relocated_source_still_requires_exact_snapshot_and_member_hashes(self):
        relocated = self.root / 'changed-checkout'
        self.source.rename(relocated)
        (relocated / 'App/App.swift').write_text('struct Changed {}\n')
        with self.assertRaisesRegex(MigrationError, 'fingerprint is stale'):
            membership.validate(relocated, self.document, capture=self.capture)

    def test_wrong_derived_root_cannot_relabel_a_captured_generated_input(self):
        generated = self.write(self.derived / 'DerivedSources/Generated.swift', 'struct Generated {}\n')
        self.file_list('App', 'arm64', self.paths('App/App.swift') + [str(generated)])
        document = self.collect()
        self.assertTrue(self.check(document)['integrity_passed'])
        document['capture_roots']['derived_data'] += '-wrong'
        with self.assertRaisesRegex(MigrationError, 'Excluded input metadata disagrees'):
            self.check(document)

    def test_complete_requires_raw_capture_but_incomplete_structure_can_be_checked(self):
        with self.assertRaisesRegex(MigrationError, 'requires captured raw'):
            membership.validate(self.source, self.document)
        self.file_list('App', 'arm64', self.paths('App/App.swift', 'App/Gone.swift'))
        incomplete = self.collect()
        self.assertEqual(incomplete['membership_status'], 'incomplete')
        self.assertEqual(membership.validate(self.source, incomplete)['membership_status'], 'incomplete')
        self.assertEqual(self.check(incomplete)['membership_status'], 'incomplete')

    def test_erased_evidence_cannot_support_retained_members(self):
        document = deepcopy(self.document)
        document['evidence']['sources'] = []
        document['evidence']['captured_build_log'] = None
        (self.capture / 'compile-invocations.json').unlink()
        with self.assertRaisesRegex(MigrationError, 'lack raw compiler evidence'):
            self.check(document)

    def test_extra_member_with_valid_source_hash_still_requires_raw_input(self):
        document = deepcopy(self.document)
        entry = next(item for item in snapshot(self.source)['files'] if item['path'] == 'App/Unused.swift')
        document['members'].append({**entry, 'kind': 'swift_source', 'analysis': 'compiled_input',
                                    'origins': ['swift_file_list'], 'targets': ['App'], 'architectures': ['arm64']})
        document['members'].sort(key=lambda item: item['path'])
        document['source_files'] = [item['path'] for item in document['members']]
        document['counts']['source_files'] += 1
        with self.assertRaisesRegex(MigrationError, 'lack raw compiler evidence'):
            self.check(document)

    def test_resealed_log_without_the_claimed_clang_member_is_rejected(self):
        document = deepcopy(self.document)
        log = self.capture / document['evidence']['captured_build_log']['artifact']
        self.reseal_log(document, '\n'.join(line for line in log.read_text().splitlines()
                                            if not line.startswith('CompileC')) + '\n')
        with self.assertRaisesRegex(MigrationError, 'lack raw compiler evidence'):
            self.check(document)

    def test_resealed_log_cannot_silently_add_an_unlisted_input(self):
        document = deepcopy(self.document)
        log = self.capture / document['evidence']['captured_build_log']['artifact']
        self.reseal_log(document, log.read_text() + 'SwiftCompile normal arm64 '
                        + str(self.source / 'App/Unused.swift') + " (in target 'App' from project 'App')\n")
        with self.assertRaisesRegex(MigrationError, 'omit captured source inputs'):
            self.check(document)

    def test_raw_ambiguous_lines_cannot_be_hidden_under_complete(self):
        document = deepcopy(self.document)
        log = self.capture / document['evidence']['captured_build_log']['artifact']
        self.reseal_log(document, log.read_text() + 'CompileC /dd/Broken.o relative.m normal arm64\n')
        with self.assertRaisesRegex(MigrationError, 'unreported unresolved.*ambiguous_compile_invocation'):
            self.check(document)

    def test_member_metadata_must_match_the_raw_evidence(self):
        for field, value in (('origins', ['swift_file_list']), ('targets', ['Widget']),
                             ('architectures', ['arm64']), ('kind', 'other_compiler_input')):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                member = next(item for item in document['members'] if item['path'] == 'App/App.swift')
                member[field] = value
                with self.assertRaises(MigrationError):
                    self.check(document)

    def test_global_counts_architectures_and_selection_are_checked(self):
        for change in ('counts', 'architectures', 'selection'):
            with self.subTest(change=change):
                document = deepcopy(self.document)
                if change == 'counts':
                    document['counts']['source_files'] = 0
                elif change == 'architectures':
                    document['architectures'].append('invented')
                else:
                    document['selection']['targets'] = ['Wrong']
                with self.assertRaises(MigrationError):
                    self.check(document)

    def test_log_counts_and_compiler_summary_are_not_trusted(self):
        for field in ('bytes', 'swift_entries', 'clang_entries', 'other_entries', 'ambiguous_lines'):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document['evidence']['captured_build_log'][field] += 1
                with self.assertRaisesRegex(MigrationError, 'disagrees with replayed evidence'):
                    self.check(document)
        (self.capture / 'compile-invocations.json').write_bytes(b'{}')
        with self.assertRaisesRegex(MigrationError, 'summary disagrees'):
            self.check()

    def test_filelist_and_log_paths_cannot_escape_capture(self):
        for kind in ('filelist', 'log'):
            with self.subTest(kind=kind):
                document = deepcopy(self.document)
                item = (document['evidence']['sources'][0] if kind == 'filelist'
                        else document['evidence']['captured_build_log'])
                raw = (self.capture / item['artifact']).read_bytes()
                outside = self.root / ('outside-' + kind)
                outside.write_bytes(raw)
                item['artifact'] = ('filelists/../../' if kind == 'filelist' else '../') + outside.name
                with self.assertRaisesRegex(MigrationError, 'Unsafe relative path'):
                    self.check(document)

    def test_malformed_members_fail_as_contract_errors(self):
        for value in (None, 'member', [], 1):
            with self.subTest(value=value):
                document = deepcopy(self.document)
                document['members'][0] = value
                with self.assertRaisesRegex(MigrationError, 'list of objects'):
                    self.check(document)

    def test_malformed_excluded_records_fail_as_contract_errors(self):
        for value in (None, {'reason': []}, {'reason': 'outside_source_tree', 'path': '/outside',
                                           'relative_path': [], 'origins': [], 'targets': []}):
            with self.subTest(value=value):
                document = deepcopy(self.document)
                document['excluded_inputs'] = [value]
                with self.assertRaises(MigrationError):
                    self.check(document)

    def test_unknown_compiler_identity_cannot_be_complete(self):
        for field in ('target', 'architecture'):
            with self.subTest(field=field):
                document = deepcopy(self.document)
                document['evidence']['sources'][0][field] = None
                with self.assertRaises(MigrationError):
                    self.check(document)

    def test_generated_outside_and_unselected_inputs_remain_explicit(self):
        generated = self.write(self.derived / 'DerivedSources/Generated.swift', 'struct Generated {}\n')
        outside = self.write(self.root / 'Shared.swift', 'struct Shared {}\n')
        self.file_list('App', 'arm64', self.paths('App/App.swift') + [str(generated), str(outside)])
        test_source = self.write(self.source / 'AppTests/Test.swift', 'struct Test {}\n')
        self.file_list('AppTests', 'arm64', [str(test_source)])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'complete')
        self.assertTrue(self.check(document)['integrity_passed'])
        self.assertEqual({item['reason'] for item in document['excluded_inputs']},
                         {'generated_build_tree_input', 'outside_source_tree', 'outside_selected_targets'})

    def test_object_count_gaps_cannot_be_hidden_under_complete(self):
        directory = self.derived / 'App.build/Objects-normal/arm64'
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(12):
            (directory / (str(index) + '.o')).write_bytes(b'object')
        document = self.collect()
        self.assertEqual(document['membership_status'], 'incomplete')
        self.assertTrue(self.check(document)['integrity_passed'])
        document['membership_status'] = 'complete'
        document['unresolved'] = []
        document['counts']['unresolved_inputs'] = 0
        with self.assertRaisesRegex(MigrationError, 'must remain unresolved'):
            self.check(document)


if __name__ == '__main__':
    unittest.main()
