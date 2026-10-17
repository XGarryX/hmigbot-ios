"""E170（AIPPT_930 移植）：verify_wires.consumer_files 沿真实使用的本地 import 图追到委托导航的提供方
（MemberPage → MemberVM → BaseMemberVM.pay() 的 pushPathByName）；未使用/type-only/外部包不跟，环有界。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import verify_wires as V  # noqa: E402


class DelegatedConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_real_transitive_host_navigation_is_found(self):
        self.write('pages/MemberPage.ets', "import { MemberVM } from '../features/member/MemberVM';\nconst vm = new MemberVM(); vm.pay();")
        self.write('features/member/MemberVM.ets', "import { BaseMemberVM } from '../../infra/pay/BaseMemberVM';\nexport class MemberVM extends BaseMemberVM {}")
        provider = self.write('infra/pay/BaseMemberVM.ets', "export class BaseMemberVM { pay() { this.host.stack.pushPathByName('H5Page', params); } }")
        files = V.consumer_files(self.root, 'MemberPage', 'member')
        self.assertIn(provider, files)
        self.assertTrue(V.consumer_pushes(files, 'H5Page'))

    def test_unused_import_does_not_prove_navigation(self):
        self.write('pages/MemberPage.ets', "import { UnusedVM } from '../infra/pay/UnusedVM';\nconst local = 1;")
        self.write('infra/pay/UnusedVM.ets', "export class UnusedVM { pay() { stack.pushPathByName('H5Page', params); } }")
        self.assertFalse(V.consumer_pushes(V.consumer_files(self.root, 'MemberPage', None), 'H5Page'))

    def test_unrelated_provider_not_scanned(self):
        self.write('pages/MemberPage.ets', 'const local = 1;')
        self.write('infra/pay/OtherVM.ets', "stack.pushPathByName('H5Page', params);")
        self.assertFalse(V.consumer_pushes(V.consumer_files(self.root, 'MemberPage', None), 'H5Page'))

    def test_cycles_are_bounded(self):
        self.write('pages/A.ets', "import { b } from './B';\nb();")
        self.write('pages/B.ets', "import { a } from './A';\na();")
        self.assertEqual(len(V.consumer_files(self.root, 'A', None)), 2)

    def test_external_and_type_only_imports_not_followed(self):
        self.write('pages/A.ets', "import type { B } from './B';\nimport { C } from '@vendor/c';\nconst value: B = undefined; C();")
        self.write('pages/B.ets', "stack.pushPathByName('H5Page', params);")
        self.assertEqual(len(V.consumer_files(self.root, 'A', None)), 1)


if __name__ == '__main__':
    unittest.main()
