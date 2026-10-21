"""Build a per-user installer with Windows' built-in IExpress and C# compiler."""
from pathlib import Path
import subprocess
import shutil
import hashlib
import zipfile

root = Path(__file__).resolve().parents[1]
stage = root / 'build' / 'installer-stage'
stage.mkdir(parents=True, exist_ok=True)
bundle = root / 'dist' / 'TianyiPet'
if not (bundle / 'TianyiPet.exe').is_file():
    raise SystemExit('先运行 PyInstaller 构建可执行版本')
with zipfile.ZipFile(stage / 'payload.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in bundle.rglob('*'):
        if path.is_file(): archive.write(path, path.relative_to(bundle))
portable = root / 'dist' / 'TianyiPet-0.3.0-portable.zip'
shutil.copyfile(stage / 'payload.zip', portable)
compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64',
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                '/out:' + str(stage / 'Setup.exe'), str(root / 'packaging' / 'Setup.cs')], check=True)
output = root / 'dist' / 'TianyiPet-0.3.0-Setup.exe'
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
FILE1="payload.zip"
[SourceFiles]
SourceFiles0={stage}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
'''.format(output=output, stage=stage), encoding='utf-16')
subprocess.run(['C:/Windows/System32/iexpress.exe', '/N', '/Q', str(sed)], check=True, cwd=stage)
if not output.is_file(): raise SystemExit('IExpress 未生成安装包，请检查 build/installer-stage')
print(output)
with (root / 'dist' / 'SHA256SUMS.txt').open('w', encoding='ascii') as checksums:
    for path in (output, portable):
        checksums.write(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')
