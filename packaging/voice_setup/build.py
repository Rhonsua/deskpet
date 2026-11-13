"""Build the private group-share ZIP. No character, reference or voice weights."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from download import fetch_tool


def main():
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    stage = root / 'build/voice-setup'
    stage.mkdir(parents=True, exist_ok=True)
    tool = fetch_tool(stage)
    source = root / 'deskpet/speech'
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
            '--name', 'TianyiVoiceSetup', '--paths', str(source), '--distpath', str(stage/'out'),
            '--workpath', str(stage/'work'), '--specpath', str(stage), '--icon', str(root/'assets/icons/tianyi.ico')]
    for asset in (tool, source/'worker.py', source/'packs.py'):
        args.extend(['--add-data', str(asset) + os.pathsep + '.'])
    subprocess.run([*args, str(here/'voice_setup.py')], check=True)
    output = root / 'dist/TianyiPet-0.7.0-VoiceSetup-Windows-x64.zip'
    temp = output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in (stage/'out/TianyiVoiceSetup.exe', here/'使用说明.txt', here/'7zip-License.txt'):
            package.write(path, path.name)
    with zipfile.ZipFile(temp) as package:
        assert package.testzip() is None
    temp.replace(output)
    with output.open('rb') as file:
        checksum = hashlib.file_digest(file, 'sha256').hexdigest()
    print(output, output.stat().st_size, checksum)


if __name__ == '__main__':
    main()
