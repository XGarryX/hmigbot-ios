"""Actual build membership is derived from captured compiler inputs, and fails closed.

The fixtures are synthetic DerivedData trees and compiler logs, so the parsing,
contract and failure paths are testable on Windows. Real macOS capture remains
unverified on this host.
"""
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError, digest, json_bytes, read_json, snapshot, write_json
from hmigbot_ios.evidence import pack, validate as validate_evidence

SCHEMA_PATH = ROOT / 'schemas/source-build-membership.schema.json'


class MembershipBase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='source-membership-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'ios'
        self.capture = self.root / 'capture'
        self.derived = self.root / 'DerivedData'
        self.capture.mkdir()
        self.derived.mkdir()
        self.source.mkdir()
        for relative, text in {
                'App/App.swift': 'import SwiftUI\nstruct App: View {\n    @State private var count = 0\n}\n',
                'App/Model.swift': 'struct Model {}\n',
                'App/Unused.swift': 'import SwiftUI\nstruct Unused: View {\n    @State private var stale = 0\n}\n',
                'App/Legacy.m': '@implementation Legacy\n@end\n',
                'App/My File With Spaces/Deep View.swift': 'struct DeepView {}\n',
                'App/视图.swift': 'struct View {}\n',
                'Widget/Widget.swift': 'struct Widget {}\n',
                'App/Shaders.metal': 'kernel void shade() {}\n',
        }.items():
            self.write(self.source / relative, text)
        self.selection = {'scheme': 'App', 'configuration': 'Release', 'sdk': 'iphoneos',
                          'xcode_version': 'Xcode 16.2\nBuild version 16C5032a',
                          'product': 'com.example.app', 'targets': ['App', 'Widget'],
                          'architectures': ['arm64'], 'toolchain': {'SWIFT_VERSION': '5.0'}}

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('hmigbot_ios.source_build_membership'),
                             'Missing actual source build membership capability')
        return importlib.import_module('hmigbot_ios.source_build_membership')

    def file_list(self, target, architecture, entries):
        path = (self.derived / 'Build/Intermediates.noindex' / (target + '.build')
                / 'Release-iphoneos' / (target + '.build') / 'Objects-normal' / architecture
                / (target + '.SwiftFileList'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(entries) + '\n', encoding='utf-8')
        return path

    def build_log(self, lines, name='device-build.stdout.log'):
        path = self.capture / name
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return path

    def paths(self, *relative):
        return [str(self.source / item) for item in relative]

    def standard_build(self):
        """A clean device build: Swift lists per architecture, Clang and Metal invocations."""
        app_files = self.paths('App/App.swift', 'App/Model.swift',
                               'App/My File With Spaces/Deep View.swift', 'App/视图.swift')
        self.file_list('App', 'arm64', app_files)
        self.file_list('App', 'arm64e', app_files)  # Multi-architecture duplicate membership.
        self.file_list('Widget', 'arm64', self.paths('Widget/Widget.swift'))
        log = self.build_log([
            # A real build prints these task lines too; none of them names an input.
            'SwiftDriver App normal arm64 com.apple.xcode.tools.swift.compiler '
            "(in target 'App' from project 'App')",
            'SwiftEmitModule normal arm64 Emitting\\ module\\ for\\ App (in target \'App\' from project \'App\')',
            'CompileC /DerivedData/App.build/Objects-normal/arm64/Legacy.o ' + str(self.source / 'App/Legacy.m')
            + ' normal arm64 objective-c com.apple.compilers.llvm.clang.1_0.compiler (in target \'App\' from project \'App\')',
            'SwiftCompile normal arm64 Compiling\\ App.swift,\\ Model.swift ' + app_files[0] + ' ' + app_files[1]
            + " (in target 'App' from project 'App')",
            'CompileMetalFile /DerivedData/Objects-normal/arm64/Shaders.air ' + str(self.source / 'App/Shaders.metal')
            + " normal arm64 metal (in target 'App' from project 'App')",
            'Ld /DerivedData/App.app/App normal arm64 (in target \'App\' from project \'App\')',
        ])
        return log

    def collect(self, *, log=True):
        return self.module().collect(self.source, self.derived, self.capture, self.selection,
                                     build_log=(self.capture / 'device-build.stdout.log') if log else None)


class ParsingTests(MembershipBase):
    def test_file_list_parsing_keeps_paths_verbatim(self):
        module = self.module()
        raw = ('\ufeff' + str(self.source / 'App/App.swift') + '\r\n\n'
               + str(self.source / 'App/My File With Spaces/Deep View.swift') + '\r\n'
               + str(self.source / '视图.swift') + '\n').encode('utf-8')
        self.assertEqual(module.parse_file_list(raw), [
            str(self.source / 'App/App.swift').replace('\\', '/'),
            str(self.source / 'App/My File With Spaces/Deep View.swift').replace('\\', '/'),
            str(self.source / '视图.swift').replace('\\', '/'),
        ])
        with self.assertRaisesRegex(MigrationError, 'UTF-8'):
            module.parse_file_list(b'\xff\xfe\x00bad')
        with self.assertRaisesRegex(MigrationError, 'NUL'):
            module.parse_file_list(b'/a.swift\x00')

    def test_compile_invocations_rejoin_escaped_spaces_and_report_ambiguity(self):
        module = self.module()
        spaced = str(self.source / 'App/My File With Spaces/Deep View.swift')
        expected = spaced.replace('\\', '/')
        escaped = spaced.replace(' ', '\\ ')
        parsed = module.parse_compile_invocations('\n'.join([
            'CompileC /dd/Objects-normal/arm64/Deep.o ' + escaped + ' normal arm64 objective-c',
            'SwiftCompile normal arm64 Compiling\\ Deep\\ View.swift ' + escaped + " (in target 'App' from project 'App')",
            'CompileC /dd/Objects-normal/arm64/Broken.o app.swift normal arm64 objective-c',
            'Ld /dd/App normal arm64',
        ]))
        self.assertEqual([item['path'] for item in parsed['entries']], [expected, expected])
        self.assertEqual({item['origin'] for item in parsed['entries']},
                         {'build_log_clang_invocation', 'build_log_swift_invocation'})
        self.assertEqual(parsed['entries'][1]['target'], 'App')
        self.assertEqual(len(parsed['ambiguous']), 1)
        self.assertIn('Broken.o', parsed['ambiguous'][0]['detail'])

    def test_real_xcode_task_lines_are_not_reported_as_ambiguous(self):
        """Driver and module-emission lines name a task, not an input; a real log must not fail."""
        module = self.module()
        source = self.paths('App/App.swift', 'App/Model.swift')
        parsed = module.parse_compile_invocations('\n'.join([
            'SwiftDriver App normal arm64 com.apple.xcode.tools.swift.compiler (in target \'App\' from project \'App\')',
            'SwiftDriver Compilation Requirements App normal arm64 com.apple.xcode.tools.swift.compiler'
            ' (in target \'App\' from project \'App\')',
            'SwiftEmitModule normal arm64 Emitting\\ module\\ for\\ App (in target \'App\' from project \'App\')',
            'SwiftCompile normal arm64 Compiling\\ App.swift,\\ Model.swift ' + source[0] + ' ' + source[1]
            + " (in target 'App' from project 'App')",
            'Ld /dd/App.app/App normal arm64 (in target \'App\' from project \'App\')',
            'CodeSign /dd/App.app (in target \'App\' from project \'App\')',
        ]))
        self.assertEqual(parsed['ambiguous'], [])
        self.assertEqual([item['path'] for item in parsed['entries']],
                         [item.replace('\\', '/') for item in source])

    def test_swift_line_naming_an_unreadable_location_stays_ambiguous(self):
        module = self.module()
        parsed = module.parse_compile_invocations(
            'SwiftCompile normal arm64 Compiling\\ Gone.swift relative/Gone.swift'
            " (in target 'App' from project 'App')")
        self.assertEqual(parsed['entries'], [])
        self.assertEqual(len(parsed['ambiguous']), 1)


class SuccessfulCaptureTests(MembershipBase):
    def setUp(self):
        super().setUp()
        self.standard_build()
        self.document = self.collect()

    def test_actual_membership_is_complete_and_per_file_hashed(self):
        document = self.document
        self.assertEqual(document['membership_status'], 'complete')
        self.assertEqual(document['unresolved'], [])
        self.assertEqual(document['source_files'], sorted([
            'App/App.swift', 'App/Model.swift', 'App/Legacy.m', 'App/My File With Spaces/Deep View.swift',
            'App/视图.swift', 'Widget/Widget.swift', 'App/Shaders.metal']))
        by_path = {item['path']: item for item in document['members']}
        for path, member in by_path.items():
            raw = (self.source / path).read_bytes()
            self.assertEqual(member['sha256'], digest(raw))
            self.assertEqual(member['bytes'], len(raw))
        self.assertEqual(by_path['App/App.swift']['kind'], 'swift_source')
        self.assertEqual(by_path['App/Legacy.m']['kind'], 'clang_source')
        self.assertEqual(by_path['App/Shaders.metal']['kind'], 'other_compiler_input')
        self.assertEqual(by_path['App/Shaders.metal']['analysis'], 'not_analyzed')
        self.assertEqual(sorted(by_path['App/App.swift']['architectures']), ['arm64', 'arm64e'])
        self.assertEqual(sorted(by_path['App/App.swift']['origins']),
                         ['build_log_swift_invocation', 'swift_file_list'])
        self.assertEqual(sorted(by_path['App/App.swift']['targets']), ['App'])
        self.assertEqual(sorted(document['architectures']), ['arm64', 'arm64e'])
        self.assertEqual(document['selection']['targets'], ['App', 'Widget'])
        self.assertEqual(document['selection']['toolchain'], {'SWIFT_VERSION': '5.0'})
        self.assertEqual(document['source_sha256'], snapshot(self.source)['sha256'])
        self.assertIn('non_swift_inputs_recorded_not_analyzed', document['limitations'])
        self.assertEqual(document['claims']['build_authenticity'], 'not_verified')
        self.assertEqual(document['claims']['behavior_equivalence'], 'not_verified')
        self.assertEqual(document['counts']['source_files'], 7)
        self.assertEqual(document['counts']['unsupported_inputs'], 1)

    def test_capture_packaging_carries_raw_file_lists(self):
        document = self.document
        self.assertEqual(read_json(self.capture / 'source-files.json'), document)
        sources = document['evidence']['sources']
        self.assertEqual(len(sources), 3)
        for item in sources:
            path = self.capture / item['artifact']
            self.assertTrue(path.is_file())
            self.assertEqual(digest(path.read_bytes()), item['sha256'])
            self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()), item['entries'])
        log = document['evidence']['captured_build_log']
        self.assertEqual(log['artifact'], 'device-build.stdout.log')
        self.assertEqual(log['swift_entries'], 2)
        self.assertEqual(log['clang_entries'], 1)
        self.assertEqual(log['other_entries'], 1)
        self.assertTrue((self.capture / 'compile-invocations.json').is_file())

    def test_validate_replays_hashes_and_file_lists(self):
        module = self.module()
        checked = module.validate(self.source, self.capture / 'source-files.json', capture=self.capture)
        self.assertTrue(checked['integrity_passed'])
        self.assertEqual(checked['membership_status'], 'complete')
        self.assertEqual(checked['source_files'], self.document['source_files'])

    def test_validate_rejects_tampered_member_and_stale_source(self):
        module = self.module()
        document = json.loads((self.capture / 'source-files.json').read_text(encoding='utf-8'))
        document['members'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(MigrationError, 'differs from current source'):
            module.validate(self.source, document)
        self.write(self.source / 'App/App.swift', 'struct App { let changed = true }\n')
        with self.assertRaisesRegex(MigrationError, 'fingerprint is stale'):
            module.validate(self.source, self.capture / 'source-files.json', capture=self.capture)

    def test_validate_rejects_tampered_file_list_artifact(self):
        module = self.module()
        source = self.document['evidence']['sources'][0]['artifact']
        path = self.capture / source
        path.write_text(path.read_text(encoding='utf-8') + str(self.source / 'App/Injected.swift') + '\n',
                        encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, 'modified'):
            module.validate(self.source, self.capture / 'source-files.json', capture=self.capture)

    def test_complete_document_cannot_list_unresolved_input(self):
        module = self.module()
        document = json.loads((self.capture / 'source-files.json').read_text(encoding='utf-8'))
        document['unresolved'] = [{'reason': 'missing_compile_input', 'path': 'App/Gone.swift',
                                   'detail': 'absent'}]
        with self.assertRaisesRegex(MigrationError, 'must not carry unresolved inputs'):
            module.validate(self.source, document)


class ConsumerContractTests(MembershipBase):
    def test_producer_bundle_satisfies_selected_build_consumer(self):
        self.standard_build()
        document = self.collect()
        bundle = self.root / 'evidence'
        pack(self.source, self.capture, bundle, 'source_build', 'xcodebuild 16.2')
        manifest = read_json(bundle / 'manifest.json')
        self.assertIn('artifacts/source-files.json', manifest['artifacts'])
        self.assertEqual(read_json(bundle / 'artifacts/source-files.json')['source_files'],
                         document['source_files'])
        self.assertTrue(validate_evidence(self.source, bundle)['integrity_passed'])
        from hmigbot_ios.ios_facts import extract
        graph = extract(self.source, {'scope': 'selected-build',
                                      'source_files': document['source_files'],
                                      'evidence_path': str(bundle)})
        self.assertEqual(graph['variant']['scope'], 'selected-build')
        scanned = {fact['anchor']['path'] for fact in graph['facts']}
        self.assertIn('App/App.swift', scanned)
        self.assertNotIn('App/Unused.swift', scanned)  # Present in source, absent from actual membership.
        self.assertNotIn('App/Shaders.metal', scanned)  # Recorded member, not a text source kind.

    def test_consumer_rejects_membership_that_differs_from_the_variant(self):
        self.standard_build()
        document = self.collect()
        bundle = self.root / 'evidence'
        pack(self.source, self.capture, bundle, 'source_build', 'xcodebuild 16.2')
        from hmigbot_ios.ios_facts import extract
        for variant_files in (document['source_files'][:-1], list(reversed(document['source_files']))):
            with self.assertRaisesRegex(MigrationError, 'Selected membership must match'):
                extract(self.source, {'scope': 'selected-build', 'source_files': variant_files,
                                      'evidence_path': str(bundle)})

    def test_generated_and_out_of_tree_inputs_stay_explicit_not_members(self):
        generated = self.derived / 'Build/Intermediates.noindex/App.build/Release-iphoneos/App.build' \
                                   '/DerivedSources/Generated.swift'
        self.write(generated, 'struct Generated {}\n')
        outside = self.root / 'Shared/Shared.swift'
        self.write(outside, 'struct Shared {}\n')
        self.file_list('App', 'arm64', self.paths('App/App.swift') + [str(generated), str(outside)])
        document = self.collect(log=False)
        reasons = {item['path']: item['reason'] for item in document['excluded_inputs']}
        self.assertEqual(reasons[str(generated).replace('\\', '/')], 'generated_build_tree_input')
        self.assertEqual(reasons[str(outside).replace('\\', '/')], 'outside_source_tree')
        self.assertEqual(document['source_files'], ['App/App.swift'])
        self.assertEqual(document['membership_status'], 'complete')
        self.assertIn('generated_build_tree_inputs_recorded_not_members', document['limitations'])
        self.assertIn('out_of_tree_inputs_recorded_not_members', document['limitations'])
        self.assertEqual(document['counts']['non_member_inputs'], 2)

    def test_snapshot_excluded_input_is_incomplete_not_silently_dropped(self):
        hidden = self.write(self.source / 'build/Generated.swift', 'struct Generated {}\n')
        self.file_list('App', 'arm64', self.paths('App/App.swift') + [str(hidden)])
        document = self.collect(log=False)
        module = self.module()
        self.assertEqual(document['membership_status'], 'incomplete')
        self.assertEqual(document['source_files'], ['App/App.swift'])
        self.assertNotIn('build/Generated.swift', document['source_files'])
        self.assertEqual([item['reason'] for item in document['excluded_inputs']],
                         ['outside_source_fingerprint_scope'])
        self.assertEqual(module.validate(self.source, document)['membership_status'], 'incomplete')
        document['membership_status'] = 'complete'
        with self.assertRaisesRegex(MigrationError, 'must not exclude compiled inputs'):
            module.validate(self.source, document)


class ObjectCoverageTests(MembershipBase):
    def objects(self, target, architecture, names):
        directory = (self.derived / 'Build/Intermediates.noindex' / (target + '.build')
                     / 'Release-iphoneos' / (target + '.build') / 'Objects-normal' / architecture)
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            (directory / name).write_bytes(b'\x00object')
        return directory

    def test_object_files_matching_captured_inputs_stay_complete(self):
        self.standard_build()
        self.objects('App', 'arm64', ['App.o', 'Model.o', 'Deep View.o', '视图.o', 'Legacy.o', 'Shaders.o'])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'complete')
        directories = {(item['target'], item['architecture']): item
                       for item in document['evidence']['build_tree_objects']['directories']}
        self.assertEqual(directories[('App', 'arm64')]['objects'], 6)
        self.assertEqual(directories[('App', 'arm64')]['captured_inputs'], 6)
        self.assertEqual(document['evidence']['build_tree_objects']['unmatched'], [])

    def test_uncompiled_object_exceeds_membership_and_fails_closed(self):
        self.standard_build()
        self.objects('App', 'arm64', ['App.o', 'Model.o', 'Deep View.o', '视图.o', 'Legacy.o', 'Shaders.o',
                                      'Uncaptured.o'])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'incomplete')
        self.assertIn('object_count_exceeds_membership',
                      [item['reason'] for item in document['unresolved']])
        unmatched = document['evidence']['build_tree_objects']['unmatched'][0]
        self.assertEqual(unmatched['objects'], 7)
        self.assertEqual(unmatched['captured_inputs'], 6)
        self.assertEqual(len(unmatched['sample_objects']), 5)
        self.assertTrue(all(name.endswith('.o') for name in unmatched['sample_objects']))


