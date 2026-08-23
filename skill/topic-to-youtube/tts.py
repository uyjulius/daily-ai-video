#!/usr/bin/env python
"""Kokoro TTS renderer.

Renders one narration text file to a 24 kHz WAV, chunk by chunk, with pacing that
makes the result read like a person talking to someone rather than a machine
reciting at a wall.

WHY THE PACING LIVES HERE AND NOT IN THE MODEL (measured 23 Aug 2026)
Kokoro is close to deaf to punctuation. Rendering the same clause with a comma, an
em-dash, a full stop or a colon gives the same ~0.24 s internal pause and the same
duration to within 6%. A question mark does not raise the final pitch — statements and
questions both fall, 82 Hz vs 88 Hz. CAPITALS produce a byte-identical pitch contour to
the lower-case version. So none of the devices a writer would reach for survive the
model. The only thing that changed anything was silence inserted between calls.

Everything expressive therefore has to be done here, by controlling two things Kokoro
does expose: where the silence goes, and the speed of each call.

    paragraph break        0.55 s   the argument moves on
    single line break      0.32 s   a beat inside an argument — was previously ignored
    em-dash                0.22 s   the aside, the correction, the turn
    **emphasis**           0.34 s before, 0.90x speed, 0.34 s after

The em-dash rule alone recovers 288 emphasis moments already sitting in the existing
scripts, which the previous version flattened into commas.
"""
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

SR = 24_000
ROOT = Path(__file__).resolve().parent.parent

# CALIBRATION. Splitting one utterance into two Kokoro calls costs about 0.82 s on its
# own — the model pads each call's onset and offset — so inserted silence sits ON TOP of
# that. Measured: "wrong, badly wrong" is 2.65 s in one call and 3.48 s split with zero
# inserted. The figures below are therefore the *extra* silence, chosen so the four
# devices land as an audible ladder rather than four similar-sounding gaps:
#
#     em-dash          ~0.82 s total   the quick catch — the split alone carries it
#     line break       ~1.07 s total   a beat inside an argument
#     paragraph        ~1.37 s total   the argument moves on (unchanged from before)
#     **emphasis**     ~1.16 s each side, and 10% slower through the span
PAUSE_PARA = 0.55
PAUSE_LINE = 0.25
PAUSE_DASH = 0.00
PAUSE_EMPH = 0.34
EMPH_SPEED = 0.90          # a touch slower; the ear reads it as weight


def normalise(text: str) -> str:
    """Make the text speakable. Keeps the em-dash — it is now a pacing instruction."""
    t = text
    t = t.replace("–", "—")                       # en-dash reads as the same beat
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"\bUS\$(\d)", r"\1 US dollars ", t)
    t = re.sub(r"\bS\$(\d)", r"\1 Singapore dollars ", t)
    t = t.replace("%", " percent")
    t = t.replace("&", " and ")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def _split_emphasis(s: str):
    """Split a run of text into (text, is_emphasised) pieces on **markers**."""
    out, pos = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*", s):
        if m.start() > pos:
            out.append((s[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], False))
    return [(t.strip(), e) for t, e in out if t.strip()]


def segments(text: str):
    """Yield (text, trailing_silence_seconds, speed_multiplier).

    Paragraphs get a real breath, single line breaks get a beat, em-dashes get the
    short catch a writer means by them, and **marked** spans slow down with air
    either side. Long runs are still split on sentence boundaries so the model never
    sees more than it handles well.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    for pi, para in enumerate(paras):
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        for li, line in enumerate(lines):
            last_line = li == len(lines) - 1
            # split the line into em-dash-separated runs
            runs = [r.strip() for r in line.split("—") if r.strip()]
            for ri, run in enumerate(runs):
                last_run = ri == len(runs) - 1
                pieces = _split_emphasis(run) or [(run, False)]
                for qi, (piece, emph) in enumerate(pieces):
                    last_piece = qi == len(pieces) - 1
                    # chunk very long pieces on sentence boundaries
                    sentences = re.split(r"(?<=[.!?])\s+", piece)
                    buf, chunks = "", []
                    for s in sentences:
                        if len(buf) + len(s) < 380:
                            buf = f"{buf} {s}".strip()
                        else:
                            if buf:
                                chunks.append(buf)
                            buf = s
                    if buf:
                        chunks.append(buf)
                    for ci, c in enumerate(chunks):
                        last_chunk = ci == len(chunks) - 1
                        if emph:
                            # air before an emphasised span, and after it
                            yield "", PAUSE_EMPH if ci == 0 else 0.0, 1.0
                            tail = PAUSE_EMPH if last_chunk else 0.10
                            yield c, tail, EMPH_SPEED
                            continue
                        if not last_chunk:
                            tail = 0.16
                        elif not last_piece:
                            tail = 0.10
                        elif not last_run:
                            tail = PAUSE_DASH
                        elif not last_line:
                            tail = PAUSE_LINE
                        else:
                            tail = PAUSE_PARA
                        yield c, tail, 1.0


def render(src: Path, dst: Path, voice: str, speed: float) -> float:
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    text = normalise(src.read_text())
    out = []
    for chunk, gap, mult in segments(text):
        if chunk:
            for _, _, audio in pipeline(chunk, voice=voice, speed=speed * mult):
                out.append(np.asarray(audio, dtype=np.float32))
        if gap > 0:
            out.append(np.zeros(int(SR * gap), dtype=np.float32))
    audio = np.concatenate(out) if out else np.zeros(1, dtype=np.float32)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), audio, SR)
    return len(audio) / SR


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    voice = sys.argv[3] if len(sys.argv) > 3 else "bm_george"
    speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    secs = render(src, dst, voice, speed)
    print(f"{dst.name}  {secs/60:.2f} min")


if __name__ == "__main__":
    main()
