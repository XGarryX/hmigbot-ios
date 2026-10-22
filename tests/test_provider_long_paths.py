"""Real Windows provider IO beyond MAX_PATH; contract names stay portable."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from hmigbot_ios.atoms import run_atom
from hmigbot_ios.core import digest, io_path, read_json, snapshot, write_json
from hmigbot_ios.ios_facts import refresh, validate_graph
from hmigbot_ios.provider_runs import ProviderRun, retained_failures


@unittest.skipUnless(os.name == 'nt', 'Windows provider extended-length IO')
class ProviderLongPathTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='provider-long-'))
        self.addCleanup(shutil.rmtree, io_path(self.root))
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'App.swift').write_text('struct App {}\n', encoding='utf-8')
        self.project = self.root.joinpath(*(['nested-' + 'p' * 42] * 5), 'target')
        self.assertGreater(len(str(self.project)), 260)
        io_path(self.project).mkdir(parents=True)

    def test_reserve_real_atom_publish_and_failure_records_use_extended_io(self):
        source_hash = snapshot(self.source)['sha256']
        run = ProviderRun(self.project, 'interface-builder', source_hash)
        run.reserve()
        with run.fixed_inputs() as (config, bundle):
            report = run_atom('interface-builder', self.source, run.directory,
                              provider_config=config, input_path=bundle)
            artifact = run.publish(report)
        self.assertEqual(artifact['run']['attempt'], 1)
        self.assertFalse(artifact['path'].startswith('\\\\?\\'))
        self.assertNotIn('\\', artifact['path'])
        self.assertEqual(read_json(io_path(self.project / artifact['path'])), report)
        self.assertEqual(run.project, self.project)
        self.assertFalse(str(run.project).startswith('\\\\?\\'))
        later = ProviderRun(self.project, 'interface-builder', source_hash)
        later.reserve()
        later.fail('retained long-path failure')
        self.assertEqual(later.attempt, 2)
        self.assertEqual(read_json(later.failure_path)['status'], 'failed')

    def test_long_config_and_bundle_retry_round_trip_keep_portable_paths(self):
        config = self.project / 'provider-config.json'
        write_json(config, {})  # optional built-in config still binds the request identity
        bundle = io_path(self.project / 'bundle')
        payload = b'{"probe": true}\n'
        (bundle / 'artifacts').mkdir(parents=True)
        (bundle / 'artifacts/probe.json').write_bytes(payload)
        write_json(bundle / 'manifest.json', {'artifacts': {'artifacts/probe.json': digest(payload)}})
        plan = self.project / 'provider-plan.json'
        write_json(plan, {'schema_version': 2, 'providers': [{
            'operation': 'interface-builder', 'config': str(config), 'input': str(bundle)}]})
        source_hash = snapshot(self.source)['sha256']
        failed = ProviderRun(self.project, 'interface-builder', source_hash,
                             config=config, input_path=Path(str(bundle)))
        self.assertEqual(failed.config_sha256, digest(io_path(config).read_bytes()))
        self.assertEqual(failed.input_sha256, digest((bundle / 'manifest.json').read_bytes()))
        failed.reserve()
        failed.fail('first attempt retained')
        graph = refresh(self.project, self.source, provider_plan=plan)
        first = graph['provider_artifacts'][0]
        self.assertEqual(first['run']['attempt'], 2)
        self.assertEqual(validate_graph(self.source, self.project)[0], graph)
        artifact_path = self.project / first['path']  # normal Path input must work too
        self.assertEqual([item['attempt'] for item in retained_failures(artifact_path)], [1])
        third = ProviderRun(self.project, 'interface-builder', source_hash,
                            config=config, input_path=Path(str(bundle)))
        third.reserve()
        third.fail('third attempt retained')
        self.assertEqual(third.attempt, 3)
        # Later failures cannot silently expand an already-published graph.
        self.assertEqual(validate_graph(self.source, self.project)[0], graph)
        again = refresh(self.project, self.source, provider_plan=plan)
        final = again['provider_artifacts'][0]
        self.assertEqual(final['run']['attempt'], 4)
        self.assertEqual([item['attempt'] for item in retained_failures(self.project / final['path'])], [1, 3])
        self.assertEqual(validate_graph(self.source, self.project)[0], again)
        self.assertNotIn('\\\\?\\', json.dumps(again))
        self.assertNotIn('\\\\?\\', final['path'])


if __name__ == '__main__':
    unittest.main()
