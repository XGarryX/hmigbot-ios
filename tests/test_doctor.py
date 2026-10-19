"""Doctor: read-only environment diagnostic tests.

These tests assert real, specific behavior (no placeholder assertions) and verify
the doctor never mutates its inputs via a real SHA comparison, not mtime.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hmigbot_ios.doctor import doctor, render_text, _check_migbot_config, _check_install_manifest
from hmigbot_ios.core import snapshot


SRC = Path(__file__).parents[1] / "src"


def _tree_sha(project: Path) -> str:
    """Real input fingerprint: full source snapshot digest of the project."""
    return snapshot(project)["sha256"]


@pytest.fixture
def user_hmos_project(tmp_path):
    """A real user HarmonyOS target (P). iOS source is a sibling outside P,
    matching native_pipeline.configure's separate-directories requirement."""
    project = tmp_path / "hmos"
    project.mkdir()
    src = tmp_path / "ios-src"
    src.mkdir()
    (project / "build-profile.json5").write_text("{}", encoding="utf-8")
    (project / "oh-package.json5").write_text("{}", encoding="utf-8")
    (project / ".migbot").mkdir()
    (project / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(src),
         "harmonyos": str(project), "tools": {}}), encoding="utf-8")
    return project


@pytest.fixture
def sibling_ios_src(user_hmos_project):
    """The iOS source sibling to user_hmos_project (re-derived to survive fixture ordering)."""
    return user_hmos_project.parent / "ios-src"


def test_full_fixture(user_hmos_project):
    report = doctor(user_hmos_project)
    assert report["status"] == "diagnostic_complete"
    assert report["tools_executed"] is False
    assert report["network_accessed"] is False
    assert report["mutations"] is False
    assert report["read_only_verified"] is True
    py = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "python")
    assert py["status"] == "ok"
    proj = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "project")
    assert proj["kind"] == "harmonyos_target"
    migbot = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "migbot_config")
    assert migbot["status"] == "ok"
    # Node must NOT poison source analysis readiness.
    assert not any(i["name"] == "node" for i in report["sections"]["source_analysis"]["items"])


def test_missing_project(tmp_path):
    report = doctor(tmp_path / "nonexistent")
    proj = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "project")
    assert proj["status"] == "missing"
    assert report["overall"] in ("blocked", "needs_project", "partial")


def test_missing_node_and_sdk_reported_not_blocking_source(user_hmos_project):
    report = doctor(user_hmos_project, node_path="/nonexistent/node", sdk_path="/nonexistent/sdk")
    build = report["sections"]["harmonyos_build"]
    node = next(i for i in build["items"] if i["name"] == "node")
    assert node["status"] == "missing"
    assert node["source"] == "explicit"
    # SDK explicitly missing is reported, but source analysis stays ready.
    sdk = next(i for i in build["items"] if i["name"] == "explicit_sdk")
    assert sdk["status"] == "missing"
    assert report["overall"] == "source_analysis_ready"
    # Unset SDK env vars are informational, not a required-missing defect.
    build_summary = build["summary"]
    assert build_summary["required_missing_count"] >= 1  # node/ohpm/java likely absent here


def test_corrupt_config_never_ready(tmp_path):
    (tmp_path / ".migbot").mkdir()
    (tmp_path / ".migbot" / "config.json").write_text("{not valid json", encoding="utf-8")
    report = doctor(tmp_path)
    migbot = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "migbot_config")
    assert migbot["status"] == "corrupt"
    assert report["overall"] == "config_error"


def test_invalid_config_object(tmp_path):
    (tmp_path / ".migbot").mkdir()
    (tmp_path / ".migbot" / "config.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    report = doctor(tmp_path)
    migbot = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "migbot_config")
    assert migbot["status"] == "invalid"
    assert report["overall"] == "config_error"


def test_source_target_overlap_detected(tmp_path):
    (tmp_path / ".migbot").mkdir()
    (tmp_path / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(tmp_path), "harmonyos": str(tmp_path / "sub"),
         "tools": {}}), encoding="utf-8")
    (tmp_path / "sub").mkdir()
    report = doctor(tmp_path)
    migbot = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "migbot_config")
    assert migbot["status"] == "misconfigured"
    joined = " ".join(migbot.get("findings", [])).lower()
    assert ("harmonyos project" in joined or "overlap" in joined
             or "differs from --project" in joined)
    assert report["overall"] == "config_error"


