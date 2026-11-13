"""Opt-in one-request provider check using an isolated real chat composer.

Run with --live to use the user's saved provider. No real chat history, settings,
or credentials are printed or changed. The normal test suite never runs this.
"""
import argparse
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer
from deskpet.chat.config import ConfigFile
from deskpet.chat.remote import ChatClient
from tests.test_music_ai_choice import ChoiceTests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Make one paid request to the saved provider')
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('Explicit --live is required; ordinary tests never contact a provider.')
    config, warning = ConfigFile(args.config).load()
    if warning or not config.api_key:
        raise SystemExit(warning or 'No remembered API key is available.')
    config.validate()
    ChoiceTests.setUpClass()
    fixture = ChoiceTests()
    fixture.setUp()
    client = ChatClient()
    result, errors = [], []
    loop = QEventLoop()
    client.completed.connect(lambda text: (result.append(text), loop.quit()))
    client.failed.connect(lambda error: (errors.append(error), loop.quit()))
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: (errors.append('Provider test timed out.'), loop.quit()))
    try:
        with fixture.window() as (window, remote), patch.object(window.balance_badge, 'refresh'):
            window.config = config
            window.send_sticker('aling_work')
            request_config, messages = remote.return_value.start.call_args.args[:2]
            print('Current user message:', messages[-1]['content'], flush=True)
            client.start(request_config, messages)
            timeout.start(105000)
            loop.exec()
            timeout.stop()
            if errors:
                raise SystemExit(errors[0])
            reply = result[0]
            print('Provider reply:', reply, flush=True)
            window.on_completed(reply)
            stored = window.store.history(window.character)
            assert len(stored) == 2 and stored[0]['stickers'] == ['aling_work']
            assert not re.search(r'空(?:空的)?(?:消息|信号)|没(?:有)?(?:收到|看到|看见)(?:图片|图呢|图|表情)', reply)
            assert any(name in reply for name in ('阿绫', '乐正绫')), 'Response did not identify the supplied character.'
            print('PASS: current attachment understood; reply delivered; no personal history used.', flush=True)
    finally:
        timeout.stop()
        client.shutdown()
        fixture.tearDown()


if __name__ == '__main__':
    main()
