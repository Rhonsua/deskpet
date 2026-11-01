"""Compose official risk review, with human approval retained for denied calls."""
import json
from pathlib import Path
from .harness_runtime import INSTALL


def write_runtime_patch(home, session_id, auto_approve=False, *, install=None):
    review = (Path(install) if install else INSTALL) / 'node_modules/@deepseek-ai/dsh-experimental-auto-review/lib/index.js'
    bridge = Path(__file__).with_name('harness_permission_bridge.mjs')
    if not review.is_file() or not bridge.is_file():
        raise ValueError('工作环境缺少自动审批组件，请重新安装工作环境；未放行任何操作。')
    # Keep Auto mounted even when disabled, so a saved Auto session can be restored
    # and reset to workspace-write before its next step instead of failing to load.
    rows = [
        {'id':'session-log-deepseek','config':{'enabled':False}},
        {'id':'session-telemetry-otel','disabled':True},
        {'id':'sandbox-policy','config':{'mode':'workspace-write'}},
        {'id':'approval','config':{'policy':'ask'}},
        {'id':'permission','config':{'defaultPreset':'workspace-write'}},
        {'insert':[
            {'id':'deskpet-auto-review','name':str(review)},
            {'id':'deskpet-permission-mode','name':str(bridge),
             'config':{'sessionId':session_id,'autoApprove':auto_approve is True}},
        ]},
    ]
    path = Path(home) / 'privacy.patch.yml'
    # JSON is a YAML subset; avoid hand-escaping Windows paths or user values.
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    return path
