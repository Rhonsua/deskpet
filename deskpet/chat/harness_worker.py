"""Isolated Harness worker. stdin/stdout are JSONL; credentials never become argv."""
import json
import os
import sys
import threading
import uuid
import re
import time
from types import SimpleNamespace
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')

_lock = threading.Lock()
_secret = ''

def redact(value):
    if isinstance(value, dict):
        return {k: ('[已隐藏]' if re.search(r'api.?key|authorization|access.?token', k, re.I) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        if _secret:
            value = value.replace(_secret, '[已隐藏]')
        return re.sub(r'([?&]token=)[^\s&]+', r'\1[已隐藏]', value)
    return value

def emit(kind, **fields):
    with _lock:
        print(json.dumps(redact(dict(type=kind, **fields)), ensure_ascii=False), flush=True)

def main():
    global _secret
    request = json.loads(sys.stdin.readline())
    _secret = request['api_key']
    cancelled = threading.Event()
    pending = {}
    holder = SimpleNamespace(client=None)

    def controls():
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if command.get('type') == 'cancel':
                    cancelled.set()
                    if holder.client:
                        holder.client.close()
                    return
                key = str(command.get('id'))
                if holder.client and key in pending:
                    holder.client.respond(pending.pop(key), {'outcome': 'allowed-once' if command.get('approved') is True else 'rejected'})
            except Exception:
                pass
        cancelled.set()  # Parent closed its pipe; don't keep installing/running.
        if holder.client:
            holder.client.close()

    threading.Thread(target=controls, daemon=True).start()
    from deepseek_harness import HarnessClient, HarnessConfig
    from deepseek_harness.api import Session
    from deepseek_harness.models import InitializeResponse
    root = Path(request['workspace']).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('工作目录不存在')
    home = Path(request['home']).resolve()
    home.mkdir(parents=True, exist_ok=True)
    origin = home / 'workspace.json'
    if origin.exists() and json.loads(origin.read_text(encoding='utf-8')).get('workspace') != str(root):
        emit('failed', text='该工作会话属于另一个文件夹，请新建工作会话。')
        return
    origin.write_text(json.dumps({'workspace':str(root)}), encoding='utf-8')
    from .harness_runtime import runtime_directory, runtime_launch_args
    from .harness_bootstrap import ensure_runtime, SetupCancelled
    install = Path(request.get('runtime_dir') or runtime_directory())
    try:
        npm_cli = ensure_runtime(install,
            progress=lambda text: emit('progress', phase='setup', text=text), cancelled=cancelled)
    except SetupCancelled:
        emit('failed', text='工作已停止。')
        return
    except Exception as error:
        emit('event', event={'type': 'failed', 'stage': 'setup', 'detail': str(error)[:2000]})
        emit('failed', text='工作环境未准备完成，任务尚未提交；可直接重试。\n' + str(error)[:400])
        return
    from .work_permissions import write_runtime_patch
    patch = write_runtime_patch(home, request['session_id'], request.get('auto_approve') is True, install=install)
    launch_args = runtime_launch_args(npm_cli, patch)
    environment = {'DEEPSEEK_API_KEY': request['api_key'],
        'DEEPSEEK_BASE_URL': request['base_url'], 'DSH_TELEMETRY_DISABLED':'1',
        'DSH_PERMISSION_MODE':'workspace-write', 'DSH_HOME':str(home)}
    # Expose the private Node to backend tools without changing global PATH.
    environment['PATH'] = str(Path(launch_args[0]).parent) + os.pathsep + os.environ.get('PATH', '')
    client = HarnessClient(HarnessConfig(dsh_bin=str(npm_cli), cwd=str(root), dsh_home=str(home), profile='sdk',
        patches=(str(patch),), env=environment), _launch_args=launch_args)
    holder.client = client
    harness = SimpleNamespace(client=client, start=lambda: None, close=client.close)
    started_at = time.monotonic()
    stage = 'launch'
    ready = False
    session_id = request['session_id']
    def session_ready():
        nonlocal ready
        if ready:
            return
        # Only after successful resume or receipt of the accepted prompt's
        # session notifications, never merely after initialize.
        (home / 'session-ready').write_text(session_id, encoding='utf-8')
        ready = True
        emit('event', event={'type':'session_ready', 'session_id':session_id})
    def approvals():
        try:
            while True:
                incoming = harness.client.next_request()
                if incoming.method == 'approval/request':
                    pending[str(incoming.id)] = incoming.id
                    emit('approval', request=dict(incoming.payload, id=str(incoming.id)))
                else:
                    harness.client.respond_error(incoming.id, code=-32601, message='Unsupported client request')
        except Exception:
            pass
    try:
        if cancelled.is_set():
            raise RuntimeError('工作已停止。')
        emit('progress', text='正在启动工作后端…')
        client.start()
        if cancelled.is_set():
            raise RuntimeError('工作已停止。')
        threading.Thread(target=approvals, daemon=True).start()
        stage = 'initialize'
        client.request('initialize', {'cwd':str(root), 'provider':'deepseek-official',
                       'model':request['model'], 'approvalRequests':True},
                       response_model=InitializeResponse, timeout_seconds=90)
        emit('event', event={'type':'runtime_ready', 'elapsed_seconds':round(time.monotonic()-started_at, 2)})
        if cancelled.is_set():
            raise RuntimeError('工作已停止。')
        if request.get('resume'):
            stage = 'resume'
            client.resume_session(session_id)
            session_ready()
        emit('event', event={'type':'started', 'session_id':session_id})
        def progress(notification):
            payload = notification.payload
            if payload.get('sessionId') == session_id:
                session_ready()
            structured = dict(payload, type=notification.method)
            if len(json.dumps(structured)) < 200000:
                emit('event', event=structured)
            event = payload.get('event', {})
            kind = event.get('type', '')
            labels = {'turn/start':'正在思考…', 'tool/call':'正在执行工具…', 'tool/result':'工具执行结束', 'turn/end':'本轮处理结束'}
            if kind in labels:
                emit('progress', text=labels[kind])
        stage = 'prompt'
        result = Session(harness, session_id).run(request['prompt'], on_notification=progress)
        session_ready()
        if result.finish_reason == 'error':
            detail = next((str(item.get('data', {}).get('reason', {}).get('error', {}).get('message', '')) for item in reversed(result.events) if item.get('type') == 'turn/end'), '')
            emit('event', event={'type':'failed','detail':redact(detail)[:2000]})
            emit('failed', text=result.final_response or ('工作运行失败：' + redact(detail)[:300] if detail else '工作运行失败，请查看状态详情。'))
        else:
            emit('completed', text=result.final_response, session_id=session_id)
    except Exception as error:
        if cancelled.is_set():
            emit('event', event={'type':'cancelled'})
            emit('failed', text='工作已停止。')
        else:
            detail = redact(str(error))[:2000]
            emit('event', event={'type':'failed','stage':stage,
                 'elapsed_seconds':round(time.monotonic()-started_at, 2),'detail':detail})
            if stage in ('launch', 'initialize'):
                emit('failed', text='工作后端未能启动，任务尚未提交；输入已保留，可直接重试。\n' + (detail[:300] or type(error).__name__))
            else:
                emit('failed', text='工作失败：' + (detail[:300] or type(error).__name__))
    finally:
        harness.close()

def run():
    try:
        main()
    except Exception as error:
        detail = redact(str(error))[:2000]
        emit('event', event={'type':'failed','detail':detail})
        emit('failed', text='无法启动工作：' + (detail[:300] or type(error).__name__))
        sys.exit(1)


if __name__ == '__main__':
    run()