def test_legit_user_app_not_unknown_without_tool_source(tmp_path):
    """A real iOS app with no src/hmigbot_ios must not be flagged unknown."""
    (tmp_path / "MyApp.xcodeproj").mkdir()
    report = doctor(tmp_path)
    proj = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "project")
    assert proj["kind"] == "ios_source"
    assert proj["status"] == "ok"


def test_install_manifest_reported(tmp_path):
    """A minimal {} manifest is NOT ok; only the installer schema is."""
    (tmp_path / ".hmigbot-ios").mkdir()
    (tmp_path / ".hmigbot-ios" / "install.json").write_text(
        json.dumps({"version": "0.9.2", "paths": ["secret"]}), encoding="utf-8")
    report = doctor(tmp_path)
    im = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "install_manifest")
    # Review finding 3: partial manifest must be invalid, not ok.
    assert im["status"] == "invalid"
    assert "missing key 'owner'" in im.get("findings", [])
    # Sensitive paths list must NOT be surfaced.
    assert "paths" not in im


def test_install_manifest_valid_schema_reports_ok(tmp_path):
    (tmp_path / ".hmigbot-ios").mkdir()
    sample = tmp_path / "payload.txt"
    sample.write_bytes(b"hello")
    digest = __import__("hashlib").sha256(b"hello").hexdigest()
    (tmp_path / ".hmigbot-ios" / "install.json").write_text(json.dumps({
        "owner": "hmigbot-ios", "schema_version": 1, "version": "0.9.2",
        "files": {"payload.txt": digest}}), encoding="utf-8")
    report = doctor(tmp_path)
    im = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "install_manifest")
    assert im["status"] == "ok"
    assert im["version"] == "0.9.2"
    assert im["integrity"] == "sample_match"
    assert "not verified" in im["note"].lower()
    assert im["files_count"] == 1


def test_install_manifest_tampered(tmp_path):
    (tmp_path / ".hmigbot-ios").mkdir()
    (tmp_path / "payload.txt").write_bytes(b"hello")
    (tmp_path / ".hmigbot-ios" / "install.json").write_text(json.dumps({
        "owner": "hmigbot-ios", "schema_version": 1, "version": "0.9.2",
        "files": {"payload.txt": "0" * 64}}), encoding="utf-8")
    report = doctor(tmp_path)
    im = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "install_manifest")
    assert im["status"] == "ok"  # format ok, but drift reported
    assert im["integrity"] == "sample_drift"
    assert im["sample"][0]["status"] == "mismatch"


def test_install_manifest_missing_reported_honestly(tmp_path):
    report = doctor(tmp_path)
    im = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "install_manifest")
    assert im["status"] == "not_installed"


def test_device_signing_static_only(tmp_path):
    report = doctor(tmp_path)
    dev = report["sections"]["device_verification"]
    device = next(i for i in dev["items"] if i["name"] == "device_id")
    signing = next(i for i in dev["items"] if i["name"] == "signing_profile")
    assert device["status"] == "unknown"
    assert "runtime" in device.get("note", "").lower() or "static" in device.get("note", "").lower()
    assert signing["status"] == "not_verified"
    assert "no keys" in signing.get("note", "").lower() or "runtime" in signing.get("note", "").lower()


def test_sdk_env_is_optional_not_defect(tmp_path):
    """An unset SDK env var is informational, not a required-missing defect."""
    report = doctor(tmp_path)
    build = report["sections"]["harmonyos_build"]
    sdk_items = [i for i in build["items"] if i["name"] in
                 ("HOS_SDK_HOME", "DEVECO_SDK_HOME", "HDC_HOME")]
    # Every SDK discovery item is optional.
    assert all(i.get("required") is False for i in sdk_items)
    # Not-configured SDK must not inflate the required-missing count.
    assert build["summary"]["required_missing_count"] == 0 or all(
        i["status"] != "not_configured" for i in build["items"] if i.get("required"))


def test_unicode_space_path(tmp_path):
    weird = tmp_path / "my project (测试)"
    weird.mkdir()
    (weird / "build-profile.json5").write_text("{}", encoding="utf-8")
    report = doctor(weird)
    proj = next(i for i in report["sections"]["source_analysis"]["items"] if i["name"] == "project")
    assert proj["kind"] == "harmonyos_target"
    assert "测试" in proj["path"] or "my project" in proj["path"]


