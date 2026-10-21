from pathlib import Path
import json
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent
datas = [(str(path), str(path.parent.relative_to(root)))
         for path in (root / 'assets' / 'character').rglob('*.png')
         if path.name in {'tianyi-simple-v3-costume.png', 'tianyi-refined-v3-smooth.png',
                          'blink.png', 'happy.png', 'eat.png', 'lift.png', 'sleep-back.png',
                          'phone.png', 'sing-front.png', 'sing-left.png', 'sing-right.png'}]
datas += [(str(root / 'bilibili_probe.js'), '.'), (str(root / 'bilibili_early.js'), '.'),
          (str(root / 'LICENSE'), '.'), (str(root / 'README.md'), '.'),
          (str(root / 'assets' / 'README.md'), 'assets'),
          (str(root / 'characters' / 'README.md'), 'characters'),
          (str(root / 'characters' / 'example' / 'character.json.example'), 'characters/example')]
datas += collect_data_files('webview')
# Bundle exactly the active Tianyi export, never user character directories or
# older model exports. An incomplete local export must fail the build.
model_root = root / 'assets' / 'live2d' / 'tianyi'
mapping = json.loads((model_root / 'action-map.json').read_text(encoding='utf-8'))
model_path = model_root / mapping['model']
model = json.loads(model_path.read_text(encoding='utf-8'))
def referenced_files(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from referenced_files(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in ('FadeInTime', 'FadeOutTime'):
                yield from referenced_files(item)
files = {model_path, model_root / 'action-map.json'}
files.update(model_root / name for name in referenced_files(model['FileReferences']))
for path in sorted(files):
    if not path.resolve().is_relative_to(model_root.resolve()) or not path.is_file():
        raise ValueError('Missing or invalid Tianyi model asset: ' + str(path))
    datas.append((str(path), str(path.parent.relative_to(root))))
datas += collect_data_files('live2d')
binaries = collect_dynamic_libs('live2d')
a = Analysis([str(root / 'app_entry.py')], pathex=[str(root)], datas=datas, binaries=binaries,
             hiddenimports=['webview.platforms.edgechromium', 'webview.platforms.winforms',
                            'live2d._live2d', 'OpenGL.platform.win32'],
             excludes=['webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cef',
                       'webview.platforms.cocoa', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'tkinter', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TianyiPet', console=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TianyiWorker', console=True)
bundle = COLLECT(gui, worker, a.binaries, a.datas, name='TianyiPet')
