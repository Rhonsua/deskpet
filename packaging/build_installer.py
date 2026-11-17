"""Build a per-user installer with Windows' built-in IExpress and C# compiler."""
from pathlib import Path
import subprocess
import hashlib
import zipfile
import argparse
import sys
from installer_payload import compress

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deskpet.version import VERSION

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--portable', action='store_true', help='另外输出免安装 ZIP')
parser.add_argument('--version', default=VERSION)
parser.add_argument('--output-dir', type=Path, help='测试构建可指定独立输出目录，不覆盖正式安装包')
args = parser.parse_args()
version = args.version
if version != VERSION:
    raise SystemExit('Installer version must match deskpet/version.py')

root = Path(__file__).resolve().parents[1]
stage = root / 'build' / 'installer-stage'
stage.mkdir(parents=True, exist_ok=True)
output_dir = args.output_dir.resolve() if args.output_dir else root / 'dist'
output_dir.mkdir(parents=True, exist_ok=True)
bundle = root / 'dist' / 'TianyiPet'
if not (bundle / 'TianyiPet.exe').is_file():
    raise SystemExit('先运行 PyInstaller 构建可执行版本')
raw_payload = stage / 'payload.zip'
try:
    # Solid native compression benefits from adjacent similar files (including
    # the two worker entry points). Keep artwork and runtime bytes unchanged.
    with zipfile.ZipFile(raw_payload, 'w', zipfile.ZIP_STORED) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file(): archive.write(path, path.relative_to(bundle))
        archive.writestr('VERSION.txt', version + '\n')
        archive.write(root / 'docs/release-notes' / (version + '更新公告.txt'), '更新公告.txt')
    compress(raw_payload, stage / 'payload.tlz',
             lambda done, total: print(f'压缩安装数据：{done * 100 // total}%', flush=True))
finally:
    raw_payload.unlink(missing_ok=True)
portable = root / 'dist' / ('TianyiPet-' + version + '-portable.zip')
if args.portable:
    from build_portable import build
    build(version)
compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
source = stage / 'Setup.generated.cs'
source.write_text((root / 'packaging/Setup.cs').read_text(encoding='utf-8').replace('__APP_VERSION__', version), encoding='utf-8-sig')
subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64',
                '/win32icon:' + str(root / 'assets' / 'icons' / 'tianyi.ico'),
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                '/out:' + str(stage / 'Setup.exe'), str(source), str(root / 'packaging/InstallerPayload.cs')], check=True)
output = output_dir / ('TianyiPet-' + version + '-Setup.exe')
sed = stage / 'package.sed'
sed.write_text('''[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={output}
FriendlyName=TianyiPet Setup
AppLaunched=Setup.exe
PostInstallCmd=<None>
AdminQuietInstCmd=Setup.exe --quiet
UserQuietInstCmd=Setup.exe --quiet
SourceFiles=SourceFiles
[Strings]
FILE0="Setup.exe"
FILE1="payload.tlz"
[SourceFiles]
SourceFiles0={stage}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
'''.format(output=output, stage=stage), encoding='utf-16')
subprocess.run(['C:/Windows/System32/iexpress.exe', '/N', '/Q', str(sed)], check=True, cwd=stage)
if not output.is_file(): raise SystemExit('IExpress 未生成安装包，请检查 build/installer-stage')
print(output)
with (output_dir / 'SHA256SUMS.txt').open('w', encoding='ascii') as checksums:
    artifacts = [output, portable] if portable.is_file() else [output]
    goal_pack = root / 'dist' / 'TianyiPet-GoalCompanion-0.1.0.zip'
    if goal_pack.is_file():
        artifacts.append(goal_pack)
    for path in artifacts:
        checksums.write(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')
