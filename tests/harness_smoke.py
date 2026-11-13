"""Manual no-key real-runtime regression: python tests/harness_smoke.py.
Fails if tool execution, approval, restoration or output markers are missing.
"""
import json
import queue
import subprocess
import threading
import time
import tempfile
import shutil
import uuid
import argparse
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--strict-path', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--followup-only', action='store_true',
                        help='Check in-flight and late inputs using only a local text response')
    parser.add_argument('--runtime', type=Path, help='Isolated official runtime to test')
    options = parser.parse_args()
    fresh_runtime = bool(options.runtime and not (options.runtime / 'deskpet-runtime-ready.json').exists())
    scratch_root = ROOT / 'local-work' / 'harness-package-checks'
    scratch_root.mkdir(parents=True, exist_ok=True)
    workspace=Path(tempfile.mkdtemp(prefix='smoke-', dir=scratch_root)).resolve()
    assert workspace.is_relative_to(scratch_root.resolve())
    output=workspace/'result.txt'
    denied_marker=workspace/'denied.txt'
    state={'step':0,'requests':[]}
    followups_ready = threading.Event()
    tools=[('write',{'file_path':str(output),'content':'HARNESS_WRITE_OK'}),
           ('read',{'file_path':str(output)}),
           ('pwsh',{'description':'Verify local command execution','command':"Write-Output 'HARNESS_COMMAND_OK'"}),
           ('pwsh',{'description':'Verify denial prevents marker creation','command':"Set-Content -LiteralPath '"+str(denied_marker)+"' -Value denied",'sandbox_permissions':'danger-full-access','justification':'Verify rejection of this one test command'}),
           ('pwsh',{'description':'Verify approved exact command execution','command':"Write-Output 'HARNESS_APPROVED_OK'",'sandbox_permissions':'danger-full-access','justification':'Verify approval of this one test command'})]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(data)
            state['step']+=1
            step=state['step']
            if options.followup_only and step == 1:
                followups_ready.wait(timeout=15)
            events=[('message_start',{'type':'message_start','message':{'id':'fake','type':'message','role':'assistant','model':'deepseek-flash','content':[],'usage':{'input_tokens':1,'output_tokens':0}}})]
            if step<=len(tools):
                name,args=tools[step-1]
                events += [('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'call_'+str(step),'name':name,'input':{}}}),('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':json.dumps(args)}})]
                reason='tool_use'
            else:
                events += [('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}),('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'LOCAL_FAKE_OK'}})]
                reason='end_turn'
            events += [('content_block_stop',{'type':'content_block_stop','index':0}),('message_delta',{'type':'message_delta','delta':{'stop_reason':reason},'usage':{'output_tokens':4}}),('message_stop',{'type':'message_stop'})]
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for kind,event in events:self.wfile.write(('event: '+kind+'\ndata: '+json.dumps(event)+'\n\n').encode())
    server=HTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    processes=[]
    stderr_path=workspace/'worker-stderr.log'
    stderr_log=stderr_path.open('w',encoding='utf-8')
    events=[]
    approvals=[]
    payload=dict(workspace=str(workspace),home=str(workspace/'home'),model='deepseek-flash',api_key='fake-secret-only',base_url=f'http://127.0.0.1:{server.server_port}/v1',session_id=uuid.uuid4().hex,prompt='Execute the deterministic local test tools')
    if options.runtime:
        payload['runtime_dir'] = str(options.runtime.resolve())
    def run_turn(resume=False, cancel=False):
        payload['resume']=resume
        command = ([str(options.worker.resolve()), '--harness-worker'] if options.worker else
                   [str(ROOT/'.harness-venv/Scripts/python.exe'),'-u','-m','deskpet.chat.harness_worker'])
        environment = os.environ.copy()
        if options.strict_path:
            windows = Path(environment.get('SystemRoot', 'C:/Windows'))
            environment['PATH'] = os.pathsep.join(map(str, (windows/'System32', windows)))
        process=subprocess.Popen(command,cwd=workspace if options.worker else ROOT,env=environment,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr_log,text=True,encoding='utf-8',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        processes.append(process)
        messages=queue.Queue()
        def read():
            for line in process.stdout:messages.put(json.loads(line))
            messages.put(None)
        threading.Thread(target=read,daemon=True).start()
        process.stdin.write(json.dumps(payload)+'\n');process.stdin.flush()
        deadline=time.monotonic()+1200
        sent = 0
        def control(**fields):
            process.stdin.write(json.dumps(fields)+'\n')
            process.stdin.flush()
        while time.monotonic()<deadline:
            event=messages.get(timeout=max(.1,deadline-time.monotonic()))
            assert event is not None,'worker ended without terminal event'
            events.append(event)
            if options.followup_only:
                data = event.get('event', {})
                if data.get('event', {}).get('type') == 'step/start' and sent == 0:
                    for seq in (1, 2):
                        control(type='followup', seq=seq, text=f'DESKPET_FOLLOWUP_{seq}')
                    sent = 2
                if data.get('type') == 'input_received' and data.get('seq') == 2:
                    followups_ready.set()
                if event['type'] == 'idle':
                    if sent == 2:
                        control(type='followup', seq=3, text='DESKPET_LATE_3')
                        sent = 3
                    control(type='finish_turn', seq=event['seq'])
            if event['type']=='approval':
                approvals.append(event['request'])
                if cancel:
                    process.stdin.write(json.dumps({'type':'cancel'})+'\n');process.stdin.flush()
                    deadline=time.monotonic()+10
                    continue
                allowed=len(approvals)>1
                process.stdin.write(json.dumps({'type':'approval','id':event['request']['id'],'approved':allowed})+'\n');process.stdin.flush()
            if event['type'] in ('completed','failed'):
                if cancel:
                    assert event['type']=='failed' and '停止' in event['text'],event
                else:
                    assert event['type']=='completed',event
                    assert event['text']=='LOCAL_FAKE_OK',event
                process.wait(timeout=10)
                return
        raise AssertionError('overall worker timeout')
    try:
        if options.followup_only:
            tools.clear()
            payload['interactive'] = True
            run_turn()
            bodies = [e['event'] for e in events if e['type'] == 'event']
            assert [b['seq'] for b in bodies if b['type'] == 'input_received'] == [0, 1, 2, 3]
            assert [e['seq'] for e in events if e['type'] == 'idle'] == [2, 3]
            inserts = [b['event']['data'] for b in bodies if b.get('event', {}).get('type') == 'agent/inbox/spliced']
            steered = [m for i in inserts if i['target']=='next-step' for m in i['inserted']]
            for seq in (1, 2):
                assert f'DESKPET_FOLLOWUP_{seq}' in json.dumps(steered), 'input missed the running turn'
            assert 'DESKPET_LATE_3' in json.dumps(state['requests'][-1])
            print('PASS real DSH: two next-step inputs, one late follow-up, one session, zero paid API calls')
            return
        run_turn()
        setup_events = [e for e in events if e.get('type') == 'progress' and e.get('phase') == 'setup']
        if fresh_runtime:
            assert setup_events, 'missing first-use setup progress'
            assert (options.runtime / 'deskpet-runtime-ready.json').is_file(), 'setup did not publish a ready runtime'
        assert output.read_text()=='HARNESS_WRITE_OK'
        tool_results=[e['event']['event']['data']['message'] for e in events if e['type']=='event' and e.get('event',{}).get('event',{}).get('type')=='tool/result']
        text=json.dumps(tool_results)
        assert 'HARNESS_WRITE_OK' in text,'read result missing'
        assert 'HARNESS_COMMAND_OK' in text and any(not x.get('isError') and 'HARNESS_COMMAND_OK' in json.dumps(x) for x in tool_results),'sandbox command did not execute'
        assert len(approvals)>=2,'approval channel did not deliver rejection and allowance'
        assert not denied_marker.exists(),'rejected command executed'
        assert any(not x.get('isError') and 'HARNESS_APPROVED_OK' in json.dumps(x) for x in tool_results),'approved command did not execute'
        run_turn(True)
        assert len(state['requests'])>=7,'resumed turn did not call model'
        assert 'LOCAL_FAKE_OK' in json.dumps(state['requests'][-1]),'resumed history missing'
        cancel_marker=workspace/'cancelled.txt'
        tools[:]=[('pwsh',{'description':'Verify cancellation prevents command execution','command':"Set-Content -LiteralPath '"+str(cancel_marker)+"' -Value cancelled",'sandbox_permissions':'danger-full-access','justification':'Test cancellation at a pending approval'})]
        state['step']=0
        payload['home']=str(workspace/'cancel-home')
        payload['session_id']=uuid.uuid4().hex
        run_turn(cancel=True)
        assert not cancel_marker.exists(),'cancelled command executed'
        state['step']=100
        payload['home']=str(workspace/'after-cancel-home')
        payload['session_id']=uuid.uuid4().hex
        run_turn()
        print('PASS real runtime: write/read/command, approval reject/allow, session resume, pending-approval cancellation, new session recovery')
        if options.report:
            options.report.parent.mkdir(parents=True, exist_ok=True)
            options.report.write_text(json.dumps(dict(ok=True, packaged=bool(options.worker),
                strict_path=options.strict_path, write=True, read=True, command=True,
                first_use_setup=fresh_runtime, setup_progress=bool(setup_events),
                approval_reject=True, approval_allow=True, resume=True, cancellation=True,
                new_session_after_cancel=True, paid_api_calls=0), indent=2), encoding='utf-8')
    finally:
        for process in processes:
            if process.poll() is None:
                subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=8)
                process.wait(timeout=5)
        server.shutdown();server.server_close()
        stderr_log.close()
        if __import__('sys').exc_info()[0] is not None:
            print(stderr_path.read_text('utf-8',errors='replace')[-6000:])
        shutil.rmtree(workspace,ignore_errors=True)

if __name__=='__main__':main()
