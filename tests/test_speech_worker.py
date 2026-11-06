import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WorkerProtocolTests(unittest.TestCase):
    def test_reuses_model_and_keeps_engine_logs_out_of_protocol(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / 'GPT_SoVITS' / 'TTS_infer_pack'
            package.mkdir(parents=True)
            (root / 'torch.py').write_text('class Serialization:\n def add_safe_globals(self, classes):\n  assert len(classes)==1 and classes[0].__module__==\"utils\" and classes[0].__name__==\"HParams\"\n  self.registered=True\nserialization=Serialization()\nclass inference_mode:\n def __enter__(self): pass\n def __exit__(self, *args): pass\n', encoding='utf8')
            (package.parent / 'utils.py').write_text('class HParams: pass\n', encoding='utf8')
            (package / '__init__.py').write_text('', encoding='utf8')
            (package / 'TTS.py').write_text('''import numpy as np, os, torch\nclass TTS:\n def __init__(self, cfg):\n  assert os.environ['HF_HUB_OFFLINE'] == '1' and os.environ['TRANSFORMERS_OFFLINE'] == '1' and os.environ['TORCH_FORCE_WEIGHTS_ONLY_LOAD'] == '1'\n  print("loading log")\n  self.text_preprocessor=self\n def set_ref_audio(self, audio): pass\n def preprocess(self, *args): pass\n def run(self, inputs):\n  print("engine log")\n  yield 24000, np.array([0, 1200, -1200, 0], dtype=np.int16)\n''', encoding='utf8')
            resource = root / 'resource'
            resource.write_bytes(b'x')
            config = root / 'config.json'
            config.write_text(json.dumps({'model': {**{k: str(resource) for k in ('t2s_weights_path', 'vits_weights_path', 'bert_base_path', 'cnhuhbert_base_path')}, 'version': 'v2'}, 'reference': {'audio': str(resource), 'text': '你好'}}), encoding='utf8')
            paths = [root / 'one.wav', root / 'two.wav']
            commands = ''.join(json.dumps({'cmd': 'synthesize', 'id': i, 'text': '你好', 'output': str(path)}, ensure_ascii=False) + '\n' for i, path in enumerate(paths))
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            worker = Path(__file__).resolve().parent.parent / 'deskpet' / 'speech' / 'worker.py'
            result = subprocess.run([sys.executable, str(worker), str(root), str(config)], input=commands,
                                    encoding='utf8', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=env, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = [json.loads(line.removeprefix('TIANYI_SPEECH ')) for line in result.stdout.splitlines()]
            self.assertEqual([e['type'] for e in events], ['ready', 'completed', 'completed'])
            self.assertTrue(all(path.exists() for path in paths))
            self.assertEqual(result.stderr.count('loading log'), 1)
            self.assertNotIn('engine log', result.stdout)


if __name__ == '__main__': unittest.main()
