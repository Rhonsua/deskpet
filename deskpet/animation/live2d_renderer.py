"""Optional native Live2D renderer; transparent frames reuse the existing pet window."""
import json
from pathlib import Path
from deskpet.paths import RESOURCE_ROOT
from deskpet.animation.pointer_follow import apply_pointer
from deskpet.animation.mouse_interactions import apply_active_petting
from deskpet.animation.lift_reaction import LiftReactionOverlay

MODEL_ROOT = RESOURCE_ROOT / 'assets' / 'live2d' / 'tianyi'
# Compare source head widths, not full canvas heights: standing 603px,
# back-sleep 315px, phone 442px. All use the same 1024x1536 coordinate system.
POSE_SCALE = {'sleep': 603 / 315, 'phone': 603 / 442}


class Live2DRenderer:
    def __init__(self, root=MODEL_ROOT):
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
        from PySide6.QtOpenGL import QOpenGLFramebufferObject
        try:
            import live2d
            from OpenGL import GL
        except ImportError as error:
            raise RuntimeError('请先安装 requirements.txt 中的 Live2D 依赖') from error
        from deskpet.animation.live2d_motion import MotionLibrary
        self.live2d, self.gl = live2d, GL
        self.model = self.fbo = None
        self.work_model = None
        from deskpet.animation.crawl_visual import ROOT as CRAWL_ROOT, CrawlPose
        self.crawl_pose = CrawlPose(self)
        self.crawl_fbo = None
        self.crawl_available = (Path(root).resolve() == MODEL_ROOT.resolve()
                                and (CRAWL_ROOT / 'tianyi-crawl.model3.json').is_file())
        self.work_curves = None
        self.work_root = MODEL_ROOT.parent / 'tianyi-work'
        self.work_available = (Path(root).resolve() == MODEL_ROOT.resolve()
                               and (self.work_root / 'tianyi-work.model3.json').is_file())
        self.pointer = (0.0, 0.0, 0.0)
        self.petting = (0.0, 0.0)
        self.resume_activity = 'idle'
        self.context = QOpenGLContext()
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setOption(QSurfaceFormat.FormatOption.DeprecatedFunctions)
        fmt.setAlphaBufferSize(8)
        self.context.setFormat(fmt)
        if not self.context.create():
            raise RuntimeError('无法建立 Live2D OpenGL 上下文')
        self.surface = QOffscreenSurface()
        self.surface.setFormat(self.context.format())
        self.surface.create()
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError('无法激活 Live2D 渲染环境')
        try:
            live2d.enableLog(False)
            live2d.init()
            live2d.glInit()
            self.motions = MotionLibrary(root)
            data = json.loads((Path(root) / self.motions.mapping['model']).read_text(encoding='utf-8'))
            # PetBehavior owns time and visibility, including interrupted/resumed actions.
            data['FileReferences'].pop('Motions', None)
            data['FileReferences'].pop('Pose', None)
            self.model = live2d.Model()
            self.model.LoadFromJsonString(json.dumps(data, indent=2), root_path=str(Path(root).resolve()) + '/')
            self.model.SetAutoBlink(False)
            self.model.SetAutoBreath(False)
            self.parts = {key: i for i, key in enumerate(self.model.GetPartIds())}
            self.parameter_ids = set(self.model.GetParamIds())
            self.motions.validate_walk_model(self.parameter_ids, self.parts)
            self.lift_reaction = LiftReactionOverlay()
            expected = {key for group in self.motions.mapping['poseGroups'] for key in group}
            if not expected <= self.parts.keys() or not self.model.GetParamIds():
                raise RuntimeError('Live2D 模型未完整加载')
            self.model.Resize(384, 576)
            self.fbo = QOpenGLFramebufferObject(384, 576)
            if not self.fbo.isValid():
                raise RuntimeError('无法建立透明 Live2D 绘图缓冲区')
        except Exception:
            self.close()
            raise
        finally:
            self.context.doneCurrent()

    def frame(self, activity, seconds, beat=None):
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError('Live2D 渲染上下文已失效')
        try:
            self.fbo.bind()
            self.gl.glViewport(0, 0, 384, 576)
            self.live2d.clearBuffer(0, 0, 0, 0)
            parameters, parts = self.motions.sample(activity, seconds, beat)
            parameters.setdefault('ParamAngleY', 0.0)
            parameters.setdefault('ParamEyeBallY', 0.0)
            parameters = apply_pointer(parameters, activity, self.pointer)
            parameters = apply_active_petting(parameters, activity, self.petting)
            parameters = self.lift_reaction.apply(
                activity, seconds, parameters, self.parameter_ids,
                resume_activity=self.resume_activity)
            for key, value in parameters.items():
                if key in self.parameter_ids:
                    self.model.SetSaveParamById(key, value)
            for key, value in parts.items():
                self.model.SetPartOpacity(self.parts[key], value)
            self.model.Update(0)
            self.model.Draw()
            return self.fbo.toImage()
        finally:
            self.fbo.release()
            self.context.doneCurrent()

    def frame_work(self, seconds, paused=False):
        """Keep the normal model loaded; both use this one context and FBO."""
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError('无法激活工作动作渲染')
        try:
            if self.work_model is None:
                from deskpet.animation.live2d_motion import Curve
                data = json.loads((self.work_root / 'tianyi-work.model3.json').read_text('utf-8'))
                motion_path = data['FileReferences']['Motions']['WorkTyping'][0]['File']
                motion = json.loads((self.work_root / motion_path).read_text('utf-8'))
                self.work_curves = [(c['Id'], Curve(c['Segments'])) for c in motion['Curves']
                                    if c['Target'] == 'Parameter']
                self.work_duration = motion['Meta']['Duration']
                data['FileReferences'].pop('Motions', None)
                data['FileReferences'].pop('Pose', None)
                self.work_model = self.live2d.Model()
                self.work_model.LoadFromJsonString(json.dumps(data), root_path=str(self.work_root.resolve()) + '/')
                self.work_model.SetAutoBlink(False)
                self.work_model.SetAutoBreath(False)
                self.work_model.Resize(384, 576)
                ids = set(self.work_model.GetParamIds())
                self.work_parameter_ids = ids
                if not {key for key, _ in self.work_curves} <= ids:
                    raise RuntimeError('工作模型缺少动作参数')
            t = 0 if paused else max(0, seconds) % self.work_duration
            for key, curve in self.work_curves:
                self.work_model.SetSaveParamById(key, curve.sample(t))
            from deskpet.animation.work_visual import idle_parameters
            for key, value in idle_parameters(seconds).items():
                if key in self.work_parameter_ids:
                    self.work_model.SetSaveParamById(key, value)
            self.fbo.bind()
            self.gl.glViewport(0, 0, 384, 576)
            self.live2d.clearBuffer(0, 0, 0, 0)
            self.work_model.Update(0)
            self.work_model.Draw()
            return self.fbo.toImage()
        except Exception:
            self.work_available = False
            raise
        finally:
            self.fbo.release()
            self.context.doneCurrent()

    def frame_crawl(self, seconds):
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError('无法激活蛄蛹动作渲染')
        try:
            if self.crawl_fbo is None:
                from PySide6.QtOpenGL import QOpenGLFramebufferObject
                self.crawl_fbo = QOpenGLFramebufferObject(832, 576)
                if not self.crawl_fbo.isValid():
                    raise RuntimeError('无法建立蛄蛹动作画布')
            self.crawl_fbo.bind()
            self.gl.glViewport(0, 0, 832, 576)
            self.live2d.clearBuffer(0, 0, 0, 0)
            self.crawl_pose.draw(seconds)
            return self.crawl_fbo.toImage()
        except Exception:
            self.crawl_available = False
            raise
        finally:
            if self.crawl_fbo is not None:
                self.crawl_fbo.release()
            self.context.doneCurrent()

    def close(self):
        if self.context.makeCurrent(self.surface):
            self.crawl_pose.close()
            self.crawl_fbo = None
            if self.work_model is not None:
                self.work_model.DestroyRenderer()
                self.work_model = None
            if self.model is not None:
                self.model.DestroyRenderer()
                self.model = None
            self.fbo = None
            self.live2d.glRelease()
            self.context.doneCurrent()
        self.surface.destroy()
