"""Extract, install to a disposable folder, run helpers, then uninstall safely."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile

root = Path(__file__).resolve().parents[1]
preview = root / 'preview'
preview.mkdir(exist_ok=True)
setup = root / 'dist' / 'TianyiPet-0.4.0-Setup.exe'
assert setup.read_bytes()[:2] == b'MZ', 'installer must be an executable'
with tempfile.TemporaryDirectory(prefix='installer-check-', dir=preview, ignore_cleanup_errors=True) as scratch:
    folder = Path(scratch).resolve()
    assert folder.is_relative_to(preview.resolve())
    extracted, installed = folder / 'extracted', folder / 'installed'
    extracted.mkdir()
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run([str(setup), '/Q', '/C', '/T:' + str(extracted)], check=True, timeout=60, creationflags=flags)
    assert (extracted / 'Setup.exe').is_file() and (extracted / 'payload.zip').is_file()
    with zipfile.ZipFile(extracted / 'payload.zip') as archive:
        names = archive.namelist()
        character_files = [name for name in names if '/characters/' in name]
        assert set(character_files) <= {'_internal/characters/README.md',
                                       '_internal/characters/example/character.json.example',
                                       '_internal/characters/example/personality.json.example'}, character_files
        models = [name for name in names if name.endswith('.model3.json')]
        assert models == ['_internal/assets/live2d/tianyi/tianyi-turn-shoulder.model3.json'], models
        assert not any('miku' in name.lower() for name in names)
        assert '_internal/pet_chat/personas/luotianyi.json' in names
        assert '_internal/assets/icons/tianyi.ico' in names
    subprocess.run([str(extracted / 'Setup.exe'), '--quiet', '--test', '--dir', str(installed)],
                   check=True, timeout=60, creationflags=flags)
    assert (installed / 'TianyiPet.exe').is_file() and (installed / 'installed-files.txt').is_file()
    report = folder / 'self-check.json'
    subprocess.run([str(installed / 'TianyiPet.exe'), '--self-check', '--native-live2d', '--report', str(report)],
                   check=True, timeout=150, creationflags=flags)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result.get('ok') and result.get('live2d') and result.get('chat') and result.get('avatar_icon'), result
    (installed / 'keep-me.txt').write_text('user file', encoding='utf-8')
    subprocess.run([str(installed / 'TianyiSetup.exe'), '--uninstall', '--quiet', '--test', '--dir', str(installed)],
                   check=True, timeout=30, creationflags=flags)
    deadline = time.monotonic() + 20
    while set(path.name for path in installed.iterdir()) != {'keep-me.txt'} and time.monotonic() < deadline:
        time.sleep(.1)
    assert not (installed / 'TianyiPet.exe').exists()
    assert not (installed / 'installed-files.txt').exists()
    assert (installed / 'keep-me.txt').read_text(encoding='utf-8') == 'user file'
    result.update(version='0.4.0', installer=True, uninstall=True, preserves_user_files=True, tianyi_only=True)
    (root / 'dist' / 'TEST-REPORT.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS: installer extraction, per-user directory install, packaged assets/audio/WebView2, uninstall preserves user files')
