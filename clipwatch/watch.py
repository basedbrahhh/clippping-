"""The Clip Watcher: record a Twitch stream, log its chat, and clip every
moment chat spikes. Leave it running overnight.

    python -m clipwatch.watch CHANNEL [--model models/ggml-medium.en.bin]

Output goes to runs/CHANNEL/<date>/:
    stream-<epoch>.ts       raw recording (a new file each time they go live)
    stream-<epoch>.start    wall-clock epoch of the recording's first byte
    chat.log                <epoch>\t<user>\t<message>
    clips/clip-*.mp4        45 s cuts (+ .captioned.mp4, .srt, .txt credit)
    clips/index.jsonl       one JSON line per clip
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

from . import chat, clip, spikes


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, file=sys.stderr, flush=True)


class Watcher:
    def __init__(self, channel, outdir, model=None, pre=30, dur=45, factor=3.0,
                 min_count=8, quality="best", streamlink="streamlink"):
        self.channel = channel.lower().lstrip("#")
        self.url = f"https://twitch.tv/{self.channel}"
        self.dir = outdir
        self.clips = os.path.join(outdir, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.model, self.pre, self.dur = model, pre, dur
        self.factor, self.min_count = factor, min_count
        self.quality, self.streamlink = quality, streamlink
        self.times = []           # chat message epochs
        self.segments = []        # {path, start, end}
        self.done = set()         # spike epochs already clipped
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.caption_q = queue.Queue()

    # --- chat ---------------------------------------------------------------
    def run_chat(self):
        path = os.path.join(self.dir, "chat.log")
        with open(path, "a", encoding="utf-8", buffering=1) as f:
            def on_msg(t, user, text):
                f.write(f"{t:.3f}\t{user}\t{text.replace(chr(9), ' ')}\n")
                with self.lock:
                    self.times.append(t)
            chat.stream_chat(self.channel, on_msg, stop=self.stopping.is_set,
                             log=log)

    # --- recording ----------------------------------------------------------
    def run_recorder(self):
        while not self.stopping.is_set():
            stamp = int(time.time())
            path = os.path.join(self.dir, f"stream-{stamp}.ts")
            log(f"[rec] waiting for {self.url} to go live -> {os.path.basename(path)}")
            proc = subprocess.Popen(
                [self.streamlink, self.url, self.quality, "-o", path,
                 "--retry-streams", "30", "--twitch-disable-ads"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            seg = None
            while proc.poll() is None and not self.stopping.is_set():
                if seg is None and os.path.exists(path) and os.path.getsize(path) > 0:
                    seg = {"path": path, "start": time.time(), "end": None}
                    with open(path[:-3] + ".start", "w") as f:
                        f.write(f"{seg['start']:.3f}\n")
                    with self.lock:
                        self.segments.append(seg)
                    log("[rec] LIVE - recording started")
                time.sleep(0.5)
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
            if seg:
                seg["end"] = time.time()
                log("[rec] stream ended")
            elif not self.stopping.is_set():
                time.sleep(30)

    # --- spikes -> clips ----------------------------------------------------
    def segment_for(self, t):
        for seg in reversed(self.segments):
            if seg["start"] <= t and (seg["end"] is None or t <= seg["end"]):
                return seg
        return None

    def check_spikes(self, now=None):
        now = now or time.time()
        with self.lock:
            times = list(self.times)
        made = []
        for s in spikes.find_spikes(times, factor=self.factor, min_count=self.min_count,
                                    cooldown_s=self.dur, until=now):
            t = s["t"]
            if t in self.done:
                continue
            seg = self.segment_for(t)
            if seg is None:              # spike while offline: nothing to cut
                self.done.add(t)
                continue
            clip_end = t - self.pre + self.dur
            ready_at = clip_end + 20     # allow for HLS buffering / file flush
            if seg["end"] is None and now < ready_at:
                continue                 # footage not on disk yet
            self.done.add(t)
            made.append(self.make_clip(seg, s))
        return made

    def make_clip(self, seg, s):
        offset = s["t"] - seg["start"]
        name = "clip-" + time.strftime("%Y%m%d-%H%M%S", time.localtime(s["t"]))
        out = os.path.join(self.clips, name + ".mp4")
        try:
            clip.cut(seg["path"], offset, out, self.pre, self.dur)
        except subprocess.CalledProcessError as e:
            log(f"[clip] ffmpeg failed: {e.stderr.decode(errors='replace')[-300:]}")
            return None
        credit = f"Streamer: {self.channel}\nWatch live: {self.url}\n"
        with open(out[:-4] + ".txt", "w") as f:
            f.write(credit)
        entry = {"clip": os.path.basename(out), "spike_epoch": s["t"],
                 "stream_file": os.path.basename(seg["path"]),
                 "stream_offset": round(offset, 1), "msgs": s["count"],
                 "baseline": s["baseline"], "credit": self.url}
        with open(os.path.join(self.clips, "index.jsonl"), "a") as f:
            f.write(json.dumps(entry) + "\n")
        log(f"[clip] {name}.mp4  ({s['count']} msgs/10s vs {s['baseline']} avg, "
            f"stream +{spikes.hms(offset)})")
        if self.model:
            self.caption_q.put(out)
        return out

    def run_captions(self):
        while True:
            out = self.caption_q.get()
            if out is None:
                return
            try:
                srt = clip.transcribe(out, self.model)
                final = out[:-4] + ".captioned.mp4"
                clip.burn(out, srt, final, credit=f"twitch.tv/{self.channel}", dur=self.dur)
                log(f"[caps] {os.path.basename(final)}")
            except Exception as e:  # keep the night going
                log(f"[caps] failed for {os.path.basename(out)}: {e}")

    # --- main loop ----------------------------------------------------------
    def run(self):
        threads = [threading.Thread(target=self.run_chat, daemon=True),
                   threading.Thread(target=self.run_recorder, daemon=True)]
        cap = threading.Thread(target=self.run_captions, daemon=True)
        for t in threads + [cap]:
            t.start()
        try:
            while True:
                time.sleep(10)
                self.check_spikes()
        except KeyboardInterrupt:
            log("stopping... cutting any pending clips")
            self.stopping.set()
            for seg in self.segments:
                seg["end"] = seg["end"] or time.time()
            self.check_spikes(now=time.time() + 3600)
            self.caption_q.put(None)
            cap.join()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channel")
    ap.add_argument("--out", help="output dir (default runs/CHANNEL/YYYY-MM-DD)")
    ap.add_argument("--model", help="whisper.cpp model for captions (optional)")
    ap.add_argument("--pre", type=float, default=30, help="seconds before the spike")
    ap.add_argument("--dur", type=float, default=45, help="clip length")
    ap.add_argument("--factor", type=float, default=3.0, help="spike = N x 5-min avg")
    ap.add_argument("--min-count", type=int, default=8, help="min msgs in a 10 s bin")
    ap.add_argument("--quality", default="best")
    a = ap.parse_args(argv)
    if not shutil.which("streamlink"):
        sys.exit("streamlink not found: pip install streamlink")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")
    if a.model and not (clip.find_whisper() and os.path.exists(a.model)):
        sys.exit("captions need whisper-cli on PATH and the --model file")
    out = a.out or os.path.join("runs", a.channel.lower(), time.strftime("%Y-%m-%d"))
    os.makedirs(out, exist_ok=True)
    log(f"watching twitch.tv/{a.channel} -> {out}  (Ctrl-C to stop)")
    Watcher(a.channel, out, a.model, a.pre, a.dur, a.factor, a.min_count,
            a.quality).run()


if __name__ == "__main__":
    main()
