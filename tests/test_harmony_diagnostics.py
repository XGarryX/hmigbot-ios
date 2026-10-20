"""Synthetic-log tests for hmigbot_ios.harmony_diagnostics.

All logs below are synthetic: modeled on DevEco/hvigor output formats from the
local arkts-error-fixes and deveco-studio-hvigor skills. No real-device or
real-project HarmonyOS build capture was available, so this file validates the
parser contract (status semantics, exact log line pinning, redaction,
read-only behavior, hash drift detection) against crafted fixtures only.
"""
import json
import os

import pytest

import hmigbot_ios.harmony_diagnostics as hd
from hmigbot_ios.core import MigrationError, digest
from hmigbot_ios.harmony_diagnostics import analyze, save_report, verify


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_arkts_rule_code_with_location(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "> hvigor INFO: start\n"
                    "ERROR: ArkTS:ERROR File: D:\\demo\\entry\\src\\main\\ets\\pages\\Index.ets:12:5\n"
                    " Using 'this' in standalone functions is not allowed (arkts-no-standalone-this)\n"
                    "BUILD FAILED in 3s\n")
    report = analyze(stdout, None, 1)
    assert report["status"] == "fail_with_errors"
    assert report["build_command_passed"] is False
    assert report["markers"]["build_failed"] is True
    finding = report["findings"][0]
    assert finding["severity"] == "error"
    assert finding["tool"] == "arkts"
    assert finding["error_code"] == "arkts-no-standalone-this"
    assert finding["file"] == "D:\\demo\\entry\\src\\main\\ets\\pages\\Index.ets"
    assert finding["line"] == 12
    assert finding["column"] == 5
    assert finding["category"] == "arkts_syntax"
    assert finding["confidence"] == "high"
    assert "arkts-error-fixes" in finding["basis"]
    assert finding["suggestion"].startswith("D:\\demo\\entry\\src\\main\\ets\\pages\\Index.ets:12:5:")
    assert "context" in finding["suggestion"]
    assert finding["log_ref"] == {"stream": "stdout", "line": 2, "end_line": 3}


def test_object_literal_interface_error(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: ArkTS:ERROR File: /demo/entry/src/main/ets/viewmodel/Model.ets:8:1\n"
                    " Object literal must correspond to some explicitly declared class or interface\n")
    report = analyze(stdout, None, 1)
    finding = report["findings"][0]
    assert finding["category"] == "arkts_type"
    assert finding["confidence"] == "high"
    assert "Object Literal Interface Errors" in finding["basis"]
    assert "interface" in finding["suggestion"]
    assert finding["file"] == "/demo/entry/src/main/ets/viewmodel/Model.ets"


