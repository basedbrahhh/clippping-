"""Find chat spikes: 10-second bins whose message count is >= FACTOR x the
average of the previous 5 minutes.

    python -m clipwatch.spikes chat.log [--start stream.start]
"""
import argparse
import time


def read_log(path):
    times = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            head = line.split("\t", 1)[0]
            try:
                times.append(float(head))
            except ValueError:
                pass
    return times


def find_spikes(times, bin_s=10, window_s=300, factor=3.0, min_count=8,
                min_history_s=60, cooldown_s=45, until=None):
    """Return a list of dicts {t, count, baseline} for each spike.

    Causal: a bin's baseline uses only the window before it, so the same
    function works on a log that is still being written. Bins at or after
    `until` (default: the bin still filling) are ignored. Consecutive hot
    bins collapse into one spike placed at the first hot bin, and spikes
    closer than `cooldown_s` are merged.
    """
    if not times:
        return []
    t0 = min(times)
    nbins = int((max(times) - t0) // bin_s) + 1
    counts = [0] * nbins
    for t in times:
        counts[int((t - t0) // bin_s)] += 1
    last = nbins - 1 if until is None else int((until - t0) // bin_s)
    w = max(1, window_s // bin_s)
    hist_bins = max(1, min_history_s // bin_s)
    spikes, prev_hot = [], False
    for i in range(min(nbins, last)):  # skip the bin that may still be filling
        prev = counts[max(0, i - w):i]
        hot = False
        if len(prev) >= hist_bins and counts[i] >= min_count:
            base = sum(prev) / len(prev)
            hot = counts[i] >= factor * max(base, 0.1)
        if hot and not prev_hot:
            t = t0 + i * bin_s
            if spikes and t - spikes[-1]["t"] < cooldown_s:
                spikes[-1]["count"] = max(spikes[-1]["count"], counts[i])
            else:
                spikes.append({"t": t, "count": counts[i], "baseline": round(base, 2)})
        elif hot:
            spikes[-1]["count"] = max(spikes[-1]["count"], counts[i])
        prev_hot = hot
    return spikes


def hms(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--start", help="file with the stream's start epoch (written by watch)")
    ap.add_argument("--factor", type=float, default=3.0)
    ap.add_argument("--min-count", type=int, default=8)
    a = ap.parse_args(argv)
    start = float(open(a.start).read().strip()) if a.start else None
    for s in find_spikes(read_log(a.log), factor=a.factor, min_count=a.min_count):
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["t"]))
        off = f"  stream {hms(s['t'] - start)} ({s['t'] - start:.0f}s)" if start else ""
        print(f"{when}{off}  {s['count']} msgs vs avg {s['baseline']}")


if __name__ == "__main__":
    main()
