#!/usr/bin/env python3
"""Render a workspace's narration with Qwen3-TTS.

Usage: <qwen venv python> qwen_tts_render.py <workspace> [speaker] [instruct]

WHY THIS REPLACES THE PER-CHAPTER tts.py CALL
Kokoro is 82M parameters and cheap enough to run six copies at once, one per chapter.
Qwen3-TTS is 1.7B and about 4.3GB of weights, so six copies would want ~20GB against
26GB of RAM — and MPS is one GPU, so parallel workers queue rather than overlap. The
right shape is therefore the opposite of Kokoro's: ONE process, model loaded once,
chapters rendered in sequence.

MEASURED ON AN M4 PRO (24 Aug 2026)
    1.7B float32   4.15x realtime, degrading to 11.49x    memory pressure
    1.7B bfloat16  1.16x, settling to 1.10x               usable
    0.6B bfloat16  1.41x, settling to 1.13x               no faster in practice
So: the big model, in bfloat16. dtype is the whole difference — float32 on MPS spills
and the run gets progressively slower rather than failing outright, which is the
hardest kind of problem to notice.

Still resumable: chapters with an existing non-empty wav are skipped, so a killed run
costs only what it had not already finished.
"""
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

SR = 24_000
DEFAULT_INSTRUCT = ("Documentary narrator. Measured and clear, speaking to one person. "
                    "Land the numbers deliberately; let the pauses sit.")


def normalise(text: str) -> str:
    """Make the text speakable. Mirrors the Kokoro path so scripts stay portable."""
    t = text
    t = t.replace("–", "—")
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"\bUS\$(\d)", r"\1 US dollars ", t)
    t = re.sub(r"\bS\$(\d)", r"\1 Singapore dollars ", t)
    t = t.replace("%", " percent")
    t = t.replace("&", " and ")
    # **emphasis** is a pacing instruction for the Kokoro engine, not something to speak.
    # Qwen carries emphasis through `instruct` instead, so strip the markers.
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


# CHUNK SIZE IS THE WHOLE PERFORMANCE STORY (measured 24 Aug 2026, M4 Pro, bf16).
# Generation cost per second of audio rises sharply with the length of a single call:
#
#     ~220 chars per call   1.04x realtime
#     ~264 chars per call   1.23x
#     ~700 chars per call   7.01x        <- a full chapter took 29 min to render
#
# So a 30-minute video is either ~31 minutes of TTS or ~3.5 hours, depending on nothing
# but this number. Keep calls short and stitch them; the model ends a span cleanly, so
# the joins are not audible.
CHUNK_CHARS = 200


def paragraphs(text: str):
    """Split into short spans. See CHUNK_CHARS — this is the difference between
    1x and 7x realtime, not a stylistic choice."""
    raw = [p.strip() for p in text.split("\n\n") if p.strip()]
    paras = []
    for p in raw:
        if len(p) <= CHUNK_CHARS:
            paras.append(p)
            continue
        # break an over-long paragraph on sentence boundaries
        buf2 = ""
        for sent in re.split(r"(?<=[.!?])\s+", p):
            if len(buf2) + len(sent) < CHUNK_CHARS:
                buf2 = f"{buf2} {sent}".strip()
            else:
                if buf2:
                    paras.append(buf2)
                buf2 = sent
        if buf2:
            paras.append(buf2)
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) < CHUNK_CHARS:
            buf = f"{buf}\n\n{p}".strip()
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def main():
    ws = Path(sys.argv[1])
    speaker = sys.argv[2] if len(sys.argv) > 2 else "Ryan"
    instruct = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_INSTRUCT

    files = sorted((ws / "narration").glob("*.txt"))
    if not files:
        sys.exit(f"no narration/*.txt in {ws}")
    todo = [f for f in files
            if not (ws / "wav" / f"{f.stem}.wav").exists()
            or (ws / "wav" / f"{f.stem}.wav").stat().st_size == 0]
    for f in files:
        if f not in todo:
            print(f"skip {f.stem}", flush=True)
    if not todo:
        print("all chapters already rendered", flush=True)
        return

    from qwen_tts import Qwen3TTSModel
    t0 = time.time()
    model = Qwen3TTSModel.from_pretrained(
        os.environ.get("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        device_map=os.environ.get("QWEN_TTS_DEVICE", "mps"),
        dtype=torch.bfloat16,            # NOT float32 — see the note above
    )
    print(f"model loaded in {time.time()-t0:.0f}s · speaker={speaker}", flush=True)

    (ws / "wav").mkdir(parents=True, exist_ok=True)
    for f in todo:
        t1 = time.time()
        chunks = paragraphs(normalise(f.read_text()))
        pieces = []
        for c in chunks:
            wavs, sr = model.generate_custom_voice(
                text=c, language="English", speaker=speaker, instruct=instruct)
            a = np.asarray(wavs[0], dtype=np.float32)
            pieces.append(a)
            # a real breath between paragraphs; Qwen ends a span cleanly but does not
            # know that the next one is a new argument
            pieces.append(np.zeros(int(sr * 0.42), dtype=np.float32))
        audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
        out = ws / "wav" / f"{f.stem}.wav"
        sf.write(str(out), audio, sr)
        dur = len(audio) / sr
        print(f"{f.stem}  {dur/60:.2f} min  ({(time.time()-t1)/dur:.2f}x realtime)", flush=True)


if __name__ == "__main__":
    main()
