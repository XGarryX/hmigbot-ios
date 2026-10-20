"""Windows synthetic fixtures: declaration subset, never an Xcode build test.

Apple's public guide describes buildable folders, not the PBX serialization:
https://developer.apple.com/documentation/xcode/managing-files-and-folders-in-your-xcode-project
The input field assumptions are taken from Xcodeproj's primary implementation
linked by synchronized_membership; these fixtures do not verify Apple's schema.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hmigbot_ios.core import MigrationError, snapshot
from hmigbot_ios.project_scope import resolve
from hmigbot_ios.xcode import project_inventory
from test_project_scope import openstep


class SynchronizedGroupsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='同步 group ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'Example.xcodeproj/project.pbxproj'
        self.path.parent.mkdir()
        self.variant = {'scope': 'project-targets', 'project_path': 'Example.xcodeproj/project.pbxproj',
                        'targets': ['App'], 'configuration': 'Release'}
        self.objects = {
            'P': {'isa': 'PBXProject', 'mainGroup': 'G', 'targets': ['A', 'W'], 'buildConfigurationList': 'PC'},
            'G': {'isa': 'PBXGroup', 'children': ['AG', 'WG'], 'sourceTree': '<group>'},
            'PC': {'isa': 'XCConfigurationList', 'buildConfigurations': ['PR']},
            'PR': {'isa': 'XCBuildConfiguration', 'name': 'Release', 'buildSettings': {}},
        }
        for tid, name, directory, product in [
                ('A', 'App', '应用 Sources', 'com.apple.product-type.application'),
                ('W', 'Widget', 'Widget Sources', 'com.apple.product-type.app-extension')]:
            self.objects[tid] = {'isa': 'PBXNativeTarget', 'name': name, 'productType': product,
                'buildPhases': [tid + 'S'], 'dependencies': [], 'buildConfigurationList': tid + 'C',
                'fileSystemSynchronizedGroups': [tid + 'G']}
            self.objects[tid + 'C'] = {'isa': 'XCConfigurationList', 'buildConfigurations': [tid + 'R']}
            self.objects[tid + 'R'] = {'isa': 'XCBuildConfiguration', 'name': 'Release', 'buildSettings': {}}
            self.objects[tid + 'S'] = {'isa': 'PBXSourcesBuildPhase', 'files': []}
            self.objects[tid + 'G'] = {'isa': 'PBXFileSystemSynchronizedRootGroup', 'path': directory,
                'sourceTree': '<group>', 'explicitFileTypes': {}, 'explicitFolders': []}
        self.put('应用 Sources/App.swift')
        self.put('应用 Sources/Nested/模型 Space.swift')
        self.put('Widget Sources/Widget.swift')
        self.put('应用 Sources/Assets.xcassets/Contents.json', '{}')
        self.write()

    def put(self, name, content='struct Model {}'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def write(self):
        self.path.write_text(openstep({'rootObject': 'P', 'objects': self.objects}), encoding='utf-8')

    def scope(self, variant=None):
        return resolve(self.root, variant or self.variant)

    def rejected(self, pattern):
        self.write()
        with self.assertRaisesRegex(MigrationError, pattern):
            self.scope()

    def exception(self, paths, target='A'):
        self.objects['AG']['exceptions'] = ['EX']
        self.objects['EX'] = {'isa': 'PBXFileSystemSynchronizedBuildFileExceptionSet',
                              'target': target, 'membershipExceptions': paths}
        self.write()

    def test_nested_unicode_separate_targets_and_inventory(self):
        scope = self.scope()
        self.assertEqual(scope['source_files'], ['应用 Sources/App.swift', '应用 Sources/Nested/模型 Space.swift'])
        self.assertEqual(scope['excluded_sources'][0]['targets'], ['Widget'])
        self.assertEqual(scope['excluded_sources'][0]['reason'], 'outside_product_target_closure')
        self.assertEqual(scope['effective_build'], 'unresolved')
        self.assertIn('synchronized_format_subset_not_apple_schema_verified', scope['limitations'])
        inventory, issues = project_inventory(self.root, snapshot(self.root)['files'])
        self.assertEqual(issues, [])
        group = inventory['projects'][0]['targets'][0]['synchronized_groups'][0]
        self.assertEqual(group['targets'], ['A'])
        self.assertEqual(group['evidence'], 'project_declared_synchronized_membership')

    def test_dependency_closure_includes_widget_without_directory_guess(self):
        self.objects['A']['dependencies'] = ['D']
        self.objects['D'] = {'isa': 'PBXTargetDependency', 'target': 'W'}
        self.write()
        scope = self.scope()
        self.assertEqual(scope['target_closure'], ['App', 'Widget'])
        self.assertIn('Widget Sources/Widget.swift', scope['source_files'])

    def test_explicit_exception_is_auditable_and_target_specific(self):
        self.objects['W']['fileSystemSynchronizedGroups'].append('AG')
        self.exception(['App.swift'])
        scope = self.scope()
        excluded = next(x for x in scope['excluded_sources'] if x['path'] == '应用 Sources/App.swift')
        self.assertEqual(excluded['targets'], ['Widget'])
        self.assertEqual(excluded['excluded_from_targets'], ['App'])
        self.assertEqual(excluded['synchronized_group_ids'], ['AG'])
        self.objects['W']['fileSystemSynchronizedGroups'].remove('AG')
        self.write()
        excluded = next(x for x in self.scope()['excluded_sources'] if x['path'] == '应用 Sources/App.swift')
        self.assertEqual(excluded['reason'], 'synchronized_membership_exception')
        self.assertEqual(excluded['targets'], [])

    def test_new_file_and_excluded_file_edits_invalidate_derived_hash(self):
        original = self.scope()
        self.put('应用 Sources/Nested/New.swift')
        new = self.scope()
        self.assertNotEqual(original['source_hash'], new['source_hash'])
        self.assertIn('应用 Sources/Nested/New.swift', new['source_files'])
        with self.assertRaisesRegex(MigrationError, 'Stale|modified'):
            self.scope(original)
        self.exception(['App.swift'])
        old = self.scope()
        self.put('应用 Sources/App.swift', '// edited excluded source')
        self.assertNotEqual(old['source_hash'], self.scope()['source_hash'])

    def test_source_root_and_matching_explicit_type(self):
        self.objects['AG']['sourceTree'] = 'SOURCE_ROOT'
        self.objects['AG']['explicitFileTypes'] = {'App.swift': 'sourcecode.swift'}
        self.write()
        self.assertIn('应用 Sources/App.swift', self.scope()['source_files'])
        self.objects['AG']['explicitFileTypes']['App.swift'] = 'text'
        self.rejected('explicit file type')

    def test_unknown_fields_flags_and_phase_exceptions_fail_closed(self):
        self.objects['AG']['futureMembershipFlag'] = '1'
        self.rejected('Unsupported synchronized root fields')
        del self.objects['AG']['futureMembershipFlag']
        self.exception(['App.swift'])
        for field, value in [('additionalCompilerFlagsByRelativePath', {'App.swift': '-DOTHER'}),
                             ('platformFiltersByRelativePath', {'App.swift': ['ios']}),
                             ('unknown', [])]:
            self.objects['EX'][field] = value
            self.rejected('exception fields')
            del self.objects['EX'][field]
        self.objects['EX']['isa'] = 'PBXFileSystemSynchronizedGroupBuildPhaseMembershipExceptionSet'
        self.rejected('exception kind')

    def test_folder_exceptions_missing_files_and_wrong_target_fail_closed(self):
        self.exception(['Nested'])
        self.rejected('existing regular file')
        self.exception(['missing.swift'])
        self.rejected('existing regular file')
        self.exception(['App.swift'], target='W')
        self.rejected('not associated')
        self.objects['AG'].pop('exceptions')
        self.objects['AG']['explicitFolders'] = ['Nested']
        self.rejected('explicitFolders')

    def test_escape_variable_source_tree_and_generated_directory_fail_closed(self):
        for value in ('../outside', '$(SOURCES)', '/absolute', 'bad\\path'):
            with self.subTest(value=value):
                self.objects['AG']['path'] = value
                self.rejected('synchronized.*path')
        self.objects['AG']['path'] = '应用 Sources'
        self.objects['AG']['sourceTree'] = 'BUILT_PRODUCTS_DIR'
        self.rejected('sourceTree')
        self.objects['AG']['sourceTree'] = '<group>'
        self.put('应用 Sources/build/Generated.swift')
        self.rejected('outside the indexed source snapshot')

    def test_links_are_rejected_even_when_destination_is_inside_repository(self):
        # Windows developer mode/administrator rights are not required for this
        # deterministic link-detection branch test. core.snapshot also rejects
        # real links independently before membership resolution.
        original = Path.is_symlink
        def linked(path):
            return path.name == 'App.swift' or original(path)
        with patch.object(Path, 'is_symlink', linked):
            with self.assertRaisesRegex(MigrationError, 'links'):
                self.scope()

    def test_opaque_folder_compile_file_and_unowned_new_source_are_rejected(self):
        self.put('应用 Sources/Data.bundle/Hidden.swift')
        self.rejected('opaque or special folder')
        (self.root / '应用 Sources/Data.bundle/Hidden.swift').unlink()
        self.put('Elsewhere.swift')
        self.rejected('unowned compile')

    def test_ambiguous_unanchored_overlapping_roots_are_rejected(self):
        self.objects['OTHER'] = {'isa': 'PBXGroup', 'children': ['AG'], 'sourceTree': '<group>'}
        self.rejected('Ambiguous.*parents')
        del self.objects['OTHER']
        self.objects['G']['children'].remove('AG')
        self.rejected('anchored parent')
        self.objects['G']['children'].append('AG')
        self.objects['WG']['path'] = '应用 Sources/Nested'
        self.rejected('Overlapping')


if __name__ == '__main__':
    unittest.main()
