"""Check real installer bytes/uninstall without opening the pet or using APIs."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class CountingOutput(io.RawIOBase):
    """Measure the previous ZIP compression without leaving another large file."""
    position = 0

    def writable(self):
        return True

    def write(self, value):
        self.position += len(value)
        return len(value)

    def tell(self):
        return self.position


def check(setup, report, compare_zip=False):
    setup, report = setup.resolve(), report.resolve()
    bundle = ROOT / 'dist/TianyiPet'
    assert (bundle / 'TianyiPet.exe').is_file()
    source_files = sorted(p for p in bundle.rglob('*') if p.is_file())
    report.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW
    result = dict(ok=False, installer_bytes=setup.stat().st_size)
    with tempfile.TemporaryDirectory(prefix='compressed-installer-', dir=report.parent) as scratch:
        folder = Path(scratch).resolve()
        assert folder.is_relative_to(report.parent)
        extracted, installed, temp = folder / 'extracted', folder / 'installed', folder / 'temp'
        extracted.mkdir()
        temp.mkdir()
        environment = dict(os.environ, TEMP=str(temp), TMP=str(temp))
        def run(command):
            return subprocess.run([str(p) for p in command], env=environment, check=True,
                                  capture_output=True, timeout=180, creationflags=flags)
        run([setup, '/Q', '/C', '/T:' + str(extracted)])
        assert (extracted / 'Setup.exe').is_file() and (extracted / 'payload.tlz').is_file()
        assert not (extracted / 'payload.zip').exists()
        result['compressed_payload_bytes'] = (extracted / 'payload.tlz').stat().st_size
        started = time.monotonic()
        run([extracted / 'Setup.exe', '--quiet', '--test', '--dir', installed])
        result['install_seconds'] = round(time.monotonic() - started, 2)
        assert not list(temp.glob('TianyiPayload-*.zip')), 'decoded temporary ZIP leaked'
        for source in source_files:
            target = installed / source.relative_to(bundle)
            assert target.is_file() and checksum(target) == checksum(source), str(source)
        expected = {p.relative_to(bundle).as_posix() for p in source_files} | {
            'VERSION.txt', '更新公告.txt', 'TianyiSetup.exe', 'installed-files.txt'}
        assert {p.relative_to(installed).as_posix() for p in installed.rglob('*') if p.is_file()} == expected
        result['identical_files'] = len(source_files)
        # Compression benchmarking is optional; ordinary release validation
        # checks extracted bytes without recompressing the complete bundle.
        if compare_zip:
            counter = CountingOutput()
            with zipfile.ZipFile(counter, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for source in source_files:
                    archive.write(source, source.relative_to(bundle))
                archive.write(installed / 'VERSION.txt', 'VERSION.txt')
                archive.write(installed / '更新公告.txt', '更新公告.txt')
            result['previous_zip_bytes'] = counter.tell()
        frozen_report = folder / 'frozen.json'
        run([installed / 'TianyiWorker.exe', '--self-check', '--bilibili-download-only', '--report', frozen_report])
        assert json.loads(frozen_report.read_text())['ok']
        keep = installed / 'user-file.txt'
        keep.write_text('keep user content', encoding='utf-8')
        run([extracted / 'Setup.exe', '--uninstall', '--quiet', '--test', '--dir', installed])
        assert list(installed.iterdir()) == [keep]
        result.update(ok=True, uninstall=True, preserves_user_files=True,
                      frozen_download=True, decoded_temp_removed=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('setup', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT / 'local-work/reports/size-check.json')
    parser.add_argument('--compare-zip', action='store_true', help='额外重压缩全部文件，测量旧格式体积')
    args = parser.parse_args()
    check(args.setup, args.report, args.compare_zip)
