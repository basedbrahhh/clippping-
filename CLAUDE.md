# Clip Watcher — notes for Claude Code

Stdlib-only Python package `clipwatch/` plus ffmpeg, streamlink, whisper.cpp.

- `chat.py`   anonymous Twitch IRC reader (irc.chat.twitch.tv:6667, nick justinfanNNNNN) → `chat.log` lines `epoch\tuser\tmsg`
- `spikes.py` `find_spikes(times)`: 10 s bins, spike = ≥3× previous-5-min average and ≥8 msgs
- `clip.py`   `cut()` (ffmpeg -ss spike-30 -t 45 -c copy), `transcribe()` (whisper-cli → .srt), `burn()` (captions + credit)
- `watch.py`  orchestrator: streamlink recorder loop + chat thread + spike→clip loop + caption worker

Run data lives in `runs/CHANNEL/DATE/`. A recording's video offset for a chat
message is `chat_epoch - float(open("stream-<x>.start").read())`.

When asked to find/cut clips from an existing run: use `python3 -m clipwatch.spikes`
with `--start`, then `python3 -m clipwatch.clip`. Always keep the streamer credit
(`--credit twitch.tv/CHANNEL`) on captioned clips.

Tests: `python3 -m unittest -v tests.test_clipwatch` (needs ffmpeg; ~1 min).
