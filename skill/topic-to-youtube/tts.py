#!/usr/bin/env python
"""Kokoro TTS renderer.

Renders one narration text file to a 24 kHz WAV, chunk by chunk, inserting
natural pauses at paragraph breaks so the result reads like a person talking
rather than a machine reciting.
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


def normalise(text: str) -> str:
    """Make the text speakable: expand symbols, strip anything a voice would trip on."""
    t = text
    t = t.replace("—", ", ").replace("–", ", ")
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"\bUS\$(\d)", r"\1 US dollars ", t)
    t = re.sub(r"\bS\$(\d)", r"\1 Singapore dollars ", t)
    t = t.replace("%", " percent")
    t = t.replace("&", " and ")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def segments(text: str):
    """Yield (text, trailing_silence_seconds) tuples.

    Paragraphs get a real breath after them; long paragraphs are split on
    sentence boundaries so the model never sees more than it handles well.
    """
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        sentences = re.split(r"(?<=[.!?])\s+", para)
        buf = ""
        chunks = []
        for s in sentences:
            if len(buf) + len(s) < 380:
                buf = f"{buf} {s}".strip()
            else:
                if buf:
                    chunks.append(buf)
                buf = s
        if buf:
            chunks.append(buf)
        for i, c in enumerate(chunks):
            last = i == len(chunks) - 1
            yield c, (0.55 if last else 0.16)


def render(src: Path, dst: Path, voice: str, speed: float) -> float:
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    text = normalise(src.read_text())
    pieces = []
    for chunk, gap in segments(text):
        for _, _, audio in pipeline(chunk, voice=voice, speed=speed):
            pieces.append(np.asarray(audio, dtype=np.float32))
        pieces.append(np.zeros(int(SR * gap), dtype=np.float32))

    if not pieces:
        raise SystemExit(f"nothing rendered for {src}")

    out = np.concatenate(pieces)
    peak = float(np.max(np.abs(out))) or 1.0
    out = (out / peak) * 0.89  # consistent loudness across chapters
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(dst, out, SR)
    return len(out) / SR


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    voice = sys.argv[3] if len(sys.argv) > 3 else "bm_george"
    speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    secs = render(src, dst, voice, speed)
    print(f"{dst.name}  {secs/60:.2f} min")
