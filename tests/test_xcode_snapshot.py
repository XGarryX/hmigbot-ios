"""Generated Xcode metadata must not hide real project inputs."""
from pathlib import Path
import os
import plistlib
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('HMIGBOT_TEST_RUNTIME', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from hmigbot_ios.core import snapshot

SELF = b'<?xml version="1.0" encoding="UTF-8"?>\n<Workspace version="1.0"><FileRef location="self:"></FileRef></Workspace>\n'


class XcodeSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.put('App.swift', b'struct App {}\n')

    def put(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def fingerprint(self):
        return snapshot(self.root)['sha256']

    def test_default_project_workspace_creation_and_formatting_are_ignored(self):
        original = self.fingerprint()
        self.put('App.xcodeproj/project.xcworkspace/contents.xcworkspacedata', SELF)
        self.assertEqual(original, self.fingerprint())
        self.put('App.xcodeproj/project.xcworkspace/contents.xcworkspacedata',
                 b'<Workspace version="1.0">\n  <FileRef location="self:"/>\n</Workspace>')
        self.assertEqual(original, self.fingerprint())

    def test_real_embedded_workspace_references_are_tracked(self):
        self.put('App.xcodeproj/project.xcworkspace/contents.xcworkspacedata', SELF)
        original = self.fingerprint()
        self.put('App.xcodeproj/project.xcworkspace/contents.xcworkspacedata',
                 SELF.replace(b'</Workspace>', b'<FileRef location="group:Library.xcodeproj"/></Workspace>'))
        self.assertNotEqual(original, self.fingerprint())

    def test_known_ide_check_cache_is_ignored_but_unknown_plist_content_is_tracked(self):
        relative = 'App.xcodeproj/project.xcworkspace/xcshareddata/IDEWorkspaceChecks.plist'
        original = self.fingerprint()
        self.put(relative, plistlib.dumps({'IDEDidComputeMac32BitWarning': True}))
        self.assertEqual(original, self.fingerprint())
        self.put(relative, plistlib.dumps({'IDEDidComputeMac32BitWarning': True, 'OtherSetting': 'changed'}))
        self.assertNotEqual(original, self.fingerprint())
        self.put(relative, b'<?xml version="1.0"?><plist><dict>')
        self.assertNotEqual(original, self.fingerprint())

    def test_shared_schemes_lockfiles_settings_and_source_are_tracked(self):
        for relative in ('App.xcodeproj/project.pbxproj',
                         'App.xcodeproj/project.xcworkspace/xcshareddata/xcschemes/App.xcscheme',
                         'App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved',
                         'App.xcodeproj/project.xcworkspace/xcshareddata/WorkspaceSettings.xcsettings', 'App.swift'):
            with self.subTest(path=relative):
                original = self.fingerprint()
                self.put(relative, b'changed input')
                self.assertNotEqual(original, self.fingerprint())

    def test_standalone_workspace_is_never_classified_as_generated(self):
        original = self.fingerprint()
        self.put('App.xcworkspace/contents.xcworkspacedata', SELF)
        self.assertNotEqual(original, self.fingerprint())

    def test_user_state_is_ignored_only_inside_xcode_bundles(self):
        original = self.fingerprint()
        for folder in ('App.xcodeproj/xcuserdata', 'App.xcodeproj/project.xcworkspace/xcuserdata', 'App.xcworkspace/xcuserdata'):
            self.put(folder + '/person.xcuserdatad/UserInterfaceState.xcuserstate', b'user state')
            self.put(folder + '/person.xcuserdatad/xcschemes/xcschememanagement.plist', plistlib.dumps({'SchemeUserState': {}}))
        self.assertEqual(original, self.fingerprint())
        self.put('Sources/xcuserdata/Model.swift', b'struct Model {}')
        self.assertNotEqual(original, self.fingerprint())
        original = self.fingerprint()
        self.put('App.xcodeproj/Sources/xcuserdata/Model.swift', b'struct NestedModel {}')
        self.assertNotEqual(original, self.fingerprint())

    def test_user_scheme_and_unknown_user_metadata_are_still_inputs(self):
        for relative in ('App.xcodeproj/xcuserdata/person.xcuserdatad/xcschemes/Local.xcscheme',
                         'App.xcworkspace/xcuserdata/person.xcuserdatad/WorkspaceSettings.xcsettings',
                         'App.xcodeproj/xcuserdata/person.xcuserdatad/Sources/Model.swift'):
            original = self.fingerprint()
            self.put(relative, b'meaningful local input')
            self.assertNotEqual(original, self.fingerprint())

    def test_unknown_xml_and_nonstandard_self_workspaces_are_tracked(self):
        for content in (b'<Workspace', b'<Workspace version="1.0"/>',
                        b'<Workspace version="1.0" custom="yes"><FileRef location="self:"/></Workspace>',
                        b'<Workspace version="1.0"><FileRef location="self:">extra</FileRef></Workspace>',
                        b'<!DOCTYPE Workspace [<!ENTITY x "self:">]><Workspace version="1.0"><FileRef location="&x;"/></Workspace>'):
            with self.subTest(content=content):
                self.put('App.xcodeproj/project.xcworkspace/contents.xcworkspacedata', SELF)
                original = self.fingerprint()
                self.put('App.xcodeproj/project.xcworkspace/contents.xcworkspacedata', content)
                self.assertNotEqual(original, self.fingerprint())


if __name__ == '__main__':
    unittest.main()
