"""Extract, install to a disposable folder, run helpers, then uninstall safely."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parents[1]
preview = root / 'preview'
preview.mkdir(exist_ok=True)
setup = root / 'dist' / 'TianyiPet-0.2.1-Setup.exe'
assert setup.read_bytes()[:2] == b'MZ', 'installer must be an executable'
with tempfile.TemporaryDirectory(prefix='installer-check-', dir=preview, ignore_cleanup_errors=True) as scratch:
    folder = Path(scratch).resolve()
    assert folder.is_relative_to(preview.resolve())
    extracted, installed = folder / 'extracted', folder / 'installed'
    extracted.mkdir()
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run([str(setup), '/Q', '/C', '/T:' + str(extracted)], check=True, timeout=60, creationflags=flags)
    assert (extracted / 'Setup.exe').is_file() and (extracted / 'payload.zip').is_file()
    subprocess.run([str(extracted / 'Setup.exe'), '--quiet', '--test', '--dir', str(installed)],
                   check=True, timeout=60, creationflags=flags)
    assert (installed / 'TianyiPet.exe').is_file() and (installed / 'installed-files.txt').is_file()
    report = folder / 'self-check.json'
    subprocess.run([str(installed / 'TianyiPet.exe'), '--self-check', '--report', str(report)],
                   check=True, timeout=100, creationflags=flags)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result.get('ok'), result
    (installed / 'keep-me.txt').write_text('user file', encoding='utf-8')
    subprocess.run([str(installed / 'TianyiSetup.exe'), '--uninstall', '--quiet', '--test', '--dir', str(installed)],
                   check=True, timeout=30, creationflags=flags)
    deadline = time.monotonic() + 20
    while set(path.name for path in installed.iterdir()) != {'keep-me.txt'} and time.monotonic() < deadline:
        time.sleep(.1)
    assert not (installed / 'TianyiPet.exe').exists()
    assert not (installed / 'installed-files.txt').exists()
    assert (installed / 'keep-me.txt').read_text(encoding='utf-8') == 'user file'
    result.update(installer=True, uninstall=True, preserves_user_files=True)
    (root / 'dist' / 'TEST-REPORT.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS: installer extraction, per-user directory install, packaged assets/audio/WebView2, uninstall preserves user files')
