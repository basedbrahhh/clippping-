import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from clipwatch import chat, clip, spikes, watch


def make_video(path, seconds=120):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:v", "libx264", "-g", "30", "-c:a", "aac", "-f", "mpegts", path],
                   check=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    return float(out.stdout)


def synthetic_chat(t0=1_000_000.0, minutes=10, spike_at=420):
    """2 msgs / 10 s background, plus a 40-message burst at spike_at."""
    times = [t0 + i * 5 for i in range(minutes * 12)]
    times += [t0 + spike_at + i * 0.2 for i in range(40)]
    return sorted(times)


class SpikeTests(unittest.TestCase):
    def test_finds_single_spike(self):
        t0 = 1_000_000.0
        s = spikes.find_spikes(synthetic_chat(t0))
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0]["t"], t0 + 420, delta=10)
        self.assertEqual(s[0]["baseline"], 2.0)

    def test_flat_chat_has_no_spikes(self):
        self.assertEqual(spikes.find_spikes(synthetic_chat(spike_at=10**9)), [])

    def test_quiet_chat_needs_min_count(self):
        # 0 -> 5 messages is a big ratio but too small to matter
        times = [0.0, 300.0] + [400 + i for i in range(5)]
        self.assertEqual(spikes.find_spikes(times), [])

    def test_causal_until(self):
        times = synthetic_chat()
        self.assertEqual(spikes.find_spikes(times, until=1_000_000 + 400), [])

    def test_read_log(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("12.5\tbob\thi\ngarbage\n13.0\tamy\tPOG\n")
        self.assertEqual(spikes.read_log(f.name), [12.5, 13.0])


class ChatTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(chat.parse_privmsg(":bob!bob@bob.tmi.twitch.tv PRIVMSG #x :KEKW lol :)"),
                         ("bob", "KEKW lol :)"))
        self.assertIsNone(chat.parse_privmsg(":tmi.twitch.tv 001 justinfan1 :Welcome"))

    def test_against_fake_irc_server(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        got_pong, received = [], []

        def serve():
            c, _ = srv.accept()
            hello = c.recv(1024).decode()
            assert "NICK justinfan" in hello and "JOIN #somechan" in hello, hello
            c.sendall(b"PING :tmi.twitch.tv\r\n")
            got_pong.append(c.recv(1024))
            c.sendall(b":a!a@a PRIVMSG #somechan :hello\r\n:b!b@b PRIVMSG #somechan :wow\r\n")
            time.sleep(0.5)
            c.close()

        threading.Thread(target=serve, daemon=True).start()
        stop = threading.Event()

        def on_msg(t, u, m):
            received.append((u, m))
            if len(received) == 2:
                stop.set()

        chat.stream_chat("SomeChan", on_msg, host="127.0.0.1", port=port,
                         stop=stop.is_set, log=lambda m: None)
        self.assertEqual(received, [("a", "hello"), ("b", "wow")])
        self.assertEqual(got_pong[0], b"PONG :tmi.twitch.tv\r\n")


class ClipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.ts = os.path.join(cls.tmp, "stream.ts")
        make_video(cls.ts)

    def test_cut_length(self):
        out = clip.cut(self.ts, 60, os.path.join(self.tmp, "c.mp4"))
        self.assertAlmostEqual(duration(out), 45, delta=1.5)

    def test_cut_near_start_clamps(self):
        out = clip.cut(self.ts, 5, os.path.join(self.tmp, "early.mp4"))
        self.assertAlmostEqual(duration(out), 45, delta=1.5)

    def test_burn_captions_and_credit(self):
        c = clip.cut(self.ts, 60, os.path.join(self.tmp, "b.mp4"))
        srt = os.path.join(self.tmp, "b.srt")
        with open(srt, "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nNo way he hit that\n")
        out = clip.burn(c, srt, os.path.join(self.tmp, "b.captioned.mp4"),
                        credit="twitch.tv/somechan")
        self.assertAlmostEqual(duration(out), 45, delta=1.5)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".credit.srt")))


class WatcherTests(unittest.TestCase):
    def test_spike_becomes_clip_once_footage_exists(self):
        tmp = tempfile.mkdtemp()
        ts = os.path.join(tmp, "stream-1.ts")
        make_video(ts, seconds=600)
        t0 = 1_000_000.0
        w = watch.Watcher("SomeChan", tmp)
        w.times = synthetic_chat(t0, minutes=10, spike_at=420)
        w.segments = [{"path": ts, "start": t0, "end": None}]

        self.assertEqual(w.check_spikes(now=t0 + 440), [])        # too soon
        made = w.check_spikes(now=t0 + 470)
        self.assertEqual(len(made), 1)
        self.assertEqual(w.check_spikes(now=t0 + 500), [])        # no duplicate
        self.assertAlmostEqual(duration(made[0]), 45, delta=1.5)
        with open(os.path.join(tmp, "clips", "index.jsonl")) as f:
            entry = json.loads(f.read())
        self.assertEqual(entry["credit"], "https://twitch.tv/somechan")
        self.assertAlmostEqual(entry["stream_offset"], 420, delta=10)
        with open(made[0][:-4] + ".txt") as f:
            self.assertIn("twitch.tv/somechan", f.read())


if __name__ == "__main__":
    unittest.main()
