# Local beat analysis

The primary UI now has one persistent switch, disabled by default. With it enabled,
`MusicPreparation` automatically prepares timing before the first local/NetEase
playback and reuses cached timing on subsequent plays. Advanced manual calibration
is collapsed. The user can skip preparation; failure continues playback, while
source changes cancel the pending callback. Online streams are analyzed in a
temporary directory and removed afterwards; only timing results persist.

`enabled`, `set_enabled(bool)`, `has_timing()`, `analyzing`, and
`analysisFinished(bool)` support the host. `restore_online(source_key, identity)`
loads a stable cache; `analyze_online(path, identity)` analyzes temporary audio
without replacing the `netease:<id>` identity. `sample` returns unavailable while
disabled. Cancellation emits one false completion; the host invalidates callbacks
before cancelling. Changed file/audio-version identities invalidate the cache.

`BeatController(data_dir, parent=None)` owns an optional Qt settings widget and provides
`BeatSample(beat_index, phase, available, bpm)` from `sample(position_ms, playing)`.
Phase zero is the beat and phase .5 the middle of the beat. Paused samples remain
available and use the supplied position unchanged; seek/loop naturally sample the
new position. There is no wall-clock animation accumulator. Before the first beat
or without data `available` is false. The caller keeps its existing fixed animation
when false and handles drag/sleep/song state separately.

Sources are `local:<absolute path>`, `netease:<song_id>` or `bilibili:<BV>:<part>` (manual only).
`set_source` reads small cache/settings and optional Mutagen BPM metadata only on
source changes. Once enabled, the host calls `analyze()` before uncached playback: Qt's bundled audio backend decodes in a
separate process, then NumPy estimates onset periodicity and snaps individual beats
to nearby onsets. It is an estimate, especially uncertain with rubato, silence,
syncopation or changing tempo. A fixed BPM tag does not establish first-beat phase.
The analysis button can still be used when a tag is present. No system FFmpeg or
librosa is needed by the application. Qt backend/codec failures are displayed and
leave manual BPM or the original fixed rhythm available.

`set_manual(bpm=0, offset_ms=0, speed=1)` saves independent correction data; zero
selects automatic/tag BPM, positive offset delays the first beat, speed accepts
.5/1/2. A manual BPM replaces the estimated grid; clearing it restores analysis.
Half/double also applies to analyzed beats without altering their stored timestamps.
Manual settings are keyed by source, and analysis by resolved path, file size,
mtime in nanoseconds and algorithm version. JSON writes are atomic. Corrupt caches
are ignored; inputs and cache size are bounded. No audio file is modified.

Runtime dependencies: existing PySide6 QtMultimedia, numpy==2.5.4,
mutagen==1.47.0 (missing Mutagen disables tag reading only). All audio/numpy imports
are lazy. Frozen worker dispatch is `TianyiWorker.exe --beat-worker <path>` and must
call `music_beats.worker.run()`. Source mode uses `python -m music_beats.worker`.
The helper emits JSON lines with type `progress`, `result`, or `error`; cancellation
kills the isolated helper. `shutdown()` cancels pending analysis.

Verification: `python -m unittest tests.test_beats -v`; optional real-MP3 smoke:
`python -m tests.smoke_beats`. The latter uses the separately installed test-only
`imageio_ffmpeg` encoder to generate an eight-second synthetic pulse MP3, then
verifies decoding through Qt, ID3 BPM, cache/settings, cancellation and widget.
Fixtures are temporary, generated locally, and contain no downloaded music.

2026-10-22 MP3 compatibility fix: keep the decoder's native sample rate/channel
format instead of forcing 22.05 kHz mono. With Qt 6.8.3, some 48 kHz MP3 encoder
delay frames produced an invalid empty buffer and stalled the forced resampler.
The worker now averages channel energy (avoiding opposite-phase cancellation),
uses the actual hop duration, and emits only one terminal result/error. Regression
coverage includes a generated 48 kHz stereo 320 kbps MP3 and opposite-phase WAV.
Five existing local songs that previously failed were read-only checked after the
fix: all completed in approximately 3–5 seconds. No audio or user cache was changed;
successful analysis is not a guarantee of musically exact tempo/beat tracking.