class TargetScopeTests(MembershipBase):
    def test_dependency_target_inputs_are_recorded_not_members(self):
        pod = self.write(self.source / 'Pods/Thing/Thing.m', '@implementation Thing\n@end\n')
        self.write(self.source / 'Pods/Thing/Thing.h', '@interface Thing\n@end\n')
        self.file_list('App', 'arm64', self.paths('App/App.swift'))
        log = self.build_log([
            'CompileC /dd/Pods.build/Objects-normal/arm64/Thing.o ' + str(pod)
            + " normal arm64 objective-c com.apple.compilers.llvm.clang.1_0.compiler (in target 'Thing' from project 'Pods')",
        ])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'complete')
        self.assertEqual(document['source_files'], ['App/App.swift'])
        reasons = {item['path']: item['reason'] for item in document['excluded_inputs']}
        self.assertEqual(reasons[str(pod).replace('\\', '/')], 'outside_selected_targets')
        self.assertIn('unselected_target_inputs_recorded_not_members', document['limitations'])
        self.assertTrue(log.is_file())

    def test_test_target_inputs_are_recorded_not_members(self):
        test_file = self.write(self.source / 'AppTests/AppTests.swift', 'struct AppTests {}\n')
        self.file_list('App', 'arm64', self.paths('App/App.swift'))
        self.build_log(['SwiftCompile normal arm64 Compiling\\ AppTests.swift ' + str(test_file)
                        + " (in target 'AppTests' from project 'App')"])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'complete')
        self.assertNotIn('AppTests/AppTests.swift', document['source_files'])