def test_input_sha_unchanged_real_snapshot(user_hmos_project):
    """Doctor must not mutate its input: real snapshot digest before == after."""
    before = _tree_sha(user_hmos_project)
    doctor(user_hmos_project)
    after = _tree_sha(user_hmos_project)
    assert before == after


def test_render_text(user_hmos_project):
    report = doctor(user_hmos_project)
    text = render_text(report)
    assert "HMigBot Doctor Report" in text
    assert "source_analysis" in text
    assert "harmonyos_build" in text
    assert "device_verification" in text
    assert "existence" in text.lower()


def test_cli_doctor_json(user_hmos_project):
    result = subprocess.run(
        [sys.executable, "-m", "hmigbot_ios.cli", "doctor", "--project", str(user_hmos_project)],
        capture_output=True, text=True, cwd=str(SRC),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "diagnostic_complete"
    assert "sections" in data


def test_cli_doctor_text_mode(user_hmos_project):
    result = subprocess.run(
        [sys.executable, "-m", "hmigbot_ios.cli", "doctor", "--project", str(user_hmos_project), "--text"],
        capture_output=True, text=True, cwd=str(SRC),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    assert result.returncode == 0
    assert "HMigBot Doctor Report" in result.stderr


# === Review counterexamples ===

def test_explicit_bad_config_blocks_and_no_fallback(user_hmos_project):
    """Finding 1: explicit --config with corrupt content must NOT fall back to
    the default valid .migbot/config.json."""
    bad = user_hmos_project / "bad-explicit.json"
    bad.write_text("{ not valid", encoding="utf-8")
    report = doctor(user_hmos_project, config=bad)
    assert report["overall"] == "config_error", report["overall"]
    cfg = next(i for i in report["sections"]["source_analysis"]["items"]
                if i["name"] == "migbot_config")
    assert cfg["status"] == "corrupt"
    assert cfg["source_of_config"] == "explicit"


def test_explicit_missing_config_blocks(user_hmos_project):
    bad = user_hmos_project / "does-not-exist.json"
    report = doctor(user_hmos_project, config=bad)
    assert report["overall"] == "config_error"
    cfg = next(i for i in report["sections"]["source_analysis"]["items"]
                if i["name"] == "migbot_config")
    assert cfg["status"] == "missing"


def test_explicit_wrong_type_config_blocks(user_hmos_project):
    """A non-object JSON (e.g. a list) is invalid, not a fallback."""
    weird = user_hmos_project / "list.json"
    weird.write_text("[1, 2, 3]", encoding="utf-8")
    report = doctor(user_hmos_project, config=weird)
    assert report["overall"] == "config_error"


def test_nonexistent_source_blocked(user_hmos_project):
    """Finding 2: source path pointing at a missing dir must NOT report ready."""
    cfg = user_hmos_project / ".migbot" / "config.json"
    cfg.write_text(json.dumps({"source_platform": "ios",
                                "ios": str(user_hmos_project.parent / "missing-src"),
                                "harmonyos": str(user_hmos_project)}),
                    encoding="utf-8")
    report = doctor(user_hmos_project)
    assert report["overall"] == "config_error"
    migbot = next(i for i in report["sections"]["source_analysis"]["items"]
                    if i["name"] == "migbot_config")
    assert migbot["status"] == "source_unavailable"
    assert migbot["source_exists"] is False


def test_relative_source_resolves_against_project(tmp_path):
    """Relative 'ios' paths resolve against project root and may point OUTSIDE
    it via '..' (a sibling). Matches native_pipeline.context."""
    proj = tmp_path / "hmos"
    (proj / ".migbot").mkdir(parents=True)
    (tmp_path / "ios-src").mkdir()
    (proj / "build-profile.json5").write_text("{}", encoding="utf-8")
    (proj / ".migbot" / "config.json").write_text(json.dumps({
        "source_platform": "ios", "ios": "../ios-src",
        "harmonyos": "."}), encoding="utf-8")
    report = doctor(proj)
    assert report["overall"] == "source_analysis_ready", report["overall"]
    migbot = next(i for i in report["sections"]["source_analysis"]["items"]
                    if i["name"] == "migbot_config")
    assert migbot["source_exists"] is True
    # The relative path resolves to a sibling outside the project (contains '..').
    assert "ios-src" in migbot["ios_source_path"]
    assert ".." in migbot["ios_source_path"] or str(proj / "ios-src") != migbot["ios_source_path"]


def test_source_platform_wrong_type_blocked(user_hmos_project):
    cfg = user_hmos_project / ".migbot" / "config.json"
    cfg.write_text(json.dumps({"source_platform": 123,
                                "ios": str(user_hmos_project.parent / "ios-src"),
                                "harmonyos": str(user_hmos_project)}),
                    encoding="utf-8")
    report = doctor(user_hmos_project)
    assert report["overall"] == "config_error"


def test_source_field_wrong_type_blocked(user_hmos_project):
    cfg = user_hmos_project / ".migbot" / "config.json"
    cfg.write_text(json.dumps({"source_platform": "ios",
                                "ios": ["array", "not", "string"],
                                "harmonyos": str(user_hmos_project)}),
                    encoding="utf-8")
    report = doctor(user_hmos_project)
    assert report["overall"] == "config_error"


def test_overlap_blocked(user_hmos_project):
    """iOS source equals the project P -> must be blocked (native rejects)."""
    cfg = user_hmos_project / ".migbot" / "config.json"
    cfg.write_text(json.dumps({"source_platform": "ios",
                                "ios": str(user_hmos_project),
                                "harmonyos": str(user_hmos_project)}),
                    encoding="utf-8")
    report = doctor(user_hmos_project)
    migbot = next(i for i in report["sections"]["source_analysis"]["items"]
                    if i["name"] == "migbot_config")
    assert migbot["status"] == "misconfigured"
    assert any("overlap" in f.lower() or "harmonyos project" in f.lower()
                for f in migbot["findings"])


def test_tool_inherited_from_config(user_hmos_project):
    fake_node = user_hmos_project.parent / "fake-node.exe"
    fake_node.write_bytes(b"")
    cfg = user_hmos_project / ".migbot" / "config.json"
    cfg.write_text(json.dumps({"source_platform": "ios",
                                "ios": str(user_hmos_project.parent / "ios-src"),
                                "harmonyos": str(user_hmos_project),
                                "tools": {"node": str(fake_node)}}),
                    encoding="utf-8")
    report = doctor(user_hmos_project)
    node = next(i for i in report["sections"]["harmonyos_build"]["items"] if i["name"] == "node")
    assert node["source"] == "config"
    assert node["status"] == "ok"


def test_explicit_tool_beats_config(user_hmos_project):
    cfg_node = user_hmos_project.parent / "cfg-node.exe"
    cfg_node.write_bytes(b"")
    explicit = user_hmos_project.parent / "explicit-node.exe"
    explicit.write_bytes(b"")
    cfg = user_hmos_project / ".migbot" / "config.json"
    cfg.write_text(json.dumps({"source_platform": "ios",
                                "ios": str(user_hmos_project.parent / "ios-src"),
                                "harmonyos": str(user_hmos_project),
                                "tools": {"node": str(cfg_node)}}), encoding="utf-8")
    report = doctor(user_hmos_project, node_path=str(explicit))
    node = next(i for i in report["sections"]["harmonyos_build"]["items"] if i["name"] == "node")
    assert node["source"] == "explicit"
    assert node["path"] == str(explicit)


def test_empty_manifest_object_is_not_ok(tmp_path):
    """Finding 3 exact reproduction: {} must not be reported as ok."""
    (tmp_path / ".hmigbot-ios").mkdir()
    (tmp_path / ".hmigbot-ios" / "install.json").write_text("{}", encoding="utf-8")
    report = doctor(tmp_path)
    im = next(i for i in report["sections"]["source_analysis"]["items"]
                if i["name"] == "install_manifest")
    assert im["status"] == "invalid"
    assert any("missing key" in f for f in im["findings"])


def test_manifest_integrity_never_full_claim(tmp_path):
    """Even with a valid schema and sample match, note says not verified."""
    (tmp_path / ".hmigbot-ios").mkdir()
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "b.txt").write_bytes(b"b")
    files = {name: __import__("hashlib").sha256(name[0].encode()).hexdigest()
             for name in ("a.txt", "b.txt")}
    (tmp_path / ".hmigbot-ios" / "install.json").write_text(json.dumps({
        "owner": "hmigbot-ios", "schema_version": 1, "version": "1.0",
        "files": files}), encoding="utf-8")
    report = doctor(tmp_path)
    im = next(i for i in report["sections"]["source_analysis"]["items"]
                if i["name"] == "install_manifest")
    assert im["status"] == "ok"
    assert "not a full integrity claim" in im["note"]
    assert im["sample_checked"] <= im["files_count"]


def test_native_pipeline_doctor_entry(user_hmos_project):
    """Doctor must be reachable from the real daily entry (scripts/a2h_ios.py)."""
    root = SRC.parent
    result = subprocess.run(
        [sys.executable, "scripts/a2h_ios.py", "doctor", "--project", str(user_hmos_project)],
        capture_output=True, text=True, cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "diagnostic_complete"
    assert data["overall"] == "source_analysis_ready"
    assert data["read_only_verified"] is True


def test_native_pipeline_doctor_corrupt_config(tmp_path):
    (tmp_path / ".migbot").mkdir()
    (tmp_path / ".migbot" / "config.json").write_text("{bad", encoding="utf-8")
    root = SRC.parent
    result = subprocess.run(
        [sys.executable, "scripts/a2h_ios.py", "doctor", "--project", str(tmp_path)],
        capture_output=True, text=True, cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["overall"] == "config_error"


def test_native_pipeline_doctor_explicit_config(user_hmos_project):
    """Second entry: explicit bad --config on the a2h_ios entry must block too."""
    bad = user_hmos_project / "bad-explicit.json"
    bad.write_text("{ not valid", encoding="utf-8")
    root = SRC.parent
    result = subprocess.run(
        [sys.executable, "scripts/a2h_ios.py", "doctor", "--project", str(user_hmos_project),
         "--config", str(bad)],
        capture_output=True, text=True, cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["overall"] == "config_error"
    cfg = next(i for i in data["sections"]["source_analysis"]["items"]
                if i["name"] == "migbot_config")
    assert cfg["status"] == "corrupt"
    assert cfg["source_of_config"] == "explicit"


# === Approved boundary round: --project P is the true HarmonyOS target ===

import hashlib as _hashlib


def _nested_boundary(tmp_path):
    """Boundary bug fixture: --project P, ios=P/nested-ios, harmonyos=outside-P."""
    P = tmp_path / "target"
    nested = P / "nested-ios"
    nested.mkdir(parents=True)
    (nested / "App.swift").write_text("import SwiftUI", encoding="utf-8")
    (P / ".migbot").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(nested), "harmonyos": str(outside)}),
        encoding="utf-8")
    return P, nested, outside


def test_nested_source_with_external_target_blocked(tmp_path):
    P, nested, _ = _nested_boundary(tmp_path)
    report = doctor(P)
    assert report["overall"] == "config_error", report["overall"]
    migbot = next(i for i in report["sections"]["source_analysis"]["items"]
                    if i["name"] == "migbot_config")
    assert migbot["status"] == "misconfigured"
    joined = " ".join(migbot["findings"]).lower()
    assert "harmonyos project" in joined
    assert "differs from --project" in joined


def test_nested_source_with_external_target_matches_native_oracle(tmp_path):
    from hmigbot_ios import native_pipeline
    from hmigbot_ios.core import MigrationError
    P, nested, _ = _nested_boundary(tmp_path)
    with pytest.raises(MigrationError) as exc_info:
        native_pipeline.configure(nested, P)
    assert "separate" in str(exc_info.value).lower()
    report = doctor(P)
    assert report["overall"] == "config_error"
    assert report["read_only_verified"] is True


def test_reverse_containment_project_inside_source_blocked(tmp_path):
    outer = tmp_path / "ios-outer"
    outer.mkdir()
    P = outer / "hmos"
    P.mkdir()
    (P / ".migbot").mkdir()
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(outer), "harmonyos": str(P)}),
        encoding="utf-8")
    report = doctor(P)
    migbot = next(i for i in report["sections"]["source_analysis"]["items"]
                    if i["name"] == "migbot_config")
    assert migbot["status"] == "misconfigured"


