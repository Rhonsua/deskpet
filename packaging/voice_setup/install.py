"""Install a private, relocatable voice runtime for the existing 0.7.0 desktop app."""
from contextlib import contextmanager
import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave
import winreg
import zipfile

from download import NAME, SIZE, SHA256, digest, fetch_archive, fetch_tool


RUNTIME_NAME = 'TianyiVoice-v2Pro-20250604'
TOP = NAME[:-3]
DATA = Path(os.environ['LOCALAPPDATA']) / 'TianyiPet' / 'TianyiPet'
REG_KEY = r'Software\TianyiPet\Prototype\speech'
NO_WINDOW = subprocess.CREATE_NO_WINDOW
REQUIRED = (
    'runtime/python.exe', 'runtime/ffmpeg.exe', 'GPT_SoVITS/TTS_infer_pack/TTS.py',
    'GPT_SoVITS/pretrained_models/chinese-hubert-base/pytorch_model.bin',
    'GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/pytorch_model.bin',
    'GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt',
    'GPT_SoVITS/text/G2PWModel/g2pW.onnx',
    'GPT_SoVITS/pretrained_models/fast_langdetect/lid.176.bin',
)


@contextmanager
def exclusive(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'install.lock').open('a+b') as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError('另一个窗口正在安装语音环境。') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def check_files(engine):
    for relative in REQUIRED:
        path = engine / relative
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'运行环境缺少 {relative}。')


def set_paths(python, engine, pack=None):
    values = {'python': str(python), 'engine': str(engine)}
    if pack:
        values['config'] = str(pack)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
        previous = {}
        try:
            for name, value in values.items():
                try:
                    previous[name] = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    previous[name] = None
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        except OSError:
            for name, old in previous.items():
                if old is not None:
                    winreg.SetValueEx(key, name, 0, old[1], old[0])
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
            raise


def import_pack(source, directory):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    if source.resolve() == target.resolve():
        return target
    if target.exists():
        if digest(source) == digest(target):
            return target
        raise ValueError('语音包目录已有内容不同的同名 ZIP。请先给新包改名。')
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        copy = Path(tmp) / 'pack.tmp'
        shutil.copyfile(source, copy)
        copy.rename(target)
    return target


def check_pack(path):
    if not path.is_file() or path.suffix.lower() != '.zip':
        raise ValueError('请选择群里提供的 A 或 C 语音包 ZIP。')
    from packs import _contents
    with zipfile.ZipFile(path) as archive:
        version, _, _ = _contents(archive)
        if version != 'v2Pro':
            raise ValueError('此辅助包针对 v2Pro 的 A、C 语音包。')


def child_env(cache):
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD', None)
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', HF_HOME=str(cache),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TORCH_FORCE_WEIGHTS_ONLY_LOAD='1')
    return env


def self_check(engine, worker, pack, cache, log):
    check_files(engine)
    python = engine / 'runtime' / 'python.exe'
    env = child_env(cache / 'hf-cache')
    with log.open('wb') as stderr:
        if not pack:
            probe = ("import sys,os; from pathlib import Path; p=Path.cwd(); "
                     "sys.path[:0]=[str(p),str(p/'GPT_SoVITS')]; "
                     "os.environ['bert_path']=str(p/'GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large'); "
                     "import packs,torch,torchaudio; from TTS_infer_pack.TTS import TTS,TTS_Config; "
                     "assert hasattr(torch.serialization,'add_safe_globals'); "
                     "from text.english import g2p; assert len(g2p('Hello, I love you.')) > 5")
            subprocess.run([str(python), '-c', probe], check=True, cwd=engine, env=env,
                           stderr=stderr, stdout=stderr, timeout=180, creationflags=NO_WINDOW)
            return
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            output = Path(tmp) / 'check.wav'
            query = dict(cmd='synthesize', id='setup', text='你好呀，Hello！今天也一起听歌吧。', output=str(output))
            proc = subprocess.run([str(python), str(worker), str(engine), str(pack)],
                                  input=(json.dumps(query, ensure_ascii=False) + '\n').encode(), cwd=engine, env=env,
                                  stdout=subprocess.PIPE, stderr=stderr, timeout=420, creationflags=NO_WINDOW)
            events = [json.loads(s.split(' ', 1)[1]) for s in proc.stdout.decode('utf-8', 'replace').splitlines()
                      if s.startswith('TIANYI_SPEECH ')]
            if proc.returncode or not any(e.get('type') == 'completed' and e.get('id') == 'setup'
                                          and Path(e.get('path', '')) == output for e in events):
                reason = next((e.get('message') for e in events if e.get('type') in ('fatal', 'failed')), '')
                raise ValueError('语音合成自检失败。' + (reason or '请查看安装日志。'))
            with wave.open(str(output), 'rb') as audio:
                if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or not audio.getnframes():
                    raise ValueError('自检生成的 WAV 无效。')


