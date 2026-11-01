"""Optional prone pose; timing and interruption remain owned by PetBehavior."""
import json
from pathlib import Path
from deskpet.paths import RESOURCE_ROOT

ROOT = RESOURCE_ROOT / 'assets' / 'live2d' / 'tianyi-crawl'


class CrawlPose:
    def __init__(self, renderer):
        self.model = None
        self.renderer = renderer

    def draw(self, seconds):
        from deskpet.animation.live2d_motion import Curve
        if self.model is None:
            data = json.loads((ROOT / 'tianyi-crawl.model3.json').read_text('utf8'))
            refs = data['FileReferences']
            motion = json.loads((ROOT / refs['Motions']['Crawl'][0]['File']).read_text('utf8'))
            self.duration = float(motion['Meta']['Duration'])
            if self.duration <= 0:
                raise ValueError('蛄蛹动作时长无效')
            self.curves = [(c['Id'], Curve(c['Segments'])) for c in motion['Curves']
                           if c['Target'] == 'Parameter']
            for key in ('Motions', 'Pose', 'Expressions'):
                refs.pop(key, None)
            data['Groups'] = []
            self.model = self.renderer.live2d.Model()
            self.model.LoadFromJsonString(json.dumps(data), root_path=str(ROOT.resolve()) + '/')
            self.model.SetAutoBlink(False)
            self.model.SetAutoBreath(False)
            self.model.Resize(832, 576)
            if not {key for key, _ in self.curves} <= set(self.model.GetParamIds()):
                raise ValueError('蛄蛹模型缺少动作参数')
        for key, curve in self.curves:
            self.model.SetSaveParamById(key, curve.sample(max(0, seconds) % self.duration))
        self.model.Update(0)
        self.model.Draw()

    def close(self):
        if self.model is not None:
            self.model.DestroyRenderer()
            self.model = None