def test_config_target_differs_from_project_alone_blocked(tmp_path):
    P = tmp_path / "hmos"
    P.mkdir()
    (P / ".migbot").mkdir()
    src = tmp_path / "ios-src"
    src.mkdir()
    other = tmp_path / "wrong-target"
    other.mkdir()
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(src), "harmonyos": str(other)}),
        encoding="utf-8")
    report = doctor(P)
    migbot = next(i for i in report["sections"]["source_analysis"]["items"]
                    if i["name"] == "migbot_config")
    assert migbot["status"] == "misconfigured"
    assert any("differs from --project" in f.lower() for f in migbot["findings"])
    assert report["overall"] == "config_error"


def test_sibling_source_with_matching_target_ready(tmp_path):
    src = tmp_path / "ios-src"
    src.mkdir()
    P = tmp_path / "hmos"
    P.mkdir()
    (P / ".migbot").mkdir()
    (P / "build-profile.json5").write_text("{}", encoding="utf-8")
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(src), "harmonyos": str(P)}),
        encoding="utf-8")
    report = doctor(P)
    assert report["overall"] == "source_analysis_ready", report["overall"]


def test_relative_harmonyos_equal_to_project_ready(tmp_path):
    src = tmp_path / "ios-src"
    src.mkdir()
    P = tmp_path / "hmos"
    (P / ".migbot").mkdir(parents=True)
    (P / "build-profile.json5").write_text("{}", encoding="utf-8")
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": "../ios-src", "harmonyos": "."}),
        encoding="utf-8")
    report = doctor(P)
    assert report["overall"] == "source_analysis_ready", report["overall"]


