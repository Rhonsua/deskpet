"""Entry point shared by GUI and console helper executables."""
import os
import sys

if '--beat-worker' in sys.argv:
    from deskpet.music.beats.worker import run
    run()
elif '--audio-worker' in sys.argv:
    from deskpet.music.players.audio_player_worker import run
    run()
elif '--netease-worker' in sys.argv:
    from deskpet.music.players.netease_player_worker import run
    run()
elif '--web-worker' in sys.argv:
    from deskpet.music.players.web_player_worker import run
    run()
elif '--chat-worker' in sys.argv:
    from deskpet.chat.player_worker import run
    run()
elif '--harness-worker' in sys.argv:
    from deskpet.chat.harness_worker import run
    run()
elif '--self-check' in sys.argv:
    from deskpet.runtime.check import run
    run()
else:
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w'))
    from deskpet.app import main
    sys.exit(main())
