"""Explicit target build provider with a persisted log and artifact hashes."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess

from .core import SCHEMA, MigrationError, atomic_write, digest, json_bytes, snapshot, write_new_tree
from .generate import verify


def build_target(config, output: Path, timeout=300):
    if config["source"]["platform"] != "ios":
        raise MigrationError("Delegate Android builds to the existing HMigBot workflow")
    target = Path(config["target"]["root"])
    source = Path(config["source"]["root"])
    output = output.resolve()
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in (source, target)):
        raise MigrationError("Build evidence output must be separate from source and target")
    if output.exists() and any(output.iterdir()):
        raise MigrationError("Build evidence output already exists")
    if not (target / "build-profile.json5").is_file():
        raise MigrationError("Target has no build-profile.json5")
    generated_integrity = verify(source, target) if (target / "migration/generation.json").exists() else None
    if generated_integrity and not generated_integrity['checks'][0]['passed']:
        raise MigrationError("Source changed since generation; reconcile the migration baseline before building")
    tool = config.get("tools", {})
    hvigor = tool.get("hvigorw") or shutil.which("hvigorw")
    if not hvigor or not Path(hvigor).is_file():
        raise MigrationError("Configure tools.hvigorw with the actual executable/wrapper path")
    command = [hvigor]
    if Path(hvigor).suffix.lower() in {".bat", ".cmd", ".js"}:
        # Bypass cmd.exe quoting entirely; official bat wrappers delegate to this JS file.
        script = Path(hvigor).with_suffix(".js")
        node = tool.get("node") or shutil.which("node")
        if not script.is_file() or not node or not Path(node).is_file():
            raise MigrationError("Configure tools.node and use a wrapper with adjacent hvigorw.js")
        command = [node, str(script)]
    import re
    build = config.get('build', {})
    module, module_target, product = (build.get(k, d) for k, d in (('module', 'entry'), ('module_target', 'default'), ('product', 'default')))
    if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]+', v) for v in (module, module_target, product)):
        raise MigrationError('Build module, module_target and product must be identifiers')
    command += ["--mode", "module", "-p", f"module={module}@{module_target}", "-p", f"product={product}", "assembleHap", "--no-daemon"]
    env = os.environ.copy()
    if tool.get("deveco_sdk"):
        env["DEVECO_SDK_HOME"] = tool["deveco_sdk"]
    if tool.get("node"):
        env["NODE_HOME"] = str(Path(tool["node"]).parent)
    started = datetime.now(timezone.utc).isoformat()
    inputs = snapshot(target)
    from .quality_views import spec_inputs, target_inputs
    product_hashes = target_inputs(target)
    contract_hashes = spec_inputs(target) if (target / '.migbot/config.json').exists() else {}
    source_before = snapshot(source)['sha256']
    try:
        result = subprocess.run(command, cwd=target, env=env, capture_output=True, timeout=timeout, shell=False)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = None, exc.stdout or b"", exc.stderr or b""
    artifacts = []
    if code == 0:
        for path in sorted((target / module / "build").rglob("*.hap")):
            artifacts.append({"path": str(path.relative_to(target).as_posix()), "sha256": digest(path.read_bytes()),
                              "bytes": path.stat().st_size})
    source_after = snapshot(source)['sha256']
    hvigor_success = b'BUILD SUCCESSFUL' in stdout + stderr
    report = {"schema_version": SCHEMA, "started_at": started, "command": command,
              "target_project": str(target.resolve()), "target_input_hashes": product_hashes,
              "spec_input_hashes": contract_hashes,
              "target_input_sha256": inputs["sha256"], "target_after_sha256": snapshot(target)['sha256'],
              "source_sha256": source_before, "source_changed": source_before != source_after,
              "generation_integrity": generated_integrity,
              "exit_code": code, "artifacts": artifacts,
              "hvigor_success_marker": hvigor_success,
              "status": "build_passed" if code == 0 and artifacts and hvigor_success and source_before == source_after else "build_failed",
              "timeout": code is None, "behavior": "not_verified", "device_install": "not_run"}
    # Retain real logs first. The accepted build receipt is published only after
    # checking for contradictory compiler errors, even when a wrapper exits zero.
    write_new_tree(output, {"stdout.log": stdout, "stderr.log": stderr})
    from .harmony_diagnostics import analyze, save_report
    diagnostics = analyze(output / 'stdout.log', output / 'stderr.log', code,
                          target={'module': module, 'module_target': module_target, 'product': product})
    diagnostic_path = save_report(diagnostics, output / 'diagnostics.json')
    report['diagnostics'] = {'path': 'diagnostics.json', 'sha256': digest(diagnostic_path.read_bytes())}
    if not diagnostics['build_command_passed']:
        report['status'] = 'build_failed'
    atomic_write(output / 'build.json', json_bytes(report))
    return report
