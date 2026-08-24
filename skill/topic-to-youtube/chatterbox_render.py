#!/usr/bin/env python3
"""Render a workspace's narration with Chatterbox (Resemble AI).

Usage: <chatter venv python> chatterbox_render.py <workspace> [voice_sample.wav]

CHUNK SIZE IS THE PERFORMANCE STORY, AND IT IS THE OPPOSITE OF QWEN'S
Measured on an M4 Pro, 25 Aug 2026, same real chapter:

    ~296 chars per call   5.66x realtime      (cold, and genuinely slower)
    ~450 chars per call   1.29x               <- the working point
    ~520 chars per call   1.51x

Qwen3-TTS wanted SHORT calls (200 chars; 700 cost it 7x). Chatterbox wants LONG ones.
Getting this backwards costs 4-7x either way, so it is not a stylistic choice and it
does not transfer between engines.

EXPRESSIVENESS
`exaggeration` (0.5 default) drives how much emotional range it uses, `cfg_weight`
how closely it tracks the reference. For documentary narration the defaults are a
little animated; 0.35 / 0.6 reads as measured without going flat. Both are tunable
from the environment, so this can be adjusted without editing code.

VOICE CLONING
Pass a WAV of any voice as the second argument and it matches it. Nothing else in this
pipeline can do that. Keep the sample clean, 10-30 seconds, one speaker.

Resumable: chapters with a non-empty wav are skipped.
"""
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

CHUNK_CHARS = int(os.environ.get("CHATTER_CHUNK", "450"))
EXAGGERATION = float(os.environ.get("CHATTER_EXAGGERATION", "0.35"))
CFG_WEIGHT = float(os.environ.get("CHATTER_CFG", "0.6"))
GAP_PARA = 0.42


def normalise(text: str) -> str:
    t = text
    t = t.replace("–", "—")
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"\bUS\$(\d)", r"\1 US dollars ", t)
    t = re.sub(r"\bS\$(\d)", r"\1 Singapore dollars ", t)
    t = t.replace("%", " percent")
    t = t.replace("&", " and ")
    # **emphasis** is a pacing marker for the Kokoro engine; Chatterbox does its own
    # prosody, so strip the markers rather than speaking them.
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def chunks(text: str):
    """Group paragraphs up to CHUNK_CHARS, splitting any single paragraph that is
    itself longer, so one big paragraph cannot blow the working point."""
    raw = [p.strip() for p in text.split("\n\n") if p.strip()]
    parts = []
    for p in raw:
        if len(p) <= CHUNK_CHARS:
            parts.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[.!?])\s+", p):
            if len(buf) + len(s) < CHUNK_CHARS:
                buf = f"{buf} {s}".strip()
            else:
                if buf:
                    parts.append(buf)
                buf = s
        if buf:
            parts.append(buf)
    out, buf = [], ""
    for p in parts:
        if len(buf) + len(p) < CHUNK_CHARS:
            buf = f"{buf} {p}".strip()
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def main():
    ws = Path(sys.argv[1])
    prompt = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] not in ("", "-") else None

    files = sorted((ws / "narration").glob("*.txt"))
    if not files:
        sys.exit(f"no narration/*.txt in {ws}")
    todo = []
    for f in files:
        w = ws / "wav" / f"{f.stem}.wav"
        if w.exists() and w.stat().st_size > 0:
            print(f"skip {f.stem}", flush=True)
        else:
            todo.append(f)
    if not todo:
        print("all chapters already rendered", flush=True)
        return

    import torch
    from chatterbox.tts import ChatterboxTTS
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    t0 = time.time()
    model = ChatterboxTTS.from_pretrained(device=dev)
    print(f"model loaded on {dev} in {time.time()-t0:.0f}s "
          f"(chunk {CHUNK_CHARS}, exaggeration {EXAGGERATION}, cfg {CFG_WEIGHT})", flush=True)

    (ws / "wav").mkdir(parents=True, exist_ok=True)
    for f in todo:
        t1 = time.time()
        pieces = []
        for c in chunks(normalise(f.read_text())):
            wav = model.generate(c, audio_prompt_path=prompt,
                                 exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT)
            a = wav.squeeze(0).cpu().numpy().astype(np.float32)
            pieces.append(a)
            pieces.append(np.zeros(int(model.sr * GAP_PARA), dtype=np.float32))
        audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
        sf.write(str(ws / "wav" / f"{f.stem}.wav"), audio, model.sr)
        dur = len(audio) / model.sr
        print(f"{f.stem}  {dur/60:.2f} min  ({(time.time()-t1)/dur:.2f}x realtime)", flush=True)


if __name__ == "__main__":
    main()
