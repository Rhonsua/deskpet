"""Archive a freshly built desktop bundle without generating an installer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


def build(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Version must be major.minor.patch')
    root = Path(__file__).resolve().parents[1]
    bundle = root / 'dist/TianyiPet'
    for name in ('TianyiPet.exe', 'TianyiWorker.exe', '_internal/assets/live2d/tianyi/action-map.json'):
        if not (bundle / name).is_file():
            raise ValueError('Build the PyInstaller bundle first: ' + name)
    notes = root / 'docs' / (version + '更新公告.txt')
    if not notes.is_file():
        raise ValueError('Missing release notes: ' + str(notes))
    output = root / 'dist' / ('TianyiPet-' + version + '-portable.zip')
    temporary = output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())
        archive.write(notes, '更新公告.txt')
        archive.writestr('VERSION.txt', version + '\n')
    with zipfile.ZipFile(temporary) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('Corrupt ZIP member: ' + bad)
    temporary.replace(output)
    checksum = hashlib.sha256()
    with output.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    digest = checksum.hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(json.dumps(dict(path=str(output), bytes=output.stat().st_size, sha256=digest), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='0.5.0')
    build(parser.parse_args().version)
