from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
datas = [(str(path), str(path.parent.relative_to(root)))
         for path in (root / 'assets' / 'character').rglob('*.png')
         if path.name in {'tianyi-simple-v3-costume.png', 'tianyi-refined-v3-smooth.png',
                          'blink.png', 'happy.png', 'eat.png', 'lift.png', 'sleep-back.png',
                          'phone.png', 'sing-front.png', 'sing-left.png', 'sing-right.png'}]
datas += [(str(root / 'bilibili_probe.js'), '.'), (str(root / 'bilibili_early.js'), '.'),
          (str(root / 'characters' / 'README.md'), 'characters'),
          (str(root / 'characters' / 'example' / 'character.json.example'), 'characters/example')]
datas += collect_data_files('webview')
a = Analysis([str(root / 'app_entry.py')], pathex=[str(root)], datas=datas,
             hiddenimports=['webview.platforms.edgechromium', 'webview.platforms.winforms'],
             excludes=['webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cef',
                       'webview.platforms.cocoa', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'tkinter', 'numpy', 'PIL', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TianyiPet', console=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TianyiWorker', console=True)
bundle = COLLECT(gui, worker, a.binaries, a.datas, name='TianyiPet')
