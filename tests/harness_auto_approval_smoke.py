"""Real official reviewer/worker; deterministic loopback model, only temp markers."""
import json
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='deskpet-auto-review-') as folder:
        root=Path(folder).resolve()
        state={'step':0,'reviews':0,'mode':'allow','requests':[]}
        tools=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                reviewing='REVIEW_POLICY' in json.dumps(request.get('system',''))
                state['requests'].append(request)
                name=None
                if reviewing:
                    state['reviews']+=1
                    text={'allow':'{"risk":"low","decision":"allow"}',
                          'deny':'{"risk":"high","decision":"deny","reason":"test high-risk decision"}',
                          'invalid':'invalid reviewer response'}[state['mode']]
                else:
                    step=state['step'];state['step']+=1
                    if step<len(tools):name,args=tools[step]
                    text='AUTO_REVIEW_TEST_DONE'
                events=[('message_start',{'type':'message_start','message':{'id':'fake','type':'message','role':'assistant','model':'deepseek-flash','content':[],'usage':{'input_tokens':1,'output_tokens':0}}})]
                if name:
                    block={'type':'tool_use','id':'call_'+str(state['step']),'name':name,'input':{}}
                    delta={'type':'input_json_delta','partial_json':json.dumps(args)}
                else:
                    block={'type':'text','text':''};delta={'type':'text_delta','text':text}
                events += [('content_block_start',{'type':'content_block_start','index':0,'content_block':block}),
                           ('content_block_delta',{'type':'content_block_delta','index':0,'delta':delta}),
                           ('content_block_stop',{'type':'content_block_stop','index':0}),
                           ('message_delta',{'type':'message_delta','delta':{'stop_reason':'tool_use' if name else 'end_turn'},'usage':{'output_tokens':20}}),
                           ('message_stop',{'type':'message_stop'})]
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for kind,event in events:self.wfile.write(('event: '+kind+'\ndata: '+json.dumps(event)+'\n\n').encode())
        server=HTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        payload=dict(workspace=str(root),home=str(root/'home'),model='deepseek-flash',api_key='fixture-key',
                     base_url=f'http://127.0.0.1:{server.server_port}/v1',session_id=uuid.uuid4().hex,
                     prompt='Create the requested temporary test marker only.')
        def run(enabled,mode,marker,resume=False):
            state.update(step=0,mode=mode)
            before=state['reviews']
            command="Set-Content -LiteralPath '"+str(marker)+"' -Value 'fixture'"
            tools[:]=[('pwsh',{'command':command,'description':'Temporary marker fixture',
                              'sandbox_permissions':'danger-full-access','justification':'Temporary test marker'})]
            process=subprocess.Popen([str(ROOT/'.harness-venv/Scripts/python.exe'),'-u','-m','deskpet.chat.harness_worker'],
                cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8')
            messages=queue.Queue();errors=[];approvals=[];events=[]
            def read():
                for line in process.stdout:messages.put(json.loads(line))
                messages.put(None)
            threading.Thread(target=read,daemon=True).start()
            threading.Thread(target=lambda:errors.append(process.stderr.read()),daemon=True).start()
            try:
                process.stdin.write(json.dumps(dict(payload,auto_approve=enabled,resume=resume))+'\n');process.stdin.flush()
                deadline=time.monotonic()+55
                while time.monotonic()<deadline:
                    event=messages.get(timeout=max(.1,deadline-time.monotonic()))
                    assert event is not None,errors
                    events.append(event)
                    if event['type']=='approval':
                        approvals.append(event['request'])
                        process.stdin.write(json.dumps({'type':'approval','id':event['request']['id'],'approved':False})+'\n');process.stdin.flush()
                    if event['type'] in ('completed','failed'):
                        assert event['type']=='completed',event
                        process.wait(timeout=10)
                        break
                else:raise AssertionError('worker timeout')
                return approvals,state['reviews']-before,events
            finally:
                if process.poll() is None:
                    subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10)
                    process.wait(timeout=5)
        try:
            marker=root/'allowed.txt'
            approvals,reviews,_=run(True,'allow',marker)
            assert reviews==1 and not approvals and marker.exists(),(reviews,approvals)
            print('PASS ordinary tool reviewed and executed without human approval',flush=True)
            marker=root/'denied.txt'
            approvals,reviews,_=run(True,'deny',marker,True)
            assert reviews==1 and len(approvals)==1 and not marker.exists(),(reviews,approvals)
            print('PASS high-risk review kept human approval; rejection prevented execution',flush=True)
            marker=root/'invalid.txt'
            approvals,reviews,events=run(True,'invalid',marker,True)
            assert reviews==1 and not approvals and not marker.exists(),(reviews,approvals)
            assert 'AUTO_REVIEW_FAILED' in json.dumps(events)
            print('PASS malformed reviewer response never executed the tool',flush=True)
            marker=root/'disabled.txt'
            approvals,reviews,_=run(False,'allow',marker,True)
            assert reviews==0 and len(approvals)==1 and not marker.exists(),(reviews,approvals)
            print('PASS disabling Auto restored manual policy on the same session',flush=True)
        finally:
            server.shutdown();server.server_close()


if __name__=='__main__':main()
