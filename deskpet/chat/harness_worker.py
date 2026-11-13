"""Isolated Harness worker. stdin/stdout are JSONL; credentials never become argv."""
import json
import os
import queue
import sys
import threading
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

def run_conversation(client, request, commands, progress, session_ready):
    """Multiplex native composer input and DSH events on one session subscription."""
    from deepseek_harness.api import final_response, finish_reason
    session_id = request['session_id']
    awaiting = {}
    results = []
    seq = 0
    idle = False
    received_first = False

    def submit(number, text):
        message_id = client.session_prompt(session_id, [{'type': 'text', 'text': text}])
        awaiting[message_id] = number

    with client.subscribe_session_notifications(session_id) as subscription:
        def notifications():
            try:
                while True:
                    commands.put(('notification', subscription.next()))
            except Exception as error:
                commands.put(('error', error))

        submit(0, request['prompt'])
        threading.Thread(target=notifications, daemon=True).start()
        while True:
            kind, value = commands.get()
            if kind == 'error':
                raise value
            if kind == 'followup':
                seq = value['seq']
                idle = False
                submit(seq, value['text'])
                continue
            if kind == 'finish_turn':
                if idle and value['seq'] == seq:
                    break
                continue
            payload = value.payload
            root = payload.get('sessionId') == session_id
            event = payload.get('event', {})
            if root and value.method == 'session.event' and event.get('type') == 'agent/inbox/spliced':
                for message in event['data']['inserted']:
                    number = awaiting.pop(message.get('id'), None)
                    if number is not None:
                        if number == 0:
                            received_first = True
                            session_ready()
                        emit('event', event={'type':'input_received', 'seq':number})
            if not received_first:
                continue
            progress(value)
            if root and value.method == 'session.event' and event.get('type') in ('assistant/message', 'turn/end'):
                results.append(event)
            if root and value.method == 'session.status':
                idle = payload.get('status') == 'idle' and not awaiting
                if idle:
                    if not request.get('interactive'):
                        break
                    # A last keystroke can cross this notification in transit.
                    # Only the composer knows whether it has sent a newer input.
                    emit('idle', seq=seq)
    return SimpleNamespace(events=results, final_response=final_response(results),
                           finish_reason=finish_reason(results))

def main():
    global _secret
    request = json.loads(sys.stdin.readline())
    _secret = request['api_key']
    cancelled = threading.Event()
    pending = {}
    commands = queue.Queue()
    holder = SimpleNamespace(client=None)

    def controls():
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if command.get('type') == 'cancel':
                    cancelled.set()
                    commands.put(('error', RuntimeError('工作已停止。')))
                    if holder.client:
                        holder.client.close()
                    return
                if command.get('type') in ('followup', 'finish_turn'):
                    commands.put((command['type'], command))
                    continue
                key = str(command.get('id'))
                if command.get('type') == 'approval' and holder.client and key in pending:
                    holder.client.respond(pending.pop(key), {'outcome': 'allowed-once' if command.get('approved') is True else 'rejected'})
            except Exception:
                pass
        cancelled.set()  # Parent closed its pipe; don't keep installing/running.
        commands.put(('error', EOFError('工作窗口已退出。')))
        if holder.client:
            holder.client.close()

    threading.Thread(target=controls, daemon=True).start()
    from deepseek_harness import HarnessClient, HarnessConfig
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
                incoming = client.next_request()
                if incoming.method == 'approval/request':
                    pending[str(incoming.id)] = incoming.id
                    emit('approval', request=dict(incoming.payload, id=str(incoming.id)))
                else:
                    client.respond_error(incoming.id, code=-32601, message='Unsupported client request')
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
            structured = dict(payload, type=notification.method)
            if len(json.dumps(structured)) < 200000:
                emit('event', event=structured)
            event = payload.get('event', {})
            kind = event.get('type', '')
            labels = {'turn/start':'正在思考…', 'tool/call':'正在执行工具…', 'tool/result':'工具执行结束', 'turn/end':'本轮处理结束'}
            if kind in labels:
                emit('progress', text=labels[kind])
        stage = 'prompt'
        result = run_conversation(client, request, commands, progress, session_ready)
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
        client.close()

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
