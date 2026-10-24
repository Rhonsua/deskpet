"""Optional native Live2D renderer; transparent frames reuse the existing pet window."""
import json
from pathlib import Path
from pointer_follow import apply_pointer
from mouse_interactions import apply_active_petting
from lift_reaction import LiftReactionOverlay

MODEL_ROOT = Path(__file__).resolve().parent / 'assets' / 'live2d' / 'tianyi'
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
        from live2d_motion import MotionLibrary
        self.live2d, self.gl = live2d, GL
        self.model = self.fbo = None
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

    def close(self):
        if self.context.makeCurrent(self.surface):
            if self.model is not None:
                self.model.DestroyRenderer()
                self.model = None
            self.fbo = None
            self.live2d.glRelease()
            self.context.doneCurrent()
        self.surface.destroy()
