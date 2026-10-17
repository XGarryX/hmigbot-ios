"""Declared Xcode membership must be derived, complete and honest about builds."""
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import MigrationError


def openstep(value):
    if isinstance(value, dict):
        return '{' + ''.join(openstep(k) + '=' + openstep(v) + ';' for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '(' + ','.join(openstep(v) for v in value) + ')'
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


class ProjectScopeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='declared xcode scope ')
        self.addCleanup(temp.cleanup)
        self.source = Path(temp.name)
        self.project = self.source / 'Example.xcodeproj/project.pbxproj'
        self.project.parent.mkdir()
        self.variant = {'scope': 'project-targets', 'project_path': 'Example.xcodeproj/project.pbxproj',
                        'targets': ['Example'], 'configuration': 'Release'}
        self.objects = {
            'P': {'isa': 'PBXProject', 'mainGroup': 'G', 'targets': ['A', 'E', 'T', 'L'],
                  'projectDirPath': '', 'buildConfigurationList': 'PC'},
            'G': {'isa': 'PBXGroup', 'sourceTree': '<group>', 'children': []},
            'PC': {'isa': 'XCConfigurationList', 'buildConfigurations': ['PR']},
            'PR': {'isa': 'XCBuildConfiguration', 'name': 'Release', 'buildSettings': {}},
        }
        specs = [('A', 'Example', 'com.apple.product-type.application', ['App.swift', 'Shared.swift']),
                 ('E', 'Widget', 'com.apple.product-type.app-extension', ['Widget.swift']),
                 ('T', 'ExampleTests', 'com.apple.product-type.bundle.unit-test', ['OnlyTests.swift', 'Shared.swift']),
                 ('L', 'SharedLibrary', 'com.apple.product-type.library.static', ['Library.swift'])]
        files = {}
        for tid, name, kind, sources in specs:
            self.objects[tid] = {'isa': 'PBXNativeTarget', 'name': name, 'productType': kind,
                                 'productReference': tid + 'PRODUCT', 'buildConfigurationList': tid + 'C',
                                 'buildPhases': [tid + 'S'], 'dependencies': []}
            self.objects[tid + 'PRODUCT'] = {'isa': 'PBXFileReference', 'path': name,
                                           'sourceTree': 'BUILT_PRODUCTS_DIR'}
            self.objects[tid + 'C'] = {'isa': 'XCConfigurationList', 'buildConfigurations': [tid + 'R']}
            self.objects[tid + 'R'] = {'isa': 'XCBuildConfiguration', 'name': 'Release', 'buildSettings': {}}
            phase = self.objects[tid + 'S'] = {'isa': 'PBXSourcesBuildPhase', 'files': []}
            for index, path in enumerate(sources):
                fid = files.setdefault(path, 'F' + str(len(files)))
                self.objects[fid] = {'isa': 'PBXFileReference', 'path': path, 'sourceTree': '<group>'}
                if fid not in self.objects['G']['children']:
                    self.objects['G']['children'].append(fid)
                (self.source / path).write_text('// ' + path, encoding='utf-8')
                bid = tid + 'B' + str(index)
                self.objects[bid] = {'isa': 'PBXBuildFile', 'fileRef': fid}
                phase['files'].append(bid)
        self.objects['A']['dependencies'] = ['D']
        self.objects['D'] = {'isa': 'PBXTargetDependency', 'targetProxy': 'PROXY'}
        self.objects['PROXY'] = {'isa': 'PBXContainerItemProxy', 'containerPortal': 'P',
                                 'remoteGlobalIDString': 'L', 'proxyType': '1'}
        self.objects['A']['buildPhases'].append('EMBED')
        self.objects['EMBED'] = {'isa': 'PBXCopyFilesBuildPhase', 'dstSubfolderSpec': '13', 'files': ['EB']}
        self.objects['EB'] = {'isa': 'PBXBuildFile', 'fileRef': 'EPRODUCT'}
        self._write()

    def _write(self):
        self.project.write_text(openstep({'rootObject': 'P', 'objects': self.objects}), encoding='utf-8')

    def _resolve(self, variant=None):
        self.assertIsNotNone(importlib.util.find_spec('hmigbot_ios.project_scope'),
                             'project-target membership resolver has not been implemented')
        return importlib.import_module('hmigbot_ios.project_scope').resolve(self.source, self.variant if variant is None else variant)

    def assert_rejected(self, message, variant=None):
        with self.assertRaisesRegex(MigrationError, message):
            self._resolve(variant)

    def test_dependencies_and_embedded_extension_close_over_declared_sources(self):
        scope = self._resolve()
        self.assertEqual(scope['source_files'], ['App.swift', 'Library.swift', 'Shared.swift', 'Widget.swift'])
        self.assertEqual(scope['target_closure'], ['Example', 'SharedLibrary', 'Widget'])
        self.assertEqual(scope['evidence'], 'project_declared_membership')
        self.assertEqual(scope['effective_build'], 'unresolved')
        self.assertIn('headers_implicit_includes_unresolved', scope['limitations'])
        self.assertEqual(scope['excluded_sources'][0]['path'], 'OnlyTests.swift')
        self.assertEqual(scope['excluded_sources'][0]['targets'], ['ExampleTests'])
        self.assertEqual(scope['excluded_sources'][0]['reason'], 'test_only_oracle')
        shared = next(item for item in scope['source_membership'] if item['path'] == 'Shared.swift')
        self.assertEqual(shared['targets'], ['Example', 'ExampleTests'])

    def test_test_only_condition_is_outside_product_and_package_manifest_is_not_a_compile_unit(self):
        (self.source / 'OnlyTests.swift').write_text('#if canImport(XCTest)\nimport XCTest\n#endif\n')
        (self.source / 'Package.swift').write_text('// swift-tools-version: 5.9\nimport PackageDescription')
        scope = self._resolve()
        self.assertNotIn('OnlyTests.swift', scope['source_files'])
        self.assertNotIn('Package.swift', scope['source_files'])
        self.assertEqual([item['path'] for item in scope['excluded_sources']], ['OnlyTests.swift'])

    def test_user_cannot_supply_or_modify_a_source_file_allowlist(self):
        self.assert_rejected('derived|membership', {**self.variant, 'source_files': ['App.swift']})
        scope = self._resolve()
        scope['source_files'] = ['App.swift']
        self.assert_rejected('derived|membership|stale', scope)

    def test_canonical_scope_recomputes_and_rejects_source_or_project_changes(self):
        scope = self._resolve()
        self.assertEqual(scope, self._resolve(scope))
        (self.source / 'App.swift').write_text('// changed source')
        self.assert_rejected('stale|derived', scope)
        scope = self._resolve()
        self.project.write_text(self.project.read_text() + '\n// changed project\n')
        self.assert_rejected('stale|derived', scope)

    def test_unowned_compile_unit_is_unknown_even_under_a_tests_directory(self):
        (self.source / 'Tests').mkdir()
        (self.source / 'Tests/Undeclared.swift').write_text('struct Undeclared {}')
        self.assert_rejected('unknown.*membership|unowned')

    def test_script_and_synchronized_group_are_unresolved(self):
        self.objects['SCRIPT'] = {'isa': 'PBXShellScriptBuildPhase', 'files': [], 'shellScript': 'echo generated'}
        self.objects['L']['buildPhases'].append('SCRIPT')
        self._write()
        self.assert_rejected('script')
        self.objects['L']['buildPhases'].remove('SCRIPT')
        self.objects['E']['fileSystemSynchronizedGroups'] = ['SG']
        self._write()
        self.assert_rejected('synchronized')

    def test_unknown_duplicate_nonproduct_targets_and_configuration_are_rejected(self):
        self.assert_rejected('Unknown|unknown', {**self.variant, 'targets': ['Missing']})
        self.assert_rejected('Duplicate|duplicate', {**self.variant, 'targets': ['Example', 'Example']})
        self.assert_rejected('application|app-extension|product', {**self.variant, 'targets': ['ExampleTests']})
        self.assert_rejected('configuration', {**self.variant, 'configuration': 'Missing'})

    def test_missing_or_ambiguous_source_path_is_rejected(self):
        (self.source / 'Widget.swift').unlink()
        self.assert_rejected('missing|exist')
        (self.source / 'Widget.swift').write_text('// restored')
        self.objects['G2'] = {'isa': 'PBXGroup', 'children': ['F0'], 'sourceTree': '<group>'}
        self._write()
        self.assert_rejected('ambiguous|parents')

    def test_source_path_escape_duplicate_phase_entry_and_unknown_reference_are_rejected(self):
        self.objects['F0']['path'] = '../Outside.swift'
        self._write()
        self.assert_rejected('escape|relative|outside')
        self.objects['F0']['path'] = 'App.swift'
        self.objects['AS']['files'].append('AB0')
        self._write()
        self.assert_rejected('Duplicate|duplicate')
        self.objects['AS']['files'].pop()
        self.objects['AB0']['fileRef'] = 'UNKNOWN'
        self._write()
        self.assert_rejected('Unknown|unknown|reference')

    def test_cross_project_dependency_and_platform_filter_are_not_guessed(self):
        self.objects['PROXY']['containerPortal'] = 'ExternalProject'
        self._write()
        self.assert_rejected('cross.project|external|portal')
        self.objects['PROXY']['containerPortal'] = 'P'
        self.objects['AB0']['platformFilters'] = ['ios']
        self._write()
        self.assert_rejected('platform')

    def test_project_directory_variables_and_external_packages_are_not_assumed(self):
        self.objects['P']['projectDirPath'] = '../Other'
        self._write()
        self.assert_rejected('projectDirPath')
        self.objects['P']['projectDirPath'] = ''
        self.objects['F0']['path'] = '$(SOURCES)/App.swift'
        self._write()
        self.assert_rejected('variable|unresolved')
        self.objects['F0']['path'] = 'App.swift'
        self.objects['A']['packageProductDependencies'] = ['ExternalPackage']
        self._write()
        self.assert_rejected('package|external')

    def test_source_exclusions_are_conservative_and_not_claimed_as_effective_build(self):
        self.objects['AR']['buildSettings']['EXCLUDED_SOURCE_FILE_NAMES'] = 'App.swift'
        self._write()
        scope = self._resolve()
        self.assertIn('App.swift', scope['source_files'])
        self.assertIn('conditional_build_settings_not_evaluated', scope['limitations'])
        self.assertEqual(scope['effective_build'], 'unresolved')

    def test_custom_build_rule_scripts_cannot_supply_unseen_generated_sources(self):
        self.objects['RULE'] = {'isa': 'PBXBuildRule', 'script': 'echo generated', 'fileType': 'pattern.proxy'}
        self.objects['L']['buildRules'] = ['RULE']
        self._write()
        self.assert_rejected('rule|script')

    def test_project_input_is_concrete_and_not_a_path_escape_or_a_missing_project(self):
        for path in ('../Example.xcodeproj/project.pbxproj', 'Example.xcodeproj', 'Missing.xcodeproj/project.pbxproj'):
            with self.subTest(path=path):
                self.assert_rejected('path|exist|project', {**self.variant, 'project_path': path})

    def test_selected_unsupported_compile_languages_cannot_be_claimed_as_analyzed(self):
        original = self.source / 'App.swift'
        original.unlink()
        for suffix in ('.cc', '.cxx', '.metal', '.s', '.SWIFT'):
            with self.subTest(suffix=suffix):
                unsupported = self.source / ('App' + suffix)
                unsupported.write_text('// unsupported product compile unit')
                self.objects['F0']['path'] = unsupported.name
                self._write()
                try:
                    self.assert_rejected('Unsupported.*compile|unsupported.*compile')
                finally:
                    unsupported.unlink()

    def test_unsupported_compile_language_outside_product_remains_reference_evidence(self):
        fid = self.objects['TB0']['fileRef']
        (self.source / 'OnlyTests.swift').unlink()
        (self.source / 'OnlyTests.metal').write_text('// test-only shader')
        self.objects[fid]['path'] = 'OnlyTests.metal'
        self._write()
        scope = self._resolve()
        self.assertNotIn('OnlyTests.metal', scope['source_files'])
        self.assertEqual(scope['excluded_sources'][0]['path'], 'OnlyTests.metal')
        self.assertEqual(scope['excluded_sources'][0]['reason'], 'test_only_oracle')


if __name__ == '__main__':
    unittest.main()
