"""Create an independent API-3 companion-growth package, without user data."""
import hashlib
import json
from pathlib import Path
import zipfile


VERSION = '0.3.2'


def build(output=None):
    root = Path(__file__).resolve().parents[1]
    output = Path(output) if output else root / f'dist/TianyiPet-BondCompanion-{VERSION}.zip'
    source = root / 'deskpet/mods/bond'
    manifest = dict(id='bond',name='互动养成增强包',version=VERSION,api_version=3,
        description='每日陪伴收集《洛天依上河图》的十八幅画片，在成长纪念集里赏画、拼接长卷。包含亲密度养成、节奏演出与猜歌。需要 Mod API 3 主程序。')
    files = {'bond/mod.json':json.dumps(manifest,ensure_ascii=False,indent=2).encode(),
             'bond/entry.py':b'from .mod import BondMod\nfactory = BondMod\n',
             'bond/LICENSE':(root/'LICENSE').read_bytes(),
             'bond/README.md':(source/'README.md').read_bytes()}
    for name in (
        '__init__.py', 'store.py', 'mod.py', 'widget.py', 'studio.py', 'album.py',
        'scrapbook.py', 'river_scroll.py', 'rhythm.py', 'chart.py', 'events.py', 'playback.py',
        'activities.py', 'listening.py', 'stage_art.py', 'assets/SOURCES.md',
        'assets/album-stationery.webp', 'assets/album-tianyi-days.webp', 'assets/stage-scenery.webp',
    ):
        files['bond/'+name]=(source/name).read_bytes()
    for number in range(1, 19):
        name = f'assets/river-scroll/{number:02d}.webp'
        files['bond/'+name] = (source/name).read_bytes()
    # Art is local and separately credited, not covered by the code's MIT license.
    for name in ('album-wings.webp','album-jasmine.webp','tianyi-background.webp','tianyi-stage.webp',
                 'tianyi-sing-front.webp','tianyi-sing-left.webp','tianyi-sing-right.webp'):
        art=source/'assets'/name
        if art.is_file():files['bond/assets/'+name]=art.read_bytes()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            if not name.endswith('.webp'):
                data = data.replace(b'\r\n', b'\n')
            archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None and set(archive.namelist())==set(files)
    output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n',encoding='ascii')
    return output


if __name__=='__main__':print(build())
