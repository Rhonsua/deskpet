"""Build a standalone API-1 work persona Mod, without desktop app files."""
import hashlib
from pathlib import Path
import zipfile


def build(output=None):
    root = Path(__file__).resolve().parents[1]
    source = root / 'extensions/tianyi_work_persona'
    output = Path(output) if output else root / 'dist/TianyiPet-WorkPersona-0.1.0.zip'
    names = ('mod.json', 'entry.py', 'widget.py', 'instructions.py', 'persona.md', 'README.md')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr('tianyi_work_persona/' + name, (source / name).read_bytes())
        archive.writestr('tianyi_work_persona/LICENSE', (root / 'LICENSE').read_bytes())
    output.with_suffix('.zip.sha256').write_text(
        hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n', encoding='ascii')
    return output


if __name__ == '__main__':
    print(build())
