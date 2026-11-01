import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from deepseek_harness import HarnessClient, HarnessConfig
from pydantic import BaseModel
class Empty(BaseModel):
    pass
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from deskpet.chat.harness_runtime import runtime_launch_args
for outcome in ('rejected','allowed-once'):
    home=root/'local-work'/'approval-probe-alpha2'/(__import__('uuid').uuid4().hex+outcome)
    home.mkdir(parents=True,exist_ok=True)
    marker=home/'approved.txt'
    if marker.exists(): marker.unlink()
    patch=home/'probe.yml'
    patch.write_text('- insert:\n    - id: approval-fixture\n      name: '+json.dumps(str(root/'packaging/harness_approval_fixture.mjs'))+'\n      config:\n        stopAfterApproval: true\n        path: '+json.dumps(str(marker))+'\n- id: session-log-deepseek\n  config:\n    enabled: false\n- id: session-telemetry-otel\n  disabled: true\n',encoding='utf-8')
    config=HarnessConfig(dsh_bin=str(root/'local-work/harness-npm/node_modules/.bin/dsh.cmd'),
        dsh_home=str(home),cwd=str(root),patches=(str(patch),),request_timeout_seconds=30,
        env={'DSH_HOME':str(home),'DSH_PERMISSION_MODE':'workspace-write','DSH_TELEMETRY_DISABLED':'1','DEEPSEEK_API_KEY':'keyless-no-model-call'})
    with ThreadPoolExecutor(max_workers=1) as pool:
        with HarnessClient(config, _launch_args=runtime_launch_args(config.dsh_bin, patch)) as client:
            client.request('initialize',{'cwd':str(home),'provider':'deepseek-official','model':'deepseek-v4-flash','approvalRequests':True},response_model=Empty)
            client.session_prompt('main',[{'type':'text','text':'Request marker write.'}])
            request=pool.submit(client.next_request).result(timeout=30)
            assert request.method=='approval/request',request
            print('APPROVAL_RECEIVED',outcome,flush=True)
            client.respond(request.id,{'outcome':outcome})
            client.request('session/wait',{'sessionId':'main'},response_model=Empty)
            assert marker.exists()==(outcome=='allowed-once')
            print('GUARDED_OPERATION_VERIFIED',outcome,flush=True)
