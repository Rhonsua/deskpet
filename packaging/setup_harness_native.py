"""Install the official Koffi 3.1.1 MIT native sidecar into the isolated venv."""
import base64
import hashlib
import io
import json
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path

METADATA='https://registry.npmjs.org/@koromix/koffi-win32-x64/3.1.1'
TARBALL='https://registry.npmjs.org/@koromix/koffi-win32-x64/-/koffi-win32-x64-3.1.1.tgz'
LICENSE_URL='https://registry.npmjs.org/koffi/-/koffi-3.1.1.tgz'

def fetch(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        return response.read()

def verify(blob, integrity):
    algorithm,digest=integrity.split('-',1)
    if algorithm != 'sha512' or base64.b64encode(hashlib.sha512(blob).digest()).decode()!=digest:
        raise ValueError('Official npm sidecar integrity verification failed')

def install(target, fetcher=fetch):
    if os.name != 'nt' or platform.machine().lower() not in ('amd64','x86_64'):
        raise RuntimeError('This sidecar supports Windows x64 only')
    meta=json.loads(fetcher(METADATA))
    if meta['version'] != '3.1.1' or meta['dist']['tarball'] != TARBALL:
        raise ValueError('Unexpected official package metadata')
    blob=fetcher(TARBALL)
    verify(blob,meta['dist']['integrity'])
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        data=archive.extractfile('package/win32_x64/koffi.node').read()
        licenses=[m for m in archive.getmembers() if 'license' in m.name.lower() and m.isfile()]
        if licenses:
            license_data=archive.extractfile(licenses[0]).read()
        else:
            license_meta=json.loads(fetcher('https://registry.npmjs.org/koffi/3.1.1'))
            license_blob=fetcher(LICENSE_URL)
            verify(license_blob,license_meta['dist']['integrity'])
            with tarfile.open(fileobj=io.BytesIO(license_blob),mode='r:gz') as source:
                license_data=source.extractfile('package/LICENSE.txt').read()
    target=Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(dir=target.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(data)
        os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    (target.parent/'LICENSE.txt').write_bytes(license_data)
    (target.parent/'SOURCE.txt').write_text('Koffi 3.1.1 (MIT)\n'+TARBALL+'\n'+LICENSE_URL+'\n',encoding='utf-8')

def main():
    root=Path(__file__).resolve().parents[1]
    install(root/'.harness-venv/native/koffi/win32_x64/koffi.node')
    print('Official Windows Koffi 3.1.1 sidecar verified and installed')

if __name__=='__main__':
    main()
