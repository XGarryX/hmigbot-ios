"""Portable contracts, source fingerprints and non-destructive output handling."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

SCHEMA = "hmigbot-ios/1"
EXCLUDED = {".git", ".build", "build", "DerivedData", "Pods", "Carthage",
            "node_modules", "oh_modules", ".hvigor", ".swiftpm", ".hmigbot-ios", ".serena", "__pycache__"}
SOURCE_SUFFIXES = {".swift", ".m", ".mm", ".h", ".c", ".cpp", ".plist",
                   ".entitlements", ".pbxproj", ".xcconfig", ".storyboard", ".xib",
                   ".xcstrings", ".strings", ".stringsdict", ".xcprivacy"}
SOURCE_NAMES = {"Package.resolved", "Podfile", "Podfile.lock", "Cartfile.resolved",
                "Contents.json", "contents.xcworkspacedata"}


class MigrationError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise MigrationError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        def invalid_constant(value):
            raise MigrationError(f"Non-finite JSON number: {value}")
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique, parse_constant=invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"Cannot read JSON {path}: {exc}") from exc


def write_json(path: Path, value):
    atomic_write(path, json_bytes(value))


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def safe_child(root: Path, relative: str) -> Path:
    # Bundle paths are POSIX and must also be safe on Windows.
    from pathlib import PurePosixPath
    parts = PurePosixPath(relative).parts
    if not relative or "\\" in relative or ":" in relative or relative.startswith("/") or ".." in parts:
        raise MigrationError(f"Unsafe relative path: {relative}")
    reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{i}" for prefix in ("com", "lpt") for i in range(1, 10)}
    if relative != PurePosixPath(relative).as_posix() or any(p.endswith((" ", ".")) or p.split(".")[0].lower() in reserved for p in parts):
        raise MigrationError(f"Non-portable relative path: {relative}")
    child = root.joinpath(*parts).resolve()
    if not child.is_relative_to(root.resolve()) or child == root.resolve():
        raise MigrationError(f"Path escapes root: {relative}")
    return child


def source_files(root: Path):
    root = root.resolve()
    if not root.is_dir():
        raise MigrationError(f"Source directory does not exist: {root}")
    # Every non-generated file contributes to the fingerprint, including assets,
    # configuration and native libraries. Symlinks are refused instead of silently skipped.
    result = []
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for name in dirs + names:
            item = Path(parent) / name
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise MigrationError(f"Source links require an explicit materialized copy: {item}")
        for name in sorted(names):
            if name.startswith("._") or name == ".DS_Store":
                continue
            result.append(Path(parent) / name)
    return sorted(result, key=lambda p: p.relative_to(root).as_posix())


def snapshot(root: Path):
    entries = [{"path": p.relative_to(root.resolve()).as_posix(),
                "sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
               for p in source_files(root)]
    return {"algorithm": "sha256", "excluded_directories": sorted(EXCLUDED),
            "files": entries, "sha256": digest(json_bytes(entries))}


def anchor(path: str, sha256: str, line: int = 1, **location):
    return {"path": path, "sha256": sha256, "line": line, **location}


def resolve_anchors(record: dict):
    modern = record.get("source_anchors_ref")
    legacy = record.get("android_source_anchors_ref")
    if modern is not None and legacy is not None and modern != legacy:
        raise MigrationError("Conflicting source_anchors_ref and android_source_anchors_ref")
    if record.get("source_platform") == "ios" and legacy is not None:
        raise MigrationError("iOS facts must not contain Android source anchors")
    return modern if modern is not None else legacy


def load_config(path: Path):
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise MigrationError("Configuration must be an object")
    if raw.get("schema_version", 1) not in (1, 2):
        raise MigrationError("Unsupported configuration schema_version")
    modern = raw.get("source")
    if modern is None:
        if not raw.get("android"):
            raise MigrationError("Set source.platform and source.root")
        modern = {"platform": "android", "root": raw["android"]}
    target = raw.get("target", {"platform": "harmonyos", "root": raw.get("harmonyos")})
    if not isinstance(modern, dict) or not isinstance(target, dict):
        raise MigrationError("source and target must be objects")
    if modern.get("platform") not in ("ios", "android") or target.get("platform") != "harmonyos":
        raise MigrationError("Supported routes: ios/android -> harmonyos")
    def resolved(value):
        if not isinstance(value, str) or not value.strip():
            raise MigrationError("Source and target root paths are required")
        return str((path.parent / value).resolve())
    modern = {**modern, "root": resolved(modern.get("root"))}
    target = {**target, "root": resolved(target.get("root"))}
    if "android" in raw and (modern["platform"] != "android" or resolved(raw["android"]) != modern["root"]):
        raise MigrationError("Legacy android conflicts with source")
    if "harmonyos" in raw and resolved(raw["harmonyos"]) != target["root"]:
        raise MigrationError("Legacy harmonyos conflicts with target")
    s, t = Path(modern["root"]), Path(target["root"])
    if s.is_relative_to(t) or t.is_relative_to(s):
        raise MigrationError("Source and target directories must not overlap")
    tool_paths = raw.get("tools", {})
    if not isinstance(tool_paths, dict):
        raise MigrationError("tools must be an object of explicit executable paths")
    tool_paths = {key: resolved(value) for key, value in tool_paths.items()}
    return {**raw, "schema_version": 2, "source": modern, "target": target, "tools": tool_paths}


def write_new_tree(output: Path, files: dict[str, bytes]):
    """Publish only into an absent or empty directory; never overwrite user work."""
    import stat

    def output_present():
        try:
            status = output.lstat()
        except FileNotFoundError:
            return False
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & reparse_point:
            raise MigrationError(f"Output must not be a link or reparse point: {output}")
        return True

    if output_present() and (not output.is_dir() or any(output.iterdir())):
        raise MigrationError(f"Output must be absent or empty: {output}")
    for name in files:
        safe_child(output, name)
    if len({name.casefold() for name in files}) != len(files):
        raise MigrationError("Output contains case-colliding paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    import time
    temp = Path(tempfile.mkdtemp(prefix=".hmigbot-ios-", dir=output.parent))
    publication_failure = None
    try:
        for name, data in files.items():
            dest = safe_child(temp, name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        if output_present():
            output.rmdir()  # Empty-directory-only operation, fails if concurrently modified.
        for attempt in range(5):
            if os.path.lexists(output):
                raise MigrationError(f"Output appeared before publication: {output}")
            try:
                temp.rename(output)
                break
            except PermissionError as error:
                # Windows can briefly deny directory renames while another handle is open.
                # Keep publication atomic, and surface genuine denials after bounded retries.
                if getattr(error, "winerror", None) != 5 or attempt == 4 or os.path.lexists(output):
                    raise
                time.sleep(0.05 * (2 ** attempt))
    except BaseException as error:
        publication_failure = error
        raise
    finally:
        try:
            if temp.exists():
                shutil.rmtree(temp)
        except Exception as cleanup_error:
            if publication_failure is None:
                raise
            publication_failure.add_note(f"Temporary tree cleanup failed at {temp}: {cleanup_error}")
