"""No-model startup regression: .harness-venv/Scripts/python tests/harness_startup_smoke.py [workspace]."""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deepseek_harness import HarnessClient, HarnessConfig
from deepseek_harness.models import InitializeResponse
from deskpet.chat.harness_runtime import runtime_cli, runtime_launch_args


def main():
    workspace = Path(sys.argv[1]).resolve(strict=True) if len(sys.argv) > 1 else ROOT
    cli = runtime_cli()
    for attempt in range(5):
        with tempfile.TemporaryDirectory(prefix='deskpet-startup-') as folder:
            home = Path(folder)
            patch = home / 'privacy.patch.yml'
            patch.write_text('- id: session-telemetry-otel\n  disabled: true\n', encoding='utf8')
            config = HarnessConfig(cwd=str(workspace), dsh_home=str(home),
                env={'DSH_HOME':str(home), 'DEEPSEEK_API_KEY':'local-fake-no-model-call',
                     'DSH_TELEMETRY_DISABLED':'1'})
            client = HarnessClient(config, _launch_args=runtime_launch_args(cli, patch))
            start = time.monotonic()
            try:
                client.start()
                # No sleeps or retries: the very first request must survive boot.
                client.request('initialize', {'cwd':str(workspace), 'provider':'deepseek-official',
                    'model':'deepseek-flash', 'approvalRequests':True},
                    response_model=InitializeResponse, timeout_seconds=30)
                print(f'PASS fresh home {attempt+1}: {time.monotonic()-start:.2f}s', flush=True)
            finally:
                client.close()


if __name__ == '__main__':
    main()
