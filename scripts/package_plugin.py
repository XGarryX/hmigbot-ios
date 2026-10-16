"""Reproducible source plugin zip, excluding local builds and captured projects."""
import argparse
import hashlib
from pathlib import Path
import zipfile
import shutil

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
if args.output.exists() or args.output.with_suffix(args.output.suffix + ".sha256").exists():
    parser.error("Output already exists; choose a new package path")
include = {".codex-plugin", "skills", "scripts", "src", "tests", "schemas", "rules", "docs", "evaluations", "providers", "agents-codex", "bin", "policies", "vendor"}
files = [p for folder in sorted(include) for p in (root / folder).rglob('*') if p.is_file()
         and not {'__pycache__', '.build', '.swiftpm', 'node_modules'}.intersection(p.relative_to(root).parts)
         and p.suffix != '.pyc' and not p.is_symlink()]
files += [root / name for name in ('.gitattributes', '.gitignore', 'README.md', 'pyproject.toml', 'CHANGELOG.md', 'install.ps1', 'install.sh', 'uninstall.ps1', 'uninstall.sh') if (root / name).is_file()]
args.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        info = zipfile.ZipInfo("hmigbot-ios/" + path.relative_to(root).as_posix(), date_time=(2026, 9, 29, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        executable = path.suffix in {'.sh', '.bin'} or path.name.startswith('a2h-') and path.parent.name == 'bin'
        info.create_system = 3
        info.external_attr = (0o100755 if executable else 0o100644) << 16
        with path.open('rb') as source, archive.open(info, 'w', force_zip64=True) as target:
            shutil.copyfileobj(source, target)
with args.output.open('rb') as stream:
    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
args.output.with_suffix(args.output.suffix + ".sha256").write_text(checksum + "  " + args.output.name + "\n")
print(f"Packaged {len(files)} files: {args.output}\nSHA256 {checksum}")
