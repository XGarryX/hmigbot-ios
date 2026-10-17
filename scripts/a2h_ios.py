"""Mechanical iOS source helpers for HMigBot's original a2h pipeline."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hmigbot_ios.windows_scheduler_runtime import install as install_windows_runtime
install_windows_runtime()
from hmigbot_ios.native_pipeline import main

if __name__ == '__main__':
    raise SystemExit(main())
