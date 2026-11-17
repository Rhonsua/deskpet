"""Create an independent API-3 companion-growth package, without user data."""
import hashlib
import json
from pathlib import Path
import zipfile


def build(output=None):
    root = Path(__file__).resolve().parents[1]
    output = Path(output) if output else root / 'dist/TianyiPet-BondCompanion-0.2.3.zip'
    source = root / 'deskpet/mods/bond'
    manifest = dict(id='bond',name='互动养成增强包',version='0.2.3',api_version=3,
        description='主面板直达；亲密度、每日互动、花样下落谱与长条、猜歌、小心愿、图鉴、三曲演出和舞台装饰。停用恢复原成长。需要 Mod API 3 主程序。')
    files = {'bond/mod.json':json.dumps(manifest,ensure_ascii=False,indent=2).encode(),
             'bond/entry.py':b'from .mod import BondMod\nfactory = BondMod\n',
             'bond/LICENSE':(root/'LICENSE').read_bytes(),
             'bond/README.md':(source/'README.md').read_bytes()}
    for name in ('__init__.py','store.py','mod.py','widget.py','album.py','rhythm.py','chart.py','events.py','playback.py','activities.py','listening.py','stage_art.py','assets/SOURCES.md'):
        files['bond/'+name]=(source/name).read_bytes()
    # Art is local and separately credited, not covered by the code's MIT license.
    for name in ('tianyi-cover.webp','tianyi-background.webp','tianyi-stage.webp',
                 'tianyi-sing-front.webp','tianyi-sing-left.webp','tianyi-sing-right.webp'):
        art=source/'assets'/name
        if art.is_file():files['bond/assets/'+name]=art.read_bytes()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):archive.writestr(name,data)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None and set(archive.namelist())==set(files)
    output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n',encoding='ascii')
    return output


if __name__=='__main__':print(build())