def prepare_engine(engine, resources):
    check_files(engine)
    scripts = engine / 'deskpet-voice'
    scripts.mkdir(exist_ok=True)
    for name in ('packs.py', 'worker.py'):
        shutil.copyfile(resources / name, scripts / name)
    # The official embedded Python isolates sys.path, even for scripts passed by filename.
    pth = engine / 'runtime' / 'python39._pth'
    original = pth.read_bytes()
    if b'../deskpet-voice' not in original.splitlines():
        pth.write_bytes(original.rstrip() + b'\r\n../deskpet-voice\r\n')
    # _pth enables isolation, so PYTHONIOENCODING alone cannot protect Chinese JSON on pipes.
    (scripts / 'sitecustomize.py').write_text(
        "import sys\nfor stream in (sys.stdin, sys.stdout, sys.stderr):\n"
        "    if stream is not None and hasattr(stream, 'reconfigure'):\n"
        "        stream.reconfigure(encoding='utf-8')\n", encoding='ascii')
    if b'import site' not in (line.strip() for line in pth.read_bytes().splitlines()):
        with pth.open('ab') as stream:
            stream.write(b'import site\r\n')


def install(parent, pack, local_archive, resources, notify, *, data=DATA, register=True, cancel=None):
    parent = parent.resolve()
    store = parent / RUNTIME_NAME
    if store.exists() and not (store / '.tianyi-voice-installer').is_file():
        raise ValueError('选择的位置已有同名目录，请选择其他位置。')
    if pack:
        pack = pack.resolve()
        check_pack(pack)
    with exclusive(data / 'voice-setup'):
        store.mkdir(parents=True, exist_ok=True)
        (store / '.tianyi-voice-installer').touch()
        engine = store / TOP
        log = data / 'voice-setup' / 'install.log'
        marker = engine / '.deskpet-runtime-sha256'
        if not (marker.is_file() and marker.read_text().strip() == SHA256):
            if engine.exists():
                raise ValueError('运行环境目录不完整或属于其他程序，请选择其他安装位置。')
            work = store / 'download'
            work.mkdir(exist_ok=True)
            archive = local_archive
            # The pinned archive expands to 14,964,402,944 bytes. Leave space for a pack and its cache.
            need = 16 * 1024**3
            if not archive and not (work / NAME).exists() and not (work / (NAME + '.partial')).exists():
                need += SIZE
            if shutil.disk_usage(store).free < need:
                raise ValueError('所选盘的空间不足，请选择约有 25 GiB 空闲的位置。')
            if archive:
                notify('正在校验已下载的官方整合包…')
                if archive.stat().st_size != SIZE or digest(archive) != SHA256:
                    raise ValueError('所选 7z 与本版官方 v2Pro 整合包的 SHA-256 不符。')
            else:
                archive = fetch_archive(work, lambda n, total: notify(
                    f'正在下载公共环境  {n / 1e9:.2f} / {total / 1e9:.2f} GB', 65 * n / total), cancel=cancel)
            notify('正在解压公共运行环境，请保留此窗口…', 67)
            tool = resources / '7zr.exe'
            if not tool.is_file():
                tool = fetch_tool(work)
            from download import EXTRACTOR_SHA
            if digest(tool) != EXTRACTOR_SHA:
                raise ValueError('解压工具校验失败。')
            with tempfile.TemporaryDirectory(prefix='extract-', dir=store) as scratch:
                with log.open('wb') as diagnostics:
                    subprocess.run([str(tool), 'x', '-y', '-bso0', '-bsp0', '-o' + scratch, str(archive)],
                                   check=True, stdout=diagnostics, stderr=diagnostics, creationflags=NO_WINDOW)
                staged = Path(scratch) / TOP
                prepare_engine(staged, resources)
                (staged / marker.name).write_text(SHA256)
                staged.rename(engine)
        notify('正在用所选语音包实际合成一句话…' if pack else '正在检查 Python、推理引擎和公共底模…', 92)
        # Use the final path to catch activation and relocation errors before configuring the pet.
        self_check(engine, engine / 'deskpet-voice' / 'worker.py', pack, data / 'chat/speech', log)
        folder = data / '语音包'
        folder.mkdir(exist_ok=True)
        active = import_pack(pack, folder) if pack else None
        if register:
            set_paths(engine / 'runtime/python.exe', engine, active)
        own_download = store / 'download' / NAME
        if own_download.is_file() and (local_archive is None or own_download.resolve() != local_archive.resolve()):
            own_download.unlink()
        return engine