class FailurePathTests(MembershipBase):
    def test_missing_listed_file_fails_closed(self):
        self.file_list('App', 'arm64', self.paths('App/App.swift', 'App/Gone.swift'))
        document = self.collect(log=False)
        self.assertEqual(document['membership_status'], 'incomplete')
        self.assertIn('missing_compile_input', [item['reason'] for item in document['unresolved']])
        self.assertEqual(document['source_files'], ['App/App.swift'])

    def test_escaping_and_relative_inputs_fail_closed(self):
        self.file_list('App', 'arm64', self.paths('App/App.swift') + [
            str(self.source / '../outside.swift'), 'App/Relative.swift'])
        document = self.collect(log=False)
        self.assertEqual(document['membership_status'], 'incomplete')
        reasons = {item['reason'] for item in document['unresolved']}
        self.assertEqual(reasons, {'escaping_compile_input', 'relative_compile_input'})

    def test_no_evidence_is_unresolved_not_empty_success(self):
        document = self.collect(log=False)
        self.assertEqual(document['membership_status'], 'unresolved')
        self.assertEqual(document['source_files'], [])
        self.assertIn('no_compile_evidence', [item['reason'] for item in document['unresolved']])
        self.assertIn('build_log_cross_check_unavailable', document['limitations'])

    def test_swift_compiled_without_any_file_list_is_incomplete(self):
        self.build_log(['SwiftCompile normal arm64 Compiling\\ App.swift ' + str(self.source / 'App/App.swift')
                        + " (in target 'App' from project 'App')"])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'incomplete')
        self.assertIn('swift_file_list_absent', [item['reason'] for item in document['unresolved']])
        self.assertEqual(document['source_files'], ['App/App.swift'])

    def test_ambiguous_compiler_line_is_incomplete(self):
        self.file_list('App', 'arm64', self.paths('App/App.swift'))
        self.build_log(['CompileC /dd/A.o not-a-path.m normal arm64 objective-c'])
        document = self.collect()
        self.assertEqual(document['membership_status'], 'incomplete')
        self.assertIn('ambiguous_compile_invocation', [item['reason'] for item in document['unresolved']])

    def test_missing_build_tree_is_reported(self):
        self.file_list('App', 'arm64', self.paths('App/App.swift'))
        removed = self.derived
        document = self.module().collect(self.source, removed / 'absent', self.capture, self.selection,
                                        build_log=self.capture / 'device-build.stdout.log')
        self.assertEqual(document['membership_status'], 'unresolved')
        self.assertIn('build_tree_missing', [item['reason'] for item in document['unresolved']])
        self.assertEqual(document['source_files'], [])

    def test_capture_overlapping_source_is_refused(self):
        inner = self.source / 'capture'
        inner.mkdir()
        with self.assertRaisesRegex(MigrationError, 'must not overlap'):
            self.module().collect(self.source, self.derived, inner, self.selection)

    def test_unknown_selection_field_is_refused(self):
        with self.assertRaisesRegex(MigrationError, 'Unknown membership selection fields'):
            self.module().collect(self.source, self.derived, self.capture,
                                  {**self.selection, 'guessed_targets': ['App']})


