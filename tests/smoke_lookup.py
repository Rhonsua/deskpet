"""Opt-in public-network and provider smoke test; never run by unittest discovery."""
import argparse
import os
from pathlib import Path
import sys
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from deskpet.chat.lookup_service import LookupJob


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-network', action='store_true', required=True)
    parser.add_argument('--kind', choices=('lyrics', 'web'), default='lyrics')
    parser.add_argument('--query', default='普通DISCO 洛天依')
    parser.add_argument('--config', type=Path, help='Optional: use remembered provider for an end-to-end chat test')
    args = parser.parse_args()
    if not args.config:
        app = QCoreApplication([])
        job = LookupJob(1, dict(kind=args.kind, query=args.query))
        found = []
        job.signals.done.connect(lambda ticket, rows, error: found.append((rows, error)))
        job.run()
        rows, error = found[0]
        for row in rows:
            print(row['kind'], row['title'], row['url'], 'characters=' + str(len(row['text'])), flush=True)
        if not rows:
            raise SystemExit(error)
        print('PASS: real public results returned.', flush=True)
        return
    from deskpet.chat.config import ConfigFile
    from deskpet.chat.remote import ChatClient
    from tests.test_music_ai_choice import ChoiceTests
    config, warning = ConfigFile(args.config).load()
    if warning or not config.api_key:
        raise SystemExit(warning or 'No remembered API key.')
    ChoiceTests.setUpClass()
    fixture = ChoiceTests()
    fixture.setUp()
    client = ChatClient()
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    try:
        with fixture.window() as (w, remote), patch.object(w.balance_badge, 'refresh'):
            w.config = config
            client.completed.connect(w.on_completed)
            client.failed.connect(w.on_failed)
            remote.return_value.start.side_effect = client.start
            w.lookup_service.ready.connect(lambda rows, error: print('Lookup:', len(rows), 'sources;', error or 'OK', flush=True))
            w.busyChanged.connect(lambda busy: loop.quit() if not busy else None)
            w.input.setPlainText('请联网查一下《普通DISCO》的歌词，用自己的话聊聊它的意思，不要复述歌词。')
            w.send_message()
            timer.start(150000)
            loop.exec()
            timer.stop()
            history = w.store.history(w.character)
            if not history:
                raise SystemExit(w.status.text())
            row = history[-1]
            print('Reply:', row['content'], flush=True)
            print('Sources:', row.get('sources', []), flush=True)
            assert row.get('sources'), 'No actual lookup was used.'
            assert remote.return_value.start.call_count == 2
            print('PASS: model requested lookup, received evidence, answered with sources.', flush=True)
    finally:
        timer.stop()
        client.shutdown()
        fixture.tearDown()


if __name__ == '__main__':
    main()
