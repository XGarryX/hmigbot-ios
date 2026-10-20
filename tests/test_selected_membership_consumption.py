from test_source_build_membership import MembershipBase
from hmigbot_ios.core import MigrationError, digest, read_json, write_json
from hmigbot_ios.evidence import pack
from hmigbot_ios.ios_facts import extract, refresh, validate_graph


class SelectedMembershipConsumptionTests(MembershipBase):
    def capture_bundle(self):
        self.standard_build()
        document = self.collect()
        assert document['membership_status'] == 'complete'
        bundle = self.root / 'evidence'
        pack(self.source, self.capture, bundle, 'source_build', 'synthetic Xcode fixture')
        return document, bundle

    def variant(self, document, bundle):
        return {'scope': 'selected-build', 'source_files': document['source_files'],
                'evidence_path': str(bundle)}

    def test_compiler_inputs_are_consumed_and_identity_is_pinned(self):
        document, bundle = self.capture_bundle()
        project = self.root / 'target'
        project.mkdir()
        graph = refresh(project, self.source, self.variant(document, bundle))
        variant = graph['variant']
        self.assertEqual(variant['selection'], document['selection'])
        self.assertEqual(variant['source_membership'], 'captured_compiler_inputs')
        self.assertEqual(variant['effective_build'], 'unresolved')
        self.assertEqual(variant['evidence_manifest_sha256'], digest((bundle / 'manifest.json').read_bytes()))
        self.assertEqual(variant['membership_sha256'], digest((bundle / 'artifacts/source-files.json').read_bytes()))
        self.assertEqual(graph['capabilities']['effective_build'], 'unresolved')
        self.assertNotIn('App/Unused.swift', {f['anchor']['path'] for f in graph['facts']})
        self.assertEqual(validate_graph(self.source, project)[0], graph)

    def test_requested_identity_cannot_conflict_with_capture(self):
        document, bundle = self.capture_bundle()
        for changed in ({'configuration': 'Debug'}, {'targets': ['App']}, {'sdk': 'iphonesimulator'},
                        {'target': 'App'}, {'selection': {'scheme': 'Other'}},
                        {'membership_sha256': '0' * 64}, {'effective_build': 'verified'}):
            with self.subTest(changed=changed), self.assertRaises(MigrationError):
                extract(self.source, {**self.variant(document, bundle), **changed})

    def test_incomplete_contract_cannot_reduce_the_fact_denominator(self):
        document, _ = self.capture_bundle()
        document['membership_status'] = 'incomplete'
        document['unresolved'] = [{'reason': 'synthetic missing input', 'path': None, 'detail': 'not captured'}]
        write_json(self.capture / 'source-files.json', document)
        bundle = self.root / 'incomplete'
        pack(self.source, self.capture, bundle, 'source_build', 'synthetic Xcode fixture')
        with self.assertRaises(MigrationError):
            extract(self.source, self.variant(document, bundle))

    def test_wrong_modern_kind_cannot_be_treated_as_legacy(self):
        document, _ = self.capture_bundle()
        document['kind'] = 'unrecognized_membership'
        write_json(self.capture / 'source-files.json', document)
        bundle = self.root / 'wrong-kind'
        pack(self.source, self.capture, bundle, 'source_build', 'synthetic Xcode fixture')
        with self.assertRaises(MigrationError):
            extract(self.source, self.variant(document, bundle))

    def test_modified_raw_capture_rejected_after_manifest_rehash(self):
        document, bundle = self.capture_bundle()
        filelist = next((bundle / 'artifacts/filelists').glob('*'))
        filelist.write_bytes(b'/not-in-the-original-capture.swift\n')
        manifest = read_json(bundle / 'manifest.json')
        manifest['artifacts'][filelist.relative_to(bundle).as_posix()] = digest(filelist.read_bytes())
        write_json(bundle / 'manifest.json', manifest)
        with self.assertRaises(MigrationError):
            extract(self.source, self.variant(document, bundle))

    def test_legacy_source_files_only_bundle_remains_readable(self):
        document, _ = self.capture_bundle()
        write_json(self.capture / 'source-files.json', {'source_files': document['source_files']})
        bundle = self.root / 'legacy'
        pack(self.source, self.capture, bundle, 'source_build', 'legacy fixture')
        graph = extract(self.source, self.variant(document, bundle))
        self.assertNotIn('source_membership', graph['variant'])
        self.assertEqual(graph['capabilities']['effective_build'], 'unresolved')