class ProducerWiringTests(MembershipBase):
    def provider(self):
        spec = importlib.util.spec_from_file_location('hmigbot_build_source',
                                                      ROOT / 'providers/xcode/build_source.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_selection_reads_only_selected_build_settings(self):
        provider = self.provider()
        parsed = [
            {'buildSettings': {'WRAPPER_EXTENSION': 'app', 'TARGET_NAME': 'App', 'ARCHS': 'arm64'}},
            {'buildSettings': {'WRAPPER_EXTENSION': 'appex', 'TARGET_NAME': 'WidgetExtension'}},
            {'buildSettings': {'WRAPPER_EXTENSION': 'xctest', 'TARGET_NAME': 'AppTests'}},
        ]
        settings = {'TARGET_NAME': 'App', 'ARCHS': 'arm64 arm64e', 'SWIFT_VERSION': '5.0',
                    'SDK_VERSION': '18.2', 'TOOLCHAINS': '', 'IPHONEOS_DEPLOYMENT_TARGET': '17.0'}
        selection = provider.membership_selection(parsed, settings, scheme='App', configuration='Release',
                                                  sdk='iphoneos', xcode_version='Xcode 16.2',
                                                  product='com.example.app')
        self.assertEqual(selection['targets'], ['App', 'WidgetExtension'])
        self.assertEqual(selection['architectures'], ['arm64', 'arm64e'])
        self.assertEqual(selection['toolchain'],
                         {'IPHONEOS_DEPLOYMENT_TARGET': '17.0', 'SDK_VERSION': '18.2', 'SWIFT_VERSION': '5.0'})
        self.assertNotIn('AppTests', selection['targets'])

    def test_producer_records_membership_before_packaging_and_cleanup(self):
        provider = self.provider()
        self.standard_build()
        document = provider.record_source_membership(
            source=self.source, derived_data=self.derived, capture=self.capture,
            build_log=self.capture / 'device-build.stdout.log', selection=self.selection)
        self.assertEqual(document['membership_status'], 'complete')
        self.assertEqual(read_json(self.capture / 'source-files.json')['source_files'],
                         document['source_files'])
        summary = provider.membership_summary(document)
        self.assertEqual(summary['status'], 'complete')
        self.assertEqual(summary['artifact'], 'artifacts/source-files.json')
        self.assertEqual(summary['source_files'], 7)
        self.assertEqual(summary['unsupported_inputs'], 1)
        import inspect
        body = inspect.getsource(provider.main)
        self.assertIn('record_source_membership(', body)
        self.assertIn('MembershipIncomplete', body)
        self.assertLess(body.index('record_source_membership('), body.index("stage = output / 'package/Payload'"))
        self.assertTrue(issubclass(provider.MembershipIncomplete, RuntimeError))


class SchemaContractTests(MembershipBase):
    def test_schema_matches_emitted_document(self):
        self.standard_build()
        document = self.collect()
        schema = read_json(SCHEMA_PATH)
        self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']), set(document))
        self.assertEqual(schema['properties']['kind']['const'], document['kind'])
        self.assertEqual(schema['properties']['scope']['const'], document['scope'])
        self.assertEqual(schema['properties']['membership_status']['enum'],
                         ['complete', 'incomplete', 'unresolved'])
        selection = schema['properties']['selection']
        self.assertLessEqual(set(selection['required']), set(document['selection']))
        self.assertEqual(set(document['selection']), set(selection['properties']))
        self.assertLessEqual(set(document['selection']), set(selection['properties']))
        member_properties = schema['$defs']['member']['properties']
        self.assertEqual(set(member_properties), set(document['members'][0]))
        self.assertLessEqual({item['kind'] for item in document['members']},
                             set(member_properties['kind']['enum']))
        self.assertEqual(set(schema['$defs']['excluded']['properties']),
                         set(document['excluded_inputs'][0] if document['excluded_inputs'] else
                             {'path', 'relative_path', 'reason', 'detail', 'origins', 'targets'}))
        self.assertEqual(set(schema['properties']['counts']['properties']), set(document['counts']))
        self.assertEqual(set(schema['properties']['claims']['properties']), set(document['claims']))
        self.assertEqual(set(schema['properties']['evidence']['properties']), set(document['evidence']))
        self.assertEqual(set(schema['properties']['evidence']['required']), set(document['evidence']))

    def test_schema_enumerates_every_reason_this_module_emits(self):
        schema = read_json(SCHEMA_PATH)
        reasons = set(schema['$defs']['unresolved']['properties']['reason']['enum'])
        module = self.module()
        source = (ROOT / 'src/hmigbot_ios/source_build_membership.py').read_text(encoding='utf-8')
        for reason in reasons:
            self.assertIn(f'"{reason}"', source, f'Schema lists an unused reason: {reason}')
        self.assertIn('no_compile_evidence', reasons)
        self.assertIn('missing_compile_input', reasons)
        self.assertIn('outside_source_fingerprint_scope',
                      schema['$defs']['excluded']['properties']['reason']['enum'])
        self.assertEqual(set(schema['$defs']['origins']['items']['enum']), set(module.ORIGINS))
        self.assertTrue(schema['$defs']['source']['properties']['artifact']['pattern'].startswith('^filelists/'))


if __name__ == '__main__':
    unittest.main()
