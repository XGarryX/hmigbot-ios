"""E166（AIPPT_930 移植）：parser 与 agent-output.schema.json 口径一致——
findings 可选 notes[]（非缺陷/非验收）；fix 可选 sdk_skills_read[]/resolved_refs[]（只申报）、required_owner 允许域 key 简写；
impl（wiring/closure 复用 domainImpl）任务 id 合法、skipped[] 保留原 BK 引用与原因、不代表销账；旧回执照常合法。"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SCHEMA = SCRIPTS.parents[2] / "schemas" / "agent-output.schema.json"


class AuditNotesOutputTest(unittest.TestCase):
    def run_parser(self, payload, schema="findings"):
        with tempfile.TemporaryDirectory() as td:
            sample = Path(td) / "sample.json"
            sample.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run([sys.executable, str(SCRIPTS / "parse_agent_output.py"),
                                   "--schema", schema, "--raw-json", "--file", str(sample), "--json"],
                                  capture_output=True, text=True, timeout=30)

    def test_notes_survive_without_creating_findings_or_acceptance(self):
        notes = ["AC-1 静态 PASS: source:12 与 target:15 分支一致；设备未验证",
                 "AC-2 无法静态验证: missing credentials，保留 blocked"]
        result = self.run_parser({"domain": "sample", "findings": [], "notes": notes})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["notes"], notes)
        self.assertEqual(payload["findings"], [])
        self.assertNotIn("acceptance", payload)
        self.assertNotIn("approved", payload)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))["definitions"]["auditFindings"]
        self.assertNotIn("notes", schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["notes"]["items"]["type"], "string")

    def test_legacy_receipt_remains_valid(self):
        result = self.run_parser({"domain": "sample", "findings": []})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["notes"], [])

    def test_object_notes_are_rejected(self):
        result = self.run_parser({"domain": "sample", "findings": [], "notes": [{"approved": True}]})
        self.assertNotEqual(result.returncode, 0)

    def test_fix_metadata_is_only_a_declaration(self):
        payload = {"domain": "sample", "fixed": [], "skipped": [], "files_touched": [],
                   "resolved_refs": ["P-DOM-SAMPLE-001"], "sdk_skills_read": ["arkts-state-manager"]}
        result = self.run_parser(payload, "fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["resolved_refs"], payload["resolved_refs"])
        self.assertEqual(output["sdk_skills_read"], payload["sdk_skills_read"])
        self.assertNotIn("resolved", output)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))["definitions"]["fixResult"]
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("resolved_refs", schema["required"])
        self.assertNotIn("sdk_skills_read", schema["required"])
        owner_pattern = schema["properties"]["skipped"]["items"]["properties"]["required_owner"]["pattern"]
        for owner in ["seed", "mainloop", "infra:common-basis", "domain:app-recommend", "app-recommend"]:
            self.assertIsNotNone(re.fullmatch(owner_pattern, owner))
        self.assertIsNone(re.fullmatch(owner_pattern, "mainloop or other owner"))

    def test_invalid_fix_metadata_is_rejected(self):
        result = self.run_parser({"domain": "sample", "fixed": [], "skipped": [],
                                  "resolved_refs": [{"resolved": True}], "sdk_skills_read": "guessed"}, "fix")
        self.assertNotEqual(result.returncode, 0)

    def test_wiring_skipped_keeps_original_reference_without_resolving(self):
        payload = {'task': 'wiring:infra:sample', 'final_state': 'PASS', 'files': [],
                   'skipped': [{'finding_ref': 'BK-7', 'reason': 'consumer outside owner', 'required_owner': 'app-page'}]}
        result = self.run_parser(payload, 'impl')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['skipped'], payload['skipped'])
        self.assertEqual(output['resolved_refs'], [])
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))['definitions']['domainImpl']
        self.assertNotIn('skipped', schema['required'])
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('required_owner', schema['properties']['skipped']['items']['required'])
        for task in (payload['task'], 'closure:r3:domain:app-one', 'domain:app-one'):
            self.assertIsNotNone(re.fullmatch(schema['properties']['task']['pattern'], task))

    def test_invalid_wiring_skipped_is_rejected_and_legacy_impl_works(self):
        base = {'task': 'domain:sample', 'final_state': 'PASS', 'files': []}
        self.assertEqual(self.run_parser(base, 'impl').returncode, 0)
        # 做不了但不转交：finding_ref + reason 即合法（backlog_settle 保持原 owner open）
        self.assertEqual(self.run_parser({**base, 'skipped': [{'finding_ref': 'BK-7', 'reason': 'gap'}]}, 'impl').returncode, 0)
        # E243：校验器只查 finding_ref 形状；编造 ID 是否真实由 land_results 按本任务书精确匹配（对不上只告警）
        self.assertEqual(self.run_parser({**base, 'skipped': [{'finding_ref': 'invented', 'reason': 'gap',
                                                                  'required_owner': 'seed'}]}, 'impl').returncode, 0)
        for item in ({'finding_ref': 'BK-7'},
                     {'finding_ref': 0, 'reason': 'gap', 'required_owner': 'seed'}):
            self.assertNotEqual(self.run_parser({**base, 'skipped': [item]}, 'impl').returncode, 0)


if __name__ == "__main__":
    unittest.main()