def test_unknown_error_stays_unknown(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: Something completely novel happened in widget pipeline\n")
    report = analyze(stdout, None, 1)
    assert report["status"] == "fail_with_errors"
    finding = report["findings"][0]
    assert finding["category"] == "unknown"
    assert finding["tool"] == "unknown"
    assert finding["error_code"] is None
    assert finding["suggestion"] is None
    assert finding["confidence"] == "low"


def test_unmapped_arkts_code_reported_literally(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: ArkTS:ERROR File: D:\\p\\entry\\src\\main\\ets\\pages\\C.ets:2:1\n"
                    " text (arkts-no-weird-unknown-rule)\n")
    report = analyze(stdout, None, 1)
    finding = report["findings"][0]
    assert finding["error_code"] == "arkts-no-weird-unknown-rule"
    assert finding["category"] == "arkts_lint"
    assert finding["confidence"] == "medium"
    assert "arkts-no-weird-unknown-rule" in finding["suggestion"]


def test_nonzero_without_parseable_error_never_passes(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "hello world\nhvigor ran fine\n")
    report = analyze(stdout, None, 1)
    assert report["findings"] == []
    assert report["status"] == "fail_unparsed"
    assert report["build_command_passed"] is False
    assert any("never reported as PASS" in note for note in report["status_notes"])


def test_none_returncode_never_passes(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Install failed.\n")
    report = analyze(stdout, None, None)
    assert report["returncode"] is None
    assert report["build_command_passed"] is False
    assert report["status"] == "fail_with_errors"


def test_zero_returncode_is_build_command_only(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "BUILD SUCCESSFUL in 4s\n")
    report = analyze(stdout, None, 0, target={"module": "entry", "module_target": "default"})
    assert report["status"] == "build_command_passed"
    assert report["build_command_passed"] is True
    assert report["functional_verified"] is False
    assert report["ui_verified"] is False
    assert report["target"] == {"module": "entry", "module_target": "default"}
    assert any("NOT verified" in note for note in report["status_notes"])


def test_zero_returncode_with_log_errors(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "BUILD SUCCESSFUL in 4s\n"
                    "ERROR: post-build cleanup hook failed\n")
    report = analyze(stdout, None, 0)
    assert report["status"] == "conflicting_build_evidence"
    assert report["build_command_passed"] is False
    assert report["process_exit_zero"] is True
    assert report["overall_status"] == "conflict"
    assert report["summary"]["errors"] == 1


def test_hvigor_model_version_error(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: Unsupported modelVersion of Hvigor 6.1.0.\n"
                    "The supported Hvigor modelVersion is 6.0.2.\n")
    report = analyze(stdout, None, 1)
    finding = report["findings"][0]
    assert finding["category"] == "sdk_api"
    assert finding["confidence"] == "high"
    assert "deveco-studio-hvigor" in finding["basis"]
    assert "hvigor-config.json5" in finding["suggestion"]
    assert "build-profile.json5" in finding["suggestion"]
    assert finding["log_ref"] == {"stream": "stdout", "line": 1, "end_line": 2}


def test_signing_error_and_secret_redaction(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: Init keystore failed\n"
                    "Error Message: parseAlgParameters failed\n"
                    "storePassword=SuperSecret123\n"
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    "MIIfakekeybodyline\n"
                    "-----END RSA PRIVATE KEY-----\n"
                    "token: ghp_abcdefghijklmnop1234567890\n"
                    "BUILD FAILED in 2s\n")
    report = analyze(stdout, None, 1)
    serialized = json.dumps(report, ensure_ascii=False)
    assert "SuperSecret123" not in serialized
    assert "ghp_abcdefghijklmnop" not in serialized
    assert "MIIfakekeybody" not in serialized
    assert report["redacted_lines"] == 3
    assert any("redacted" in note for note in report["status_notes"])
    first, second = report["findings"][0], report["findings"][1]
    assert first["message"] == "Init keystore failed"
    assert first["category"] == "signing"
    assert first["tool"] == "signing"
    assert second["category"] == "signing"
    assert "[REDACTED:credential-like line]" in second["message"]
    assert "[REDACTED:private-key-block]" in second["message"]
    assert second["log_ref"]["end_line"] == 7


def test_bearer_token_redacted_inline(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: upload failed Authorization: Bearer abc123def456.err\n")
    report = analyze(stdout, None, 1)
    serialized = json.dumps(report, ensure_ascii=False)
    assert "abc123def456" not in serialized
    assert "[REDACTED:credential-like line]" in report["findings"][0]["message"]


def test_hvigorw_not_recognized_bare_line(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "Building HAP via hvigorw\n"
                    "'hvigorw' is not recognized as an internal or external command\n")
    report = analyze(stdout, None, 1)
    finding = report["findings"][0]
    assert finding["category"] == "hvigor"
    assert finding["tool"] == "hvigor"
    assert finding["confidence"] == "high"
    assert "hvigorw.js" in finding["suggestion"]
    assert "--no-daemon" in finding["suggestion"]
    assert "deveco-studio-hvigor" in finding["basis"]
    assert finding["log_ref"] == {"stream": "stdout", "line": 2, "end_line": 2}


def test_ohpm_install_failed_numeric_code(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: Install failed.\n"
                    "Error code:404\n"
                    "Not Found: @scope/pkg\n")
    report = analyze(stdout, None, 1)
    finding = report["findings"][0]
    assert finding["error_code"] == "404"
    assert finding["category"] == "module_dependency"
    assert finding["tool"] == "ohpm"
    assert finding["log_ref"] == {"stream": "stdout", "line": 1, "end_line": 3}


def test_missing_ohos_module_is_sdk_api(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: ArkTS:ERROR File: D:\\p\\entry\\src\\main\\ets\\pages\\Index.ets:3:1\n"
                    " Cannot find module '@ohos.multimedia.unknownKit'\n")
    report = analyze(stdout, None, 1)
    finding = report["findings"][0]
    assert finding["category"] == "sdk_api"
    assert "compatibleSdkVersion" in finding["suggestion"]
    assert finding["tool"] == "arkts"
    assert finding["error_code"] is None


def test_unicode_and_windows_paths(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: ArkTS:ERROR File: D:\\测试项目\\entry\\src\\main\\ets\\pages\\页面.ets:3:1\n"
                    " 类型“number”不能分配给类型“string”\n"
                    "ERROR: ArkTS:ERROR File: D:\\My Projects\\app\\entry\\src\\main\\ets\\Index.ets:1:1\n"
                    " Cannot find name 'foo'\n")
    report = analyze(stdout, None, 1)
    first, second = report["findings"][0], report["findings"][1]
    assert first["file"] == "D:\\测试项目\\entry\\src\\main\\ets\\pages\\页面.ets"
    assert first["line"] == 3
    assert "类型" in first["message"]
    assert first["category"] == "unknown"
    assert second["file"] == "D:\\My Projects\\app\\entry\\src\\main\\ets\\Index.ets"
    assert second["category"] == "arkts_type"
    path = save_report(report, tmp_path / "reports" / "diag.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["findings"][0]["file"] == "D:\\测试项目\\entry\\src\\main\\ets\\pages\\页面.ets"


def test_catch_clause_and_possibly_null(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: ArkTS:ERROR File: D:\\p\\entry\\src\\main\\ets\\pages\\A.ets:5:1\n"
                    " Catch clause variable cannot have a type annotation\n"
                    "ERROR: ArkTS:ERROR File: D:\\p\\entry\\src\\main\\ets\\pages\\B.ets:6:1\n"
                    " Object is possibly 'null'\n")
    report = analyze(stdout, None, 1)
    first, second = report["findings"][0], report["findings"][1]
    assert first["category"] == "arkts_syntax"
    assert "Remove the type annotation" in first["suggestion"]
    assert "Catch Clause Type Errors" in first["basis"]
    assert second["category"] == "arkts_type"
    assert "optional chaining" in second["suggestion"]
    assert "Possibly Null Errors" in second["basis"]


def test_finding_target_extracted_when_present(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: Assemble task failed for module entry@default\n")
    report = analyze(stdout, None, 1)
    assert report["findings"][0]["target"] == "entry@default"


def test_warning_does_not_fail_successful_build(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "WARNING: 'x' is declared but its value is never read\n"
                    "BUILD SUCCESSFUL in 2s\n")
    report = analyze(stdout, None, 0)
    assert report["status"] == "build_command_passed"
    finding = report["findings"][0]
    assert finding["severity"] == "warning"
    assert finding["category"] == "arkts_lint"
    assert "hilog" in finding["suggestion"]
    assert report["summary"]["warnings"] == 1
    assert report["summary"]["errors"] == 0


def test_logs_are_read_only(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Install failed.\n")
    stderr = _write(tmp_path / "stderr.log", "ERROR: something in stderr\n")
    before = (digest(stdout.read_bytes()), digest(stderr.read_bytes()))
    report = analyze(stdout, stderr, 1)
    save_report(report, tmp_path / "out" / "report.json")
    assert (digest(stdout.read_bytes()), digest(stderr.read_bytes())) == before


def test_verify_detects_log_changes(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Install failed.\n")
    stderr = _write(tmp_path / "stderr.log", "note\n")
    report = analyze(stdout, stderr, 1)
    assert verify(report) is True
    stdout.write_text("ERROR: Install failed.\nERROR: another failure\n", encoding="utf-8")
    assert verify(report) is False


def test_verify_false_when_log_deleted(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "BUILD SUCCESSFUL in 1s\n")
    stderr = _write(tmp_path / "stderr.log", "note\n")
    report = analyze(stdout, stderr, 0)
    stderr.unlink()
    assert verify(report) is False


def test_stderr_stream_recorded(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "BUILD SUCCESSFUL in 1s\n")
    stderr = _write(tmp_path / "stderr.log", "ERROR: linker step failed\n")
    report = analyze(stdout, stderr, 1)
    finding = report["findings"][0]
    assert finding["log_ref"]["stream"] == "stderr"
    assert report["logs"]["stderr"]["sha256"] == digest(stderr.read_bytes())
    assert report["logs"]["stderr"]["bytes"] == len(stderr.read_bytes())


def test_exact_log_line_references(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "info line one\n"
                    "info line two\n"
                    "ERROR: ArkTS:ERROR File: D:\\p\\Index.ets:10:20\n"
                    " rule text here\n"
                    "\n"
                    "ERROR: tail\n")
    report = analyze(stdout, None, 1)
    first, second = report["findings"][0], report["findings"][1]
    assert first["log_ref"] == {"stream": "stdout", "line": 3, "end_line": 4}
    assert second["log_ref"] == {"stream": "stdout", "line": 6, "end_line": 6}


def test_findings_cap_and_truncation(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "\n".join("ERROR: failure %d" % i for i in range(300)) + "\n")
    report = analyze(stdout, None, 1)
    assert len(report["findings"]) == 200
    assert report["summary"]["truncated"] is True
    assert any("truncated" in note for note in report["status_notes"])


def test_binary_garbage_and_empty_logs(tmp_path):
    stdout = tmp_path / "stdout.log"
    stdout.write_bytes(b"\xff\xfe\x00garbage\x01")
    report = analyze(stdout, None, 1)
    assert report["status"] == "fail_unparsed"
    assert report["findings"] == []
    assert report["logs"]["stdout"]["bytes"] == 11
    empty = tmp_path / "empty.log"
    empty.write_bytes(b"")
    report = analyze(empty, None, 0)
    assert report["status"] == "build_command_passed"
    assert report["findings"] == []


def test_api_contract_and_no_subprocess(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Install failed.\n")
    report = analyze(stdout, None, 1)
    assert report["api_contract"] == {"reads_logs_only": True, "edits_source": False,
                                      "edits_signing": False, "device_operations": False,
                                      "network_access": False, "model_api_calls": False}
    module_vars = vars(hd)
    assert "subprocess" not in module_vars
    assert "socket" not in module_vars
    assert "requests" not in module_vars


def test_limitations_disclose_synthetic_validation(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Install failed.\n")
    report = analyze(stdout, None, 1)
    assert any("synthetic" in item.lower() for item in report["limitations"])
    assert any("returncode=0" in item for item in report["limitations"])


def test_report_determinism_and_roundtrip(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    "ERROR: Unsupported modelVersion of Hvigor 6.1.0.\n"
                    "The supported Hvigor modelVersion is 6.0.2.\n")
    stderr = _write(tmp_path / "stderr.log", "note\n")
    first = analyze(stdout, stderr, 1)
    second = analyze(stdout, stderr, 1)
    first.pop("generated_at")
    second.pop("generated_at")
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(second, sort_keys=True, ensure_ascii=False)
    path = save_report(first, tmp_path / "reports" / "diag.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["report_kind"] == "harmony_build_diagnostics"
    assert loaded["schema_version"] == "hmigbot-ios/1"
    assert verify(loaded) is True


def test_invalid_inputs_raise(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Install failed.\n")
    with pytest.raises(MigrationError):
        analyze(None, None, 1)
    with pytest.raises(MigrationError):
        analyze(tmp_path / "missing.log", None, 0)
    with pytest.raises(MigrationError):
        analyze(stdout, None, 0, target="entry")
    with pytest.raises(MigrationError):
        analyze(stdout, None, returncode="1")
    with pytest.raises(MigrationError):
        verify({})
    with pytest.raises(MigrationError):
        verify({"report_kind": "harmony_build_diagnostics", "logs": {}})


@pytest.mark.parametrize("line", [
    'ERROR: signing failed "storePassword": "synthetic password with spaces"',
    "ERROR: signing failed 'keyPassword' = 'synthetic password with spaces'",
    'ERROR: upload --token "synthetic token with spaces"',
    'ERROR: upload api_key=synthetic token with spaces',
    'ERROR: upload {"Authorization": "Basic synthetic secret with spaces"}',
    'ERROR: upload Cookie: session=synthetic secret with spaces',
])
def test_quoted_inline_and_space_values_redact_entire_sensitive_line(tmp_path, line):
    stdout = _write(tmp_path / "stdout.log", line + "\n")
    report = analyze(stdout, returncode=1)
    serialized = json.dumps(report["findings"])
    assert "synthetic" not in serialized
    assert report["redacted_lines"] == 1
    assert report["findings"][0]["message"] == "[REDACTED:credential-like line]"


def test_sensitive_file_header_does_not_leak_into_file_or_suggestion(tmp_path):
    stdout = _write(tmp_path / "stdout.log",
                    'ERROR: ArkTS:ERROR File: D:/token=synthetic-header-secret/Index.ets:1:1\n'
                    " Cannot find name 'x'\n")
    report = analyze(stdout, returncode=1)
    assert "synthetic-header-secret" not in json.dumps(report)
    assert report["findings"][0]["file"] is None


@pytest.mark.parametrize("target", [
    {"token": "synthetic sensitive value"},
    {"module": "Bearer synthetic sensitive value"},
    {"module": "ghp_" + "a" * 20},
    {"module": 123}, {"module": False}, {"module": float("nan")},
])
def test_target_is_identity_allowlist_not_arbitrary_scalar_passthrough(tmp_path, target):
    stdout = _write(tmp_path / "stdout.log", "BUILD SUCCESSFUL\n")
    with pytest.raises(MigrationError) as exc:
        analyze(stdout, returncode=0, target=target)
    assert "synthetic" not in str(exc.value)
    assert "ghp_" not in str(exc.value)


@pytest.mark.parametrize("text", [
    "BUILD FAILED in 2 s\n", "BUILD SUCCESSFUL\nBUILD FAILED\n",
    "> hvigor ERROR: task failed\n", "FATAL: unknown fatal failure\n",
])
def test_zero_exit_with_failed_or_error_markers_is_conflict_not_acceptance(tmp_path, text):
    stdout = _write(tmp_path / "stdout.log", text)
    report = analyze(stdout, returncode=0)
    assert report["process_exit_zero"] is True
    assert report["status"] == "conflicting_build_evidence"
    assert report["overall_status"] == "conflict"
    assert report["build_command_passed"] is False


def test_report_cannot_overwrite_either_log_or_hardlink_alias(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: signing failed\n")
    stderr = _write(tmp_path / "stderr.log", "ERROR: stderr evidence\n")
    report = analyze(stdout, stderr, 1)
    aliases = []
    for index, source in enumerate((stdout, stderr)):
        alias = tmp_path / ("hardlink-%d.json" % index)
        os.link(source, alias)
        aliases.append(alias)
    before = {path: path.read_bytes() for path in (stdout, stderr)}
    for out in (stdout, stderr, *aliases):
        with pytest.raises(MigrationError, match="overwrite.*input log"):
            save_report(report, out)
        assert before == {path: path.read_bytes() for path in before}
    destination = tmp_path / "diagnostics.json"
    save_report(report, destination)
    save_report(report, destination)  # An existing derived report remains replaceable.
    assert verify(json.loads(destination.read_text(encoding="utf-8")))


def test_signing_advice_preserves_real_configuration(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "ERROR: Init keystore failed\n")
    suggestion = analyze(stdout, returncode=1)["findings"][0]["suggestion"]
    assert "preserve existing signingConfigs" in suggestion
    assert "clearing signingConfigs" not in suggestion
    assert "read-only" in suggestion
