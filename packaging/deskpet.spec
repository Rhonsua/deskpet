from pathlib import Path
import json
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(path), str(path.parent.relative_to(root)))
         for path in (root / 'assets' / 'character').rglob('*.png')
         if path.name in {'tianyi-refined-v3-smooth.png',
                          'blink.png', 'happy.png', 'eat.png', 'lift.png', 'sleep-back.png',
                          'phone.png', 'sing-front.png', 'sing-left.png', 'sing-right.png'}]

# Include only validated walking frames; generation sheets/previews stay local.
import sys
sys.path.insert(0, str(root))
sdk_site = root / '.harness-venv/Lib/site-packages'
if not (sdk_site / 'deepseek_harness').is_dir():
    raise ValueError('Install the verified Harness SDK before building')
sys.path.insert(0, str(sdk_site))
datas += copy_metadata('deepseek-harness-sdk')
datas += copy_metadata('pydantic')
from deskpet.pet.characters import builtin_walk, validate_walk_images
walk = builtin_walk()
if walk is not None:
    validate_walk_images(walk)
    walk_files = set(walk.left + walk.right) | {root / 'assets/character/walk/walk.json'}
    datas += [(str(path), str(path.parent.relative_to(root))) for path in sorted(walk_files)]
datas += [(str(root / 'deskpet/music/players/bilibili_probe.js'), 'deskpet/music/players'), (str(root / 'deskpet/music/players/bilibili_early.js'), 'deskpet/music/players'),
          (str(root / 'LICENSE'), '.'), (str(root / 'README.md'), '.'),
          (str(root / 'assets' / 'README.md'), 'assets'),
          (str(root / 'characters' / 'README.md'), 'characters'),
          (str(root / 'characters' / 'example' / 'character.json.example'), 'characters/example'),
          (str(root / 'characters' / 'example' / 'character-walk.json.example'), 'characters/example'),
          (str(root / 'characters' / 'example' / 'personality.json.example'), 'characters/example')]
datas += collect_data_files('webview')
datas.append((str(root / 'assets' / 'icons' / 'tianyi.ico'), 'assets/icons'))
datas.append((str(root / 'deskpet/chat' / 'personas' / 'luotianyi.json'), 'deskpet/chat/personas'))
datas.append((str(root / 'deskpet/chat' / 'harness_permission_bridge.mjs'), 'deskpet/chat'))
datas.append((str(root / 'deskpet/chat' / 'runtime_package_lock.json'), 'deskpet/chat'))
datas.append((str(root / 'deskpet/music/kugou/LICENSE'), 'deskpet/music/kugou'))
# Only aligned original hand poses: exclude generation sheets and references.
hand_root = root / 'assets' / 'ui' / 'headpat'
for name in ('hand-hover.png', 'hand-contact.png', 'manifest.json'):
    path = hand_root / name
    if not path.is_file():
        raise ValueError('Missing headpat hand asset: ' + str(path))
    datas.append((str(path), 'assets/ui/headpat'))
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

# Current separate poses only: runtime files, never PSD/Cubism projects/backups.
for pose in ('work', 'crawl'):
    pose_root = root / 'assets/live2d' / ('tianyi-' + pose)
    entry = pose_root / ('tianyi-' + pose + '.model3.json')
    model = json.loads(entry.read_text(encoding='utf-8'))
    pose_files = {entry} | {pose_root / name for name in referenced_files(model['FileReferences'])}
    for path in sorted(pose_files):
        if not path.resolve().is_relative_to(pose_root.resolve()) or not path.is_file():
            raise ValueError('Missing pose asset: ' + str(path))
        datas.append((str(path), str(path.parent.relative_to(root))))
datas += collect_data_files('live2d')
binaries = collect_dynamic_libs('live2d')
a = Analysis([str(root / 'app_entry.py')], pathex=[str(root), str(sdk_site)], datas=datas, binaries=binaries,
             hiddenimports=['webview.platforms.edgechromium', 'webview.platforms.winforms',
                            'live2d._live2d', 'OpenGL.platform.win32',
                            *collect_submodules('deepseek_harness')],
             excludes=['webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cef',
                       'webview.platforms.cocoa', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'tkinter', 'pytest', 'deskpet.mods.goals',
                       'PIL.AvifImagePlugin', 'PIL._avif'], noarchive=False)
# These optional Qt plugins drag in PDF/QML/virtual-keyboard engines. The app
# uses native Windows widgets/IME and PNG artwork, not either plugin. Keep
# software OpenGL, TLS and multimedia backends for machines unlike this one.
unused_qt = {name.lower() for name in (
    'Qt6Pdf.dll', 'Qt6Quick.dll', 'Qt6Qml.dll', 'Qt6QmlMeta.dll',
    'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll', 'Qt6VirtualKeyboard.dll',
    'qpdf.dll', 'qtvirtualkeyboardplugin.dll')}
filtered_binaries = [entry for entry in a.binaries
                     if Path(entry[0]).name.lower() not in unused_qt]
# Fail the build if a retained DLL/PYD actually needs an excluded engine.
import pefile
for destination, source, kind in filtered_binaries:
    if Path(source).suffix.lower() not in ('.dll', '.pyd'):
        continue
    with pefile.PE(source, fast_load=True) as pe:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
        imports = (getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []) +
                   getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', []))
        needed = {entry.dll.decode('ascii').lower() for entry in imports} & unused_qt
        if needed:
            raise ValueError(f'{destination} still needs excluded Qt engines: {needed}')
a.binaries = filtered_binaries
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TianyiPet', console=False,
          icon=str(root / 'assets' / 'icons' / 'tianyi.ico'))
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TianyiWorker', console=True)
bundle = COLLECT(gui, worker, a.binaries, a.datas, name='TianyiPet')
