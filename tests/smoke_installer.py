"""Extract, install to a disposable folder, run helpers, then uninstall safely."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile

from PyInstaller.archive.readers import CArchiveReader

root = Path(__file__).resolve().parents[1]
preview = root / 'preview'
preview.mkdir(exist_ok=True)
setup = root / 'dist' / 'TianyiPet-0.5.0-Setup.exe'
goal_pack = root / 'dist' / 'TianyiPet-GoalCompanion-0.1.0.zip'
assert goal_pack.is_file(), 'build the separate goal Mod ZIP before installer validation'
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
                                       '_internal/characters/example/character-walk.json.example',
                                       '_internal/characters/example/personality.json.example'}, character_files
        models = [name for name in names if name.endswith('.model3.json')]
        model_prefix = '_internal/assets/live2d/tianyi/'
        mapping = json.loads(archive.read(model_prefix + 'action-map.json'))
        assert models == [model_prefix + mapping['model']], models
        assert archive.read('VERSION.txt').decode().strip() == '0.5.0'
        assert not any('previous-action-map' in name for name in names)
        assert not any('miku' in name.lower() for name in names)
        assert '_internal/pet_chat/personas/luotianyi.json' in names
        assert '_internal/assets/icons/tianyi.ico' in names
        assert not any('pet_mods/goals' in name.replace('\\', '/') for name in names), names
    subprocess.run([str(extracted / 'Setup.exe'), '--quiet', '--test', '--dir', str(installed)],
                   check=True, timeout=60, creationflags=flags)
    assert (installed / 'TianyiPet.exe').is_file() and (installed / 'installed-files.txt').is_file()
    for executable in ('TianyiPet.exe', 'TianyiWorker.exe'):
        bundle = CArchiveReader(str(installed / executable))
        assert not any(name == 'pet_mods.goals' or name.startswith('pet_mods.goals.') for name in bundle.toc)
        pyz_names = [name for name in bundle.toc if name.lower().endswith('.pyz')]
        assert pyz_names, 'missing bundled Python archive'
        for name in pyz_names:
            pure = bundle.open_embedded_archive(name)
            assert 'audio.output_switch' in pure.toc, 'installer is missing the audio route fix'
            assert not any(module == 'pet_mods.goals' or module.startswith('pet_mods.goals.')
                           for module in pure.toc), 'goal code must not ship in the main application'
    report = folder / 'self-check.json'
    subprocess.run([str(installed / 'TianyiPet.exe'), '--self-check', '--native-live2d', '--report', str(report),
                    '--mod-pack', str(goal_pack)],
                   check=True, timeout=240, creationflags=flags)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result.get('ok') and result.get('live2d') and result.get('chat') and result.get('avatar_icon'), result
    assert all(result.get(key) for key in ('live2d_walk', 'static_walk', 'chat_worker')), result
    assert result.get('goal_code_excluded') and result.get('mods_empty_by_default') and result.get('external_goal_package'), result
    assert all(result.get(key) for key in ('music_tools', 'netease_crypto', 'netease_browser', 'lyrics_menu', 'beat_worker')), result
    (installed / 'keep-me.txt').write_text('user file', encoding='utf-8')
    subprocess.run([str(installed / 'TianyiSetup.exe'), '--uninstall', '--quiet', '--test', '--dir', str(installed)],
                   check=True, timeout=30, creationflags=flags)
    deadline = time.monotonic() + 20
    while set(path.name for path in installed.iterdir()) != {'keep-me.txt'} and time.monotonic() < deadline:
        time.sleep(.1)
    assert not (installed / 'TianyiPet.exe').exists()
    assert not (installed / 'installed-files.txt').exists()
    assert (installed / 'keep-me.txt').read_text(encoding='utf-8') == 'user file'
    result.update(version='0.5.0', installer=True, uninstall=True, preserves_user_files=True, tianyi_only=True)
    (root / 'dist' / 'TEST-REPORT-0.5.0-installer.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS: installer extraction, standalone Mod ZIP in frozen runtime, empty default Mod host, '
          'no bundled goal code, packaged assets/audio/WebView2, uninstall preserves user files')
