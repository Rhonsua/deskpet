"""Edit only our marked section in a project's DSH local instruction file."""
import os
import tempfile
from pathlib import Path

FILENAME = 'AGENTS.local.md'
BEGIN = b'<!-- tianyi-work-persona:begin -->'
END = b'<!-- tianyi-work-persona:end -->'
MAX_FILE = 1024 * 1024


def target_path(project):
    if not str(project).strip():
        raise ValueError('请先选择项目文件夹。')
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('请选择有效的项目文件夹。')
    target = root / FILENAME
    if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise ValueError('项目人设文件是链接，请先检查其实际位置。')
    return target


def read_target(target):
    try:
        with target.open('rb') as stream:
            data = stream.read(MAX_FILE + 1)
    except FileNotFoundError:
        return None
    if len(data) > MAX_FILE:
        raise ValueError('项目人设文件超过 1 MiB，请先手动整理。')
    data.decode('utf-8-sig')
    return data


def section(data):
    if BEGIN not in data and END not in data:
        return None
    if data.count(BEGIN) != 1 or data.count(END) != 1:
        raise ValueError('人设标记重复或不完整，请先检查 AGENTS.local.md。')
    start, end = data.index(BEGIN), data.index(END)
    if start >= end or (start and data[start-1:start] != b'\n'):
        raise ValueError('人设标记顺序或位置异常，请先检查 AGENTS.local.md。')
    end += len(END)
    if end < len(data) and data[end:end+1] not in (b'\r', b'\n'):
        raise ValueError('人设结束标记与其他内容相连，请先检查 AGENTS.local.md。')
    return start, end


def current_persona(project):
    data = read_target(target_path(project)) or b''
    bounds = section(data)
    if bounds is None:
        return None
    start, end = bounds
    return data[start + len(BEGIN):end - len(END)].decode('utf-8').strip()


def validate_persona(text):
    text = text.strip()
    if not text or len(text.encode('utf-8')) > 48000:
        raise ValueError('请填写人设，UTF-8 编码后最多 48 KB。')
    if BEGIN.decode() in text or END.decode() in text or '\x00' in text:
        raise ValueError('人设中包含保留标记或无效字符。')
    return text


def replace_file(target, before, after):
    # Stage in the same directory so replacement is atomic on the target drive.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.tianyi-persona-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        target_path(target.parent)
        if read_target(target) != before:
            raise ValueError('文件在编辑期间发生变化，请重新选择项目后再试。')
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apply_persona(project, text):
    text = validate_persona(text)
    target = target_path(project)
    before = read_target(target)
    data = before or b''
    bounds = section(data)
    block = BEGIN + b'\n' + text.replace('\r\n', '\n').encode('utf-8') + b'\n' + END
    if bounds is None:
        after = data + b'\n' + block + b'\n'
    else:
        start, end = bounds
        after = data[:start] + block + data[end:]
    if len(after) > MAX_FILE:
        raise ValueError('加入人设后文件超过 1 MiB，请先整理项目人设文件。')
    replace_file(target, before, after)
    return target


def remove_persona(project):
    target = target_path(project)
    before = read_target(target)
    data = before or b''
    bounds = section(data)
    if bounds is None:
        return False
    start, end = bounds
    # The importer owns the immediately surrounding line breaks as well.
    if start:
        start -= 2 if data[max(0, start-2):start] == b'\r\n' else 1
    if data[end:end+2] == b'\r\n':
        end += 2
    elif data[end:end+1] == b'\n':
        end += 1
    replace_file(target, before, data[:start] + data[end:])
    return True
