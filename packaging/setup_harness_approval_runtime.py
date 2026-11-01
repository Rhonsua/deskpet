"""Install the official approval-capable DSH runtime locally, never globally."""
import subprocess
import sys
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from deskpet.chat.harness_bootstrap import ensure_runtime
    target = root / 'local-work' / 'harness-npm'
    ensure_runtime(target, progress=lambda text: print(text, flush=True))
    subprocess.run([sys.executable, str(root / 'packaging/probe_harness_approval.py')], check=True)
    print(target / 'node_modules/.bin/dsh.cmd')

if __name__ == '__main__':
    main()