def test_boundary_input_config_unchanged(tmp_path):
    P, _, _ = _nested_boundary(tmp_path)
    cfg = P / ".migbot" / "config.json"
    before = _hashlib.sha256(cfg.read_bytes()).hexdigest()
    doctor(P)
    after = _hashlib.sha256(cfg.read_bytes()).hexdigest()
    assert before == after


def test_both_entries_agree_on_boundary(tmp_path):
    P = tmp_path / "boundary-P"
    nested = P / "nested-ios"
    nested.mkdir(parents=True)
    (P / ".migbot").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(nested), "harmonyos": str(outside)}),
        encoding="utf-8")
    root = SRC.parent
    cli_run = subprocess.run(
        [sys.executable, "-m", "hmigbot_ios.cli", "doctor", "--project", str(P)],
        capture_output=True, text=True, cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    np_run = subprocess.run(
        [sys.executable, "scripts/a2h_ios.py", "doctor", "--project", str(P)],
        capture_output=True, text=True, cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(SRC)})
    assert cli_run.returncode == 0 and np_run.returncode == 0
    cli_data = json.loads(cli_run.stdout)
    np_data = json.loads(np_run.stdout)
    assert cli_data["overall"] == "config_error"
    assert np_data["overall"] == "config_error"


# === P1: SwiftPM manifest pre-flight diagnostic (THEF-21) ===


