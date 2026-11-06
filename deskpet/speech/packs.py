"""Portable GPT-SoVITS voice packs. Only model weights and one WAV are materialized."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import wave
import zipfile

PACK_FOLDER = '语音包'
VERSIONS = ('v1', 'v2', 'v2Pro', 'v2ProPlus', 'v3', 'v4')
MAX_MEMBER = 2 * 1024**3


def available_packs(directory):
    try:
        return sorted((p for p in Path(directory).iterdir() if p.suffix.lower() == '.zip' and p.is_file()),
                      key=lambda p: p.name.casefold())
    except FileNotFoundError:
        return []


def _small_text(archive, info):
    if info.file_size > 65536:
        raise ValueError('语音包文字文件太大')
    return archive.read(info).decode('utf-8-sig').strip()


def _unique(items, description):
    if len(items) != 1:
        raise ValueError(f'语音包需要指定唯一的{description}，可以在 voice.json 中填写')
    return items[0]


def _contents(archive):
    infos = archive.infolist()
    if len(infos) > 1024:
        raise ValueError('语音包文件过多')
    members = {}
    for info in infos:
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        if (path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename
                or info.filename in members):
            raise ValueError('语音包内文件名无效或重复')
        members[info.filename] = info

    manifests = [n for n in members if PurePosixPath(n).name == 'voice.json']
    if manifests:
        key = _unique(manifests, 'voice.json')
        meta = json.loads(_small_text(archive, members[key]))
        if not isinstance(meta, dict) or meta.get('format') != 1:
            raise ValueError('不支持的 voice.json 格式')
        parent = PurePosixPath(key).parent
        names = []
        for field, suffix in [('gpt', '.ckpt'), ('sovits', '.pth'), ('reference', '.wav')]:
            rel = meta.get(field)
            if not isinstance(rel, str) or not rel.lower().endswith(suffix):
                raise ValueError('语音包缺少 ' + field)
            path = parent / rel
            if path.is_absolute() or '..' in path.parts or str(path) not in members:
                raise ValueError('语音包文件不存在：' + rel)
            names.append(str(path))
        version, text = meta.get('version'), meta.get('text')
    else:
        names = [_unique([n for n in members if n.lower().endswith(ext)], desc) for ext, desc in
                 [('.ckpt', 'GPT 权重'), ('.pth', 'SoVITS 权重'), ('.wav', '参考 WAV')]]
        wav = PurePosixPath(names[2])
        transcripts = [str(wav.with_suffix('.txt')), str(wav.parent / 'prompt.txt'), 'prompt.txt']
        prompt = next((name for name in transcripts if name in members), None)
        if prompt is None:
            raise ValueError('语音包需要参考录音的逐字台词，请加入同名 .txt 或 prompt.txt')
        text = _small_text(archive, members[prompt])
        with archive.open(members[names[1]]) as f:
            header = f.read(2)
        version = {b'05': 'v2Pro', b'06': 'v2ProPlus', b'04': 'v4', b'03': 'v3', b'02': 'v3',
                   b'00': 'v1', b'01': 'v2'}.get(header)
        if version is None:
            raise ValueError('无法识别权重版本，请在 voice.json 中填写 version')
    if version not in VERSIONS or not isinstance(text, str) or not 0 < len(text.strip()) <= 1000:
        raise ValueError('语音包版本或参考台词无效')
    files = [members[name] for name in names]
    if any(not 0 < f.file_size <= MAX_MEMBER for f in files) or files[2].file_size > 16 * 1024**2:
        raise ValueError('语音包内模型或参考录音大小无效')
    return version, text.strip(), files


def pack_config(path, engine, cache, shared=None):
    """Run in the speech worker. ZIPs can never set executables or filesystem destinations."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with Path(path).open('rb') as stream:
        signature = hashlib.sha256()
        for block in iter(lambda: stream.read(2**20), b''):
            signature.update(block)
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            version, text, members = _contents(archive)
            directory = cache / signature.hexdigest()
            files = [directory / name for name in ('model.ckpt', 'speaker.pth', 'ref.wav')]
            marker = directory / 'ready'
            if not marker.is_file() or not all(p.is_file() and p.stat().st_size == m.file_size
                                               for p, m in zip(files, members)):
                with tempfile.TemporaryDirectory(dir=cache) as scratch:
                    for dest, member in zip(files, members):
                        with archive.open(member) as src, (Path(scratch)/dest.name).open('wb') as output:
                            shutil.copyfileobj(src, output, length=1024*1024)
                    with wave.open(str(Path(scratch)/'ref.wav'), 'rb') as wav:
                        duration = wav.getnframes() / wav.getframerate()
                        if not 3 <= duration <= 10:
                            raise ValueError('参考录音须为 3～10 秒的 PCM WAV')
                    directory.mkdir(exist_ok=True)
                    for dest in files:
                        os.replace(Path(scratch)/dest.name, dest)
                    marker.touch()
    engine = Path(engine)
    bases = (engine.parent/'pretrained', engine/'GPT_SoVITS'/'pretrained_models')
    defaults = (shared or {}).get('model', {})
    model = {k: defaults[k] for k in ('device', 'is_half') if k in defaults}
    for field, name in [('bert_base_path', 'chinese-roberta-wwm-ext-large'),
                        ('cnhuhbert_base_path', 'chinese-hubert-base')]:
        configured = defaults.get(field)
        model[field] = str(next((p for p in ([Path(configured)] if configured else []) + [b/name for b in bases]
                                 if p.is_dir()), bases[0]/name))
    model.update(version=version, t2s_weights_path=str(files[0]), vits_weights_path=str(files[1]))
    return {'model': model, 'reference': {'audio': str(files[2]), 'text': text, 'language': 'zh'},
            'inference': (shared or {}).get('inference', {})}
