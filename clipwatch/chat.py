"""Read-only anonymous Twitch chat logger.

Connects to irc.chat.twitch.tv:6667 as justinfan<random>, no token needed,
and appends one line per message to a log file:

    <unix_epoch_seconds>\t<user>\t<message>
"""
import argparse
import random
import socket
import sys
import time

HOST, PORT = "irc.chat.twitch.tv", 6667


def parse_privmsg(line):
    """Return (user, text) for a PRIVMSG line, else None."""
    # :nick!nick@nick.tmi.twitch.tv PRIVMSG #chan :message text
    if " PRIVMSG " not in line or not line.startswith(":"):
        return None
    prefix, _, rest = line[1:].partition(" PRIVMSG ")
    _, _, text = rest.partition(" :")
    return prefix.split("!", 1)[0], text


def stream_chat(channel, on_message, host=HOST, port=PORT, stop=None, log=print):
    """Connect, call on_message(epoch, user, text) for every message.

    Reconnects forever (with backoff) until stop() returns True.
    """
    channel = channel.lower().lstrip("#")
    backoff = 1
    while not (stop and stop()):
        try:
            with socket.create_connection((host, port), timeout=10) as s:
                s.settimeout(1.0)
                nick = f"justinfan{random.randint(10000, 99999)}"
                s.sendall(f"NICK {nick}\r\nJOIN #{channel}\r\n".encode())
                log(f"[chat] connected as {nick}, joined #{channel}")
                backoff = 1
                buf = b""
                last_rx = time.time()
                while not (stop and stop()):
                    try:
                        data = s.recv(4096)
                    except socket.timeout:
                        if time.time() - last_rx > 360:  # Twitch PINGs ~every 5 min
                            raise ConnectionError("chat silent for 6 min")
                        continue
                    if not data:
                        raise ConnectionError("server closed connection")
                    last_rx = time.time()
                    buf += data
                    *lines, buf = buf.split(b"\r\n")
                    for raw in lines:
                        line = raw.decode("utf-8", "replace")
                        if line.startswith("PING"):
                            s.sendall(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                            continue
                        msg = parse_privmsg(line)
                        if msg:
                            on_message(time.time(), *msg)
        except (OSError, ConnectionError) as e:
            if stop and stop():
                break
            log(f"[chat] disconnected ({e}); retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("channel")
    ap.add_argument("-o", "--out", default="chat.log")
    a = ap.parse_args(argv)
    with open(a.out, "a", encoding="utf-8", buffering=1) as f:
        def write(t, user, text):
            f.write(f"{t:.3f}\t{user}\t{text.replace(chr(9), ' ')}\n")
        try:
            stream_chat(a.channel, write, log=lambda m: print(m, file=sys.stderr))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