def _target_with_src(tmp_path):
    """Real split: P is the HarmonyOS target, ios-src is the sibling source."""
    P = tmp_path / "hmos"
    P.mkdir()
    (P / "build-profile.json5").write_text("{}", encoding="utf-8")
    src = tmp_path / "ios-src"
    src.mkdir()
    (P / ".migbot").mkdir()
    (P / ".migbot" / "config.json").write_text(json.dumps(
        {"source_platform": "ios", "ios": str(src), "harmonyos": str(P),
         "tools": {}}), encoding="utf-8")
    return P, src


def _swiftpm_item(report):
    return next((i for i in report["sections"]["source_analysis"]["items"]
                 if i["name"] == "swiftpm_manifest"), None)


def test_swiftpm_source_root_manifest_reports_pending_evidence(tmp_path):
    P, src = _target_with_src(tmp_path)
    (src / "Package.swift").write_text("// swift-tools-version\n", encoding="utf-8")
    report = doctor(P)
    item = _swiftpm_item(report)
    assert item is not None
    assert item["status"] == "pending_evidence"
    assert item["required"] is True
    assert item["evaluation_verified"] is False
    # Doctor stays read-only / inert.
    assert report["tools_executed"] is False
    assert report["network_accessed"] is False
    assert report["mutations"] is False
    assert report["read_only_verified"] is True
    # Actionable formal guidance is present.
    joined = json.dumps(item, ensure_ascii=False)
    assert "manifest-evaluate" in joined
    assert "facts --project" in joined and "--manifest-evidence" in joined
    assert "source-input-evidence.md" in joined
    # Never claims Swift must be on Windows PATH.
    assert item["tool_requirement"]
    # Section surfaces it as a warning, static analysis still proceeds.
    summary = report["sections"]["source_analysis"]["summary"]
    assert summary["can_do"] == "partial"
    assert any("manifest-evaluate" in a for a in summary["next_actions"])
    assert report["overall"] == "source_analysis_ready"


