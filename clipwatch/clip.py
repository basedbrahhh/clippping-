"""Cut a clip and (optionally) caption it with whisper.cpp + burn-in.

    python -m clipwatch.clip stream.ts 3725 -o clip.mp4 [--model ggml-medium.en.bin --credit twitch.tv/NAME]
"""
import argparse
import os
import shutil
import subprocess


def run(cmd, **kw):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, **kw)


def cut(src, spike_offset, out, pre=30, dur=45):
    """Stream-copy `dur` seconds starting `pre` seconds before the spike."""
    start = max(0.0, spike_offset - pre)
    run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{start:.2f}", "-t", str(dur),
         "-i", src, "-c", "copy", "-avoid_negative_ts", "make_zero",
         "-movflags", "+faststart", out])
    return out


def find_whisper():
    for name in ("whisper-cli", "whisper-cpp", "main"):
        p = shutil.which(name)
        if p:
            return p
    return None


def transcribe(clip, model, whisper=None):
    """Write <clip-base>.srt next to the clip using whisper.cpp; return its path."""
    whisper = whisper or find_whisper()
    if not whisper:
        raise FileNotFoundError("whisper-cli not found on PATH")
    base = os.path.splitext(clip)[0]
    wav = base + ".wav"  # whisper.cpp wants 16 kHz mono wav
    run(["ffmpeg", "-y", "-hide_banner", "-i", clip, "-ar", "16000", "-ac", "1", wav])
    try:
        run([whisper, "-m", model, "-f", wav, "-osrt", "-of", base])
    finally:
        os.remove(wav)
    return base + ".srt"


def write_credit_srt(path, text, dur):
    end = f"00:{int(dur) // 60:02d}:{int(dur) % 60:02d},000"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"1\n00:00:00,000 --> {end}\n{text}\n")


def burn(clip, srt, out, credit=None, dur=45):
    """Burn captions (bottom) and a credit line (top) into the clip."""
    d = os.path.dirname(os.path.abspath(clip))
    rel = lambda p: os.path.relpath(os.path.abspath(p), d)  # avoid filter escaping
    vf = [f"subtitles={rel(srt)}:force_style='FontSize=20,Outline=2,MarginV=30'"]
    if credit:
        cpath = os.path.join(d, ".credit.srt")
        write_credit_srt(cpath, credit, dur)
        vf.append("subtitles=.credit.srt:force_style='Alignment=6,FontSize=14,MarginV=10,Outline=1'")
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-i", rel(clip), "-vf", ",".join(vf),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
             "-movflags", "+faststart", rel(out)], cwd=d)
    finally:
        if credit:
            os.remove(cpath)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("spike", type=float, help="spike time in seconds into the recording")
    ap.add_argument("-o", "--out", default="clip.mp4")
    ap.add_argument("--pre", type=float, default=30)
    ap.add_argument("--dur", type=float, default=45)
    ap.add_argument("--model", help="whisper.cpp model, e.g. ggml-medium.en.bin")
    ap.add_argument("--credit", help="text burned at the top, e.g. twitch.tv/NAME")
    a = ap.parse_args(argv)
    cut(a.src, a.spike, a.out, a.pre, a.dur)
    print(a.out)
    if a.model:
        srt = transcribe(a.out, a.model)
        final = os.path.splitext(a.out)[0] + ".captioned.mp4"
        burn(a.out, srt, final, a.credit, a.dur)
        print(final)


if __name__ == "__main__":
    main()
