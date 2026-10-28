"""Check the actual portable ZIP and run its frozen app in an isolated folder."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from PyInstaller.archive.readers import CArchiveReader


def check(archive_path):
    root = Path(__file__).resolve().parents[1]
    preview = root / 'preview'
    preview.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='portable-check-', dir=preview,
                                     ignore_cleanup_errors=True) as scratch:
        folder = Path(scratch).resolve()
        installed = folder / 'application'
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            assert archive.testzip() is None
            assert len(names) == len(set(names)), 'Duplicate ZIP entries'
            for name in names:
                assert (installed / name).resolve().is_relative_to(installed), name
            assert archive.read('VERSION.txt').decode().strip() == '0.5.0'
            assert '更新公告.txt' in names
            assert not any('miku' in name.lower() or '/pet_mods/goals/' in name.lower()
                           or name.lower().endswith(('.db', '.mp3', '.cmo3', '.psd')) for name in names)
            character_files = [name for name in names if '/characters/' in name]
            assert set(character_files) <= {'_internal/characters/README.md',
                '_internal/characters/example/character.json.example',
                '_internal/characters/example/character-walk.json.example',
                '_internal/characters/example/personality.json.example'}, character_files
            prefix = '_internal/assets/live2d/tianyi/'
            mapping = json.loads(archive.read(prefix + 'action-map.json'))
            models = [name for name in names if name.endswith('.model3.json')]
            assert models == [prefix + mapping['model']], models
            assert not any('previous-action-map' in name for name in names)
            archive.extractall(installed)
        for executable in ('TianyiPet.exe', 'TianyiWorker.exe'):
            bundle = CArchiveReader(str(installed / executable))
            pure_names = [name for name in bundle.toc if name.lower().endswith('.pyz')]
            assert pure_names
            for name in pure_names:
                modules = bundle.open_embedded_archive(name).toc
                assert not any(module == 'pet_mods.goals' or module.startswith('pet_mods.goals.')
                               for module in modules)
                assert all(module in modules for module in ('walk_controller', 'walk_runtime',
                    'pet_chat.remote', 'chat_player_worker'))
        report = folder / 'self-check.json'
        env = os.environ.copy()
        env.pop('QT_QPA_PLATFORM', None)
        with (folder / 'stdout.log').open('w') as stdout, (folder / 'stderr.log').open('w') as stderr:
            subprocess.run([str(installed / 'TianyiPet.exe'), '--self-check', '--native-live2d',
                            '--report', str(report)], check=True, timeout=240, env=env,
                           stdout=stdout, stderr=stderr,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result = json.loads(report.read_text(encoding='utf-8'))
        result.update(version='0.5.0', portable_zip=True, tianyi_only=True,
                      no_bundled_mods=True, model=mapping['model'])
        (root / 'dist/TEST-REPORT-0.5.0.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        required = ('ok', 'live2d', 'live2d_walk', 'static_walk', 'chat_worker', 'chat',
                    'avatar_icon', 'goal_code_excluded', 'mods_empty_by_default', 'music_tools',
                    'netease_crypto', 'netease_browser', 'lyrics_menu', 'beat_worker', 'audio', 'webview2')
        assert all(result.get(key) for key in required), result
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, nargs='?', default=Path(__file__).resolve().parents[1] /
                        'dist/TianyiPet-0.5.0-portable.zip')
    check(parser.parse_args().archive.resolve())