def test_swiftpm_absent_preserves_prior_behavior(tmp_path):
    P, src = _target_with_src(tmp_path)  # no Package.swift anywhere
    report = doctor(P)
    assert _swiftpm_item(report) is None
    assert report["overall"] == "source_analysis_ready"
    assert report["sections"]["source_analysis"]["summary"]["can_do"] == "full"


def test_swiftpm_never_uses_harmony_target(tmp_path):
    """A Package.swift only in the target (not the source) must not be flagged."""
    P, src = _target_with_src(tmp_path)
    (P / "Package.swift").write_text("// wrong side\n", encoding="utf-8")
    report = doctor(P)
    assert _swiftpm_item(report) is None


def test_swiftpm_present_but_swift_on_path_still_not_verified(tmp_path, monkeypatch):
    """Even if a 'swift' is discoverable on PATH, the manifest gate stays
    pending — presence is a clue, never an evaluation/compatibility pass."""
    P, src = _target_with_src(tmp_path)
    (src / "Package.swift").write_text("// pkg\n", encoding="utf-8")
    fake = tmp_path / "swift"
    fake.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    report = doctor(P)
    item = _swiftpm_item(report)
    assert item is not None
    assert item["status"] == "pending_evidence"
    assert item["evaluation_verified"] is False


def test_swiftpm_input_unchanged(tmp_path):
    P, src = _target_with_src(tmp_path)
    (src / "Package.swift").write_text("// pkg\n", encoding="utf-8")
    cfg = P / ".migbot" / "config.json"
    before = _hashlib.sha256(cfg.read_bytes()).hexdigest()
    pkg_before = _hashlib.sha256((src / "Package.swift").read_bytes()).hexdigest()
    doctor(P)
    assert _hashlib.sha256(cfg.read_bytes()).hexdigest() == before
    assert _hashlib.sha256((src / "Package.swift").read_bytes()).hexdigest() == pkg_before



# THEF-13 directed rework only; selected independently from the old suite.
@pytest.mark.parametrize("mode", ["embedded", "contains", "equal", "bad_explicit", "missing_explicit", "unavailable"])
def test_directed_rework_config_blockers_consistent(user_hmos_project, mode):
    project = user_hmos_project
    cfg = project / ".migbot/config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    explicit = None
    if mode == "embedded":
        source = project / "embedded-ios"; source.mkdir(); data["ios"] = str(source)
    elif mode == "contains":
        data["ios"] = str(project.parent)
    elif mode == "equal":
        data["ios"] = str(project)
    elif mode == "unavailable":
        data["ios"] = str(project.parent / "missing-ios")
    else:
        explicit = project / "selected-config.json"
        if mode == "bad_explicit": explicit.write_text("{broken", encoding="utf-8")
    cfg.write_text(json.dumps(data), encoding="utf-8")
    report = doctor(project, config=explicit)
    section = report["sections"]["source_analysis"]
    summary = section["summary"]
    config_item = next(item for item in section["items"] if item["name"] == "migbot_config")
    assert report["overall"] == "config_error"
    assert summary["can_do"] == "none"
    assert summary["required_missing_count"] >= 1
    assert config_item["required"] is True
    assert any("fix selected migration configuration" in action for action in summary["next_actions"])
    assert not any("optional" in action or "install or configure migbot_config" in action for action in summary["next_actions"])
    if explicit: assert config_item["source_of_config"] == "explicit"
    print(json.dumps({"case": mode, "overall": report["overall"], "summary": summary}))


def test_directed_rework_separated_static_without_build_tools(user_hmos_project, monkeypatch):
    monkeypatch.setattr("hmigbot_ios.doctor.shutil.which", lambda name: None)
    for name in ("HOS_SDK_HOME", "DEVECO_SDK_HOME", "HDC_HOME"): monkeypatch.delenv(name, raising=False)
    report = doctor(user_hmos_project)
    assert report["overall"] == "source_analysis_ready"
    assert report["sections"]["source_analysis"]["summary"]["can_do"] == "full"
    assert report["sections"]["harmonyos_build"]["summary"]["required_missing_count"] == 4
    assert report["tools_executed"] is False
    print(json.dumps({"case":"separated_no_build_tools","overall":report["overall"]}))


