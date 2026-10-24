"""Entry point shared by GUI and console helper executables."""
import os
import sys

if '--beat-worker' in sys.argv:
    from music_beats.worker import run
    run()
elif '--audio-worker' in sys.argv:
    from audio_player_worker import run
    run()
elif '--netease-worker' in sys.argv:
    from netease_player_worker import run
    run()
elif '--web-worker' in sys.argv:
    from web_player_worker import run
    run()
elif '--chat-worker' in sys.argv:
    from chat_player_worker import run
    run()
elif '--self-check' in sys.argv:
    from packaged_check import run
    run()
else:
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w'))
    from main import main
    sys.exit(main())
