# The Clip Watcher

One folder that records a Twitch stream, reads its chat, and clips every moment
chat goes off — while you sleep.

```
streamlink ──► stream-<t>.ts ─┐
                              ├─► spike? ──► ffmpeg cut ──► whisper captions ──► clips/
IRC (anon)  ──► chat.log ─────┘
```

## Setup

Needs Python 3.9+, ffmpeg, and streamlink. Whisper.cpp is only needed for captions.

```bash
./setup.sh
```

```bash
./setup.sh captions
```

## Run it overnight

```bash
python3 -m clipwatch.watch CHANNEL
```

With captions:

```bash
python3 -m clipwatch.watch CHANNEL --model models/ggml-medium.en.bin
```

It waits for the channel to go live, records from the first second, logs chat,
and cuts a clip ~20 s after each spike is over. If the streamer goes offline
and comes back, it starts a new recording file and keeps going. Ctrl-C cuts any
clips still pending and exits.

Everything lands in `runs/CHANNEL/YYYY-MM-DD/`:

| file | what |
|---|---|
| `stream-<epoch>.ts` | raw recording, one per live session |
| `stream-<epoch>.start` | wall-clock time of its first byte (used to line chat up with video) |
| `chat.log` | `epoch<TAB>user<TAB>message` |
| `clips/clip-*.mp4` | 45 s stream-copy cut |
| `clips/clip-*.captioned.mp4` | captions burned in at the bottom, `twitch.tv/CHANNEL` at the top |
| `clips/clip-*.txt` | credit + link to paste into your post |
| `clips/index.jsonl` | one line per clip: spike time, message count, baseline, stream offset |

## How a spike is defined

Chat is counted in 10-second bins. A bin is a spike when it has
**≥ 3× the average of the previous 5 minutes** and at least 8 messages (so a
quiet chat going 0 → 3 doesn't count). Back-to-back hot bins are one spike.
The clip starts **30 s before** the spike and runs **45 s**, because chat reacts
after the moment.

Tune with `--factor`, `--min-count`, `--pre`, `--dur`.

## Running the steps by hand

```bash
python3 -m clipwatch.chat CHANNEL -o chat.log
```

```bash
python3 -m clipwatch.spikes chat.log --start stream-1731800000.start
```

```bash
python3 -m clipwatch.clip stream-1731800000.ts 3725 -o clip.mp4 --model models/ggml-medium.en.bin --credit twitch.tv/CHANNEL
```

Or open this folder in Claude Code and ask, e.g. *"Find the spikes in
runs/CHANNEL/2026-11-17 and cut the top 5."* — `CLAUDE.md` tells it how.

## Limits

- Live only: it records what it sees live, not VODs.
- Chat/video alignment is approximate (HLS delay is a few seconds); the 30 s
  lead-in covers it.
- Chat is read-only and anonymous (`justinfan…`), no Twitch account or token.
- Stream-copy cuts start on the nearest keyframe, so a clip can begin up to ~2 s early.

## The one rule

Clip, **credit and link the streamer**. Every clip ships with a `.txt` credit
and a burned-in `twitch.tv/CHANNEL`. Don't strip them, and respect the
streamer's wishes and Twitch's terms if they ask you not to clip.

## Tests

```bash
python3 -m unittest -v tests.test_clipwatch
```
