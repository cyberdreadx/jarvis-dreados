"""Hidden launcher entry point; keep startup errors in the project log."""
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent.parent
os.chdir(root)
sys.path.insert(0, str(root))
(root / 'data').mkdir(exist_ok=True)
with (root / 'data' / 'launcher-server.log').open('a', encoding='utf-8', buffering=1) as log:
    sys.stdout = sys.stderr = log
    try:
        runpy.run_path(str(root / 'server.py'), run_name='__main__')
    except BaseException:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