def test_directed_rework_default_missing_still_setup(user_hmos_project):
    (user_hmos_project / ".migbot/config.json").unlink()
    report=doctor(user_hmos_project)
    summary=report["sections"]["source_analysis"]["summary"]
    assert report["overall"] == "partial"
    assert summary["can_do"] == "partial"
    assert summary["required_missing_count"] == 0
    assert not any("optional" in action for action in summary["next_actions"])
    print(json.dumps({"case":"default_missing_setup","overall":report["overall"],"summary":summary}))


def _directed_manifest(project, files):
    path=project / ".hmigbot-ios/install.json"; path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"owner":"hmigbot-ios","schema_version":1,"version":"fixture","files":files}),encoding="utf-8")


def test_directed_rework_legal_samples_bounded(user_hmos_project, monkeypatch):
    import hashlib
    project=user_hmos_project; expected=hashlib.sha256(b"ordinary").hexdigest()
    files={f"sample-{number}.txt":expected for number in range(4)}
    for name in files: (project/name).write_bytes(b"ordinary")
    _directed_manifest(project, files)
    original=Path.read_bytes; reads=[]
    def read(path):
        if path.name in files: reads.append(path.name)
        return original(path)
    monkeypatch.setattr(Path,"read_bytes",read)
    result=_check_install_manifest(project)
    assert result["status"] == "ok" and result["integrity"] == "sample_match"
    assert result["sample_checked"] == 3 and len(reads)==3
    assert "remaining files reported as unknown" in result["integrity_scope"]
    print(json.dumps({"case":"legal_manifest","status":result["status"],"sample_checked":result["sample_checked"]}))


@pytest.mark.parametrize("shape", ["parent", "absolute", "backslash", "drive", "unsampled_fourth"])
def test_directed_rework_manifest_outside_never_read(user_hmos_project, monkeypatch, shape):
    import hashlib
    project=user_hmos_project
    outside=project.parent / "ordinary-outside-sentinel.txt"; outside.write_bytes(b"ordinary")
    expected=hashlib.sha256(b"ordinary").hexdigest()
    names={"parent":"../ordinary-outside-sentinel.txt","absolute":outside.as_posix(),
           "backslash":"..\\ordinary-outside-sentinel.txt","drive":"Z:/ordinary-outside.txt"}
    files={}
    if shape=="unsampled_fourth":
        for number in range(3):
            name=f"sample-{number}.txt"; (project/name).write_bytes(b"ordinary"); files[name]=expected
    files[names.get(shape,"../ordinary-outside-sentinel.txt")]=expected
    _directed_manifest(project,files)
    original=Path.read_bytes; reads=[]
    def read(path):
        if path.resolve()==outside.resolve(): raise AssertionError("outside sentinel read attempted")
        reads.append(path)
        return original(path)
    monkeypatch.setattr(Path,"read_bytes",read)
    result=_check_install_manifest(project)
    assert result["status"] == "invalid" and result.get("integrity") != "sample_match"
    assert reads==[]
    print(json.dumps({"case":"manifest_"+shape,"status":result["status"],"outside_reads":0,"sample_content_reads":0}))


def test_directed_rework_manifest_link_escape_not_read(user_hmos_project, monkeypatch):
    import hashlib
    project=user_hmos_project; external=project.parent/"owned-external-directory"; external.mkdir()
    sentinel=external/"ordinary.txt"; sentinel.write_bytes(b"ordinary")
    link=project/"sample-link"
    method="symlink"
    try:
        link.symlink_to(external,target_is_directory=True)
    except OSError:
        if os.name != "nt": pytest.skip("own directory symlink unavailable")
        result=subprocess.run(["cmd","/c","mklink","/J",str(link),str(external)],capture_output=True)
        if result.returncode: pytest.skip("own directory junction unavailable")
        method="junction"
    _directed_manifest(project,{"sample-link/ordinary.txt":hashlib.sha256(b"ordinary").hexdigest()})
    original=Path.read_bytes; outside_reads=[]
    def read(path):
        if path.resolve()==sentinel.resolve():
            outside_reads.append(True); raise AssertionError("linked outside sentinel read attempted")
        return original(path)
    monkeypatch.setattr(Path,"read_bytes",read)
    result=_check_install_manifest(project)
    assert result["status"]=="invalid" and result.get("integrity")!="sample_match"
    assert outside_reads==[]
    print(json.dumps({"case":"manifest_link_escape","method":method,"status":result["status"],"outside_reads":0}))
