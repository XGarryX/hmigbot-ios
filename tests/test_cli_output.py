"""Encoding failures must not turn a completed capture into a reported failure."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hmigbot_ios.cli_output import emit_json


class JsonOutputTests(unittest.TestCase):
    def test_embedded_string_stream(self):
        stream = io.StringIO()
        emit_json({'name': '中文 🧭'}, stream=stream)
        self.assertEqual(json.loads(stream.getvalue()), {'name': '中文 🧭'})

    def test_fixed_legacy_encoding_uses_lossless_json(self):
        class FixedGBK:
            def __init__(self):
                self.data = bytearray()

            def reconfigure(self, **kwargs):
                raise ValueError('fixed encoding')

            def write(self, text):
                encoded = text.encode('gbk')
                self.data.extend(encoded)
                return len(text)

        stream = FixedGBK()
        emit_json({'name': '中文 🧭'}, stream=stream)
        self.assertEqual(json.loads(stream.data.decode('utf-8')), {'name': '中文 🧭'})

    def test_native_capture_in_gbk_environment(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source, project = work / 'ios', work / 'harmony'
            source.mkdir()
            project.mkdir()
            (source / '界面.swift').write_text('import SwiftUI\nstruct Main: View { var body: some View { Text("🧭导航") } }\n', encoding='utf-8')
            env = {**os.environ, 'PYTHONPATH': str(root / 'src'),
                   'PYTHONIOENCODING': 'gbk', 'PYTHONDONTWRITEBYTECODE': '1'}
            for args in [
                ['init', '--source', str(source), '--project', str(project)],
                ['source-index', '--project', str(project)],
                ['facts', '--project', str(project)],
            ]:
                command = [sys.executable, '-B', '-c',
                           'from hmigbot_ios.native_pipeline import main; raise SystemExit(main())', *args]
                result = subprocess.run(command, capture_output=True, env=env, timeout=30)
                self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
                payload = json.loads(result.stdout.decode('utf-8'))
                self.assertNotEqual(payload.get('status'), 'FAIL')
            graph_path = project / 'spec/baseline/ios-facts.json'
            self.assertTrue(graph_path.exists())
            self.assertIn('🧭导航', graph_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
