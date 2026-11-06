"""Private JSONL worker for an independently installed GPT-SoVITS runtime."""
import json
import os
import sys
import wave
from pathlib import Path

protocol = sys.stdout
sys.stdout = sys.stderr
os.environ['TORCH_FORCE_WEIGHTS_ONLY_LOAD'] = '1'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ.pop('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD', None)


def emit(**value):
    protocol.write('TIANYI_SPEECH ' + json.dumps(value, ensure_ascii=False) + '\n')
    protocol.flush()


def main():
    # Leave CPU capacity for the animation and the rest of the desktop.
    threads = str(min(4, max(1, (os.cpu_count() or 2) // 2)))
    os.environ.setdefault('OMP_NUM_THREADS', threads)
    os.environ.setdefault('MKL_NUM_THREADS', threads)
    if sys.platform == 'win32':
        # Let desktop interaction win CPU time while this process loads the model.
        import ctypes
        import subprocess
        kernel = ctypes.windll.kernel32
        current_process = ctypes.c_void_p(-1)
        if kernel.GetPriorityClass(current_process) == subprocess.NORMAL_PRIORITY_CLASS:
            kernel.SetPriorityClass(current_process, subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    import numpy as np
    engine = Path(sys.argv[1]).resolve()
    config_path = Path(sys.argv[2]).resolve()
    cache = Path(os.environ.get('HF_HOME', str(config_path.parent / 'cache' / 'huggingface'))).parent
    packed = config_path.suffix.lower() == '.zip'
    if packed:
        from packs import pack_config
        from zipfile import BadZipFile
        shared_path = engine.parent / 'speech-config.json'
        shared = json.loads(shared_path.read_text(encoding='utf-8-sig')) if shared_path.is_file() else {}
        try:
            config = pack_config(config_path, engine, cache / 'voice-packs', shared)
        except BadZipFile as exc:
            raise ValueError('语音包损坏或尚未复制完成，请重新放入 ZIP 后试听') from exc
    else:
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    os.chdir(engine)
    sys.path.insert(0, str(engine))
    sys.path.insert(0, str(engine / 'GPT_SoVITS'))
    # The upstream Chinese G2PW frontend reads this separately from TTS_Config.
    # Without it, a correctly loaded acoustic model still fails on its first text.
    os.environ['bert_path'] = str(Path(config['model']['bert_base_path']).resolve())
    os.environ['PATH'] = str(engine / 'runtime') + os.pathsep + os.environ.get('PATH', '')
    for name, folder in (('TORCH_HOME', 'torch'), ('MPLCONFIGDIR', 'matplotlib')):
        os.environ[name] = str(cache / folder)
    import torch
    if packed and 'device' not in config['model']:
        config['model']['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
        config['model']['is_half'] = config['model']['device'] == 'cuda'
    from utils import HParams
    if HParams.__module__ != 'utils':
        raise ValueError('不支持的 HParams 类型')
    # Official GPT-SoVITS HParams is a plain configuration container. Register
    # only this exact pickle global; weights-only enforcement remains enabled.
    torch.serialization.add_safe_globals([HParams])
    from TTS_infer_pack.TTS import TTS
    model = config['model']
    for key in ('t2s_weights_path', 'vits_weights_path', 'bert_base_path', 'cnhuhbert_base_path'):
        if not Path(model[key]).exists():
            raise ValueError('模型资源缺失: ' + key)
    reference = config['reference']
    if not Path(reference['audio']).is_file() or not reference['text'].strip():
        raise ValueError('参考音频或文字未配置')
    options = config.get('inference', {})
    sample_steps = int(options.get('sample_steps', 16))
    speed = float(options.get('speed_factor', 1.0))
    if sample_steps not in (4, 8, 16, 32, 64) or not 0.5 <= speed <= 2.0:
        raise ValueError('语音采样步数或语速设置无效')
    if packed:
        from tempfile import TemporaryDirectory
        from TTS_infer_pack.TTS import TTS_Config
        # Upstream saves its last-used weights during initialization. Keep
        # those writes private to this worker, even on a read-only install.
        with TemporaryDirectory(dir=cache) as work:
            options_config = TTS_Config({'custom': model})
            options_config.configs_path = str(Path(work) / 'tts_infer.yaml')
            tts = TTS(options_config)
    else:
        tts = TTS({'custom': model})
    # Prepare the supplied voice reference and lazy Chinese language frontend.
    # This creates no speech and removes their cold-start work from the reply.
    with torch.inference_mode():
        tts.set_ref_audio(reference['audio'])
        tts.text_preprocessor.preprocess(reference['text'], reference.get('language', 'zh'),
                                        'cut5', model['version'])
    emit(type='ready')
    for line in sys.stdin:
        command = None
        try:
            command = json.loads(line)
            if command.get('cmd') != 'synthesize':
                continue
            job = command['id']
            output = Path(command['output'])
            if output.exists():
                raise ValueError('输出文件已存在')
            chunks = list(tts.run(dict(text=command['text'], text_lang='zh',
                                       ref_audio_path=reference['audio'], prompt_text=reference['text'],
                                       prompt_lang=reference.get('language', 'zh'),
                                       text_split_method='cut5', batch_size=1, streaming_mode=False,
                                       parallel_infer=False, sample_steps=sample_steps,
                                       speed_factor=speed, return_fragment=False,
                                       fragment_interval=0.2, use_cuda_graph=False,
                                       use_flash_attention=False, super_sampling=False)))
            if not chunks or len({int(rate) for rate, _ in chunks}) != 1:
                raise ValueError('合成未返回有效音频')
            rate = int(chunks[0][0])
            audio = np.concatenate([np.asarray(samples).reshape(-1) for _, samples in chunks])
            if audio.size == 0 or not np.isfinite(audio).all() or not np.any(np.abs(audio.astype(np.float64)) > (0.0005 if audio.dtype.kind == 'f' else 16)):
                raise ValueError('合成音频为空或静音')
            if audio.dtype.kind == 'f':
                audio = np.clip(audio, -1, 1) * 32767
            audio = np.clip(audio, -32768, 32767).astype('<i2')
            with wave.open(str(output), 'wb') as wav:
                wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                wav.writeframes(audio.tobytes())
            emit(type='completed', id=job, path=str(output))
        except Exception as exc:
            emit(type='failed', id=command.get('id') if isinstance(command, dict) else None,
                 message=str(exc)[:300])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit(type='fatal', message=str(exc)[:300])
        sys.exit(1)
