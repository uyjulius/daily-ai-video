#!/usr/bin/env python3
"""Audition Kokoro voices and measure what each one does to your word budget.

    $ROOT/.venv-tts/bin/python tools/audition-voices.py            # American male
    $ROOT/.venv-tts/bin/python tools/audition-voices.py --all
    $ROOT/.venv-tts/bin/python tools/audition-voices.py --measure af_heart am_liam

Two separate jobs:

  audition  renders a sample per voice plus a single back-to-back reel, and reports a
            median fundamental frequency so "deep" is measured rather than guessed.

  --measure renders REAL multi-paragraph chapters and reports words-per-minute, which
            is the number you put in WPM in config.sh. Do not estimate this from a
            short clip: a single-paragraph sample omits the pauses tts.py inserts at
            paragraph breaks and reads roughly 30 wpm too fast.

Outputs land in ./voice-audition/.
"""
import argparse, glob, os, sys, warnings
import numpy as np
import soundfile as sf
warnings.filterwarnings("ignore")
from kokoro import KPipeline

OUT = os.path.abspath("voice-audition")
SR = 24000

AMERICAN_MALE = ["am_adam", "am_echo", "am_eric", "am_fenrir",
                 "am_liam", "am_michael", "am_onyx", "am_puck"]
ALL_VOICES = AMERICAN_MALE + [
    "af_heart", "af_bella", "af_nicole", "af_sarah",
    "bm_george", "bm_fable", "bm_lewis", "bf_emma", "bf_isabella"]

SAMPLE = ("Over the twenty twenty-two to twenty twenty-four window where both exist, the gap "
          "between the most and least exposed quintiles is minus zero point one three two in "
          "the payroll data. The certainty was manufactured somewhere between the paper and you.")


def say(text, voice):
    pipe = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    chunks = [a for _, _, a in pipe(text, voice=voice, speed=1.0)]
    a = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    return np.asarray(a, dtype=np.float32)


def median_f0(x, sr=SR):
    """Median F0 over voiced frames, by autocorrelation. Lower = deeper."""
    win, hop = int(0.04 * sr), int(0.02 * sr)
    lo, hi = int(sr / 300), int(sr / 60)
    vals = []
    for i in range(0, len(x) - win, hop):
        f = x[i:i + win].astype(np.float64)
        if np.sqrt(np.mean(f ** 2)) < 0.02:
            continue
        f -= f.mean()
        ac = np.correlate(f, f, mode="full")[win - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if not len(seg):
            continue
        pk = int(np.argmax(seg)) + lo
        if ac[pk] / ac[0] > 0.3:
            vals.append(sr / pk)
    return float(np.median(vals)) if vals else float("nan")


def audition(voices):
    os.makedirs(OUT, exist_ok=True)
    rows, reel = [], []
    gap = np.zeros(int(SR * 0.9), dtype=np.float32)
    for v in voices:
        try:
            body = say(SAMPLE, v)
        except Exception as e:
            print(f"{v:12s} FAILED: {type(e).__name__}: {str(e)[:60]}", flush=True)
            continue
        sf.write(os.path.join(OUT, f"{v}.wav"), body, SR)
        f0 = median_f0(body)
        rows.append((v, f0))
        print(f"{v:12s} median F0 {f0:6.1f} Hz", flush=True)
        intro = say(f"Voice {v.split('_')[-1]}. {int(f0)} hertz.", v)
        reel += [intro, np.zeros(int(SR * 0.35), dtype=np.float32), body, gap]
    if reel:
        sf.write(os.path.join(OUT, "AUDITION-REEL.wav"), np.concatenate(reel), SR)
    print("\n--- deepest first ---")
    for v, f0 in sorted([r for r in rows if r[1] == r[1]], key=lambda r: r[1]):
        print(f"  {v:12s} {f0:6.1f} Hz")
    print(f"\nWritten to {OUT}/ — play AUDITION-REEL.wav to compare them back to back.")


def measure(voices, workspace):
    """Words-per-minute on real chapters, pauses included. This is your WPM value."""
    files = sorted(glob.glob(os.path.join(workspace, "narration", "*.txt")))[:3]
    if not files:
        sys.exit(f"No narration/*.txt in {workspace}. Point --workspace at a finished run.")
    words = sum(len(open(f).read().split()) for f in files)
    print(f"Measuring on {len(files)} real chapters, {words} words "
          f"(multi-paragraph, so tts.py's pauses are included).\n")
    print(f"{'voice':12s} {'minutes':>9s} {'wpm':>7s}   {'words for 30 min':>17s}")
    os.makedirs(OUT, exist_ok=True)
    for v in voices:
        total = 0.0
        for f in files:
            a = say(open(f).read(), v)
            total += len(a) / SR / 60
        wpm = words / total
        print(f"{v:12s} {total:9.2f} {wpm:7.1f}   {int(round(wpm*30)):17d}")
    print("\nPut the wpm for your chosen voice into WPM in daily/config.sh.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="audition every bundled voice")
    ap.add_argument("--measure", nargs="+", metavar="VOICE",
                    help="measure words-per-minute for these voices")
    ap.add_argument("--workspace", default=".",
                    help="a finished run's workspace, for --measure (needs narration/)")
    a = ap.parse_args()
    if a.measure:
        measure(a.measure, a.workspace)
    else:
        audition(ALL_VOICES if a.all else AMERICAN_MALE)
