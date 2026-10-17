"""Validate native contracts around the unchanged bundled writeback writer."""
from pathlib import Path
import json, sys
here = Path(__file__).resolve()
skill = next(p for p in here.parents if (p / 'SKILL.md').is_file())
runtime = skill / 'runtime.json'
root = (skill / json.loads(runtime.read_text())['runtime_relative']).resolve() if runtime.exists() else skill.parents[1]
helper = root / 'vendor/hmigbot' / 'skills/a2h-execute/scripts/apply_writeback.py'
if not helper.is_file(): raise SystemExit('Bundled helper missing; reinstall the complete plugin')
sys.path.insert(0, str(root / 'src'))
from hmigbot_ios.native_writeback import main
raise SystemExit(main(sys.argv[1:], helper=helper))
