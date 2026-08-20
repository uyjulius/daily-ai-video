#!/usr/bin/env python3
"""Generate a rights-free ambient music bed for narration (documentary style).

Usage: <tts venv python> make_music.py <out.wav> [minutes] [seed]

Synthesizes a slow, seamless-looping pad: minor-key chord drones with soft
harmonics, gentle amplitude breathing, and a filtered noise air layer. Designed
to sit UNDER a voice at ~-26 dB — evocative but never attention-grabbing.
Needs numpy + soundfile (present in the Kokoro TTS venv).
"""
import sys

import numpy as np
import soundfile as sf

SR = 24_000


def note(freq, dur, amp=1.0, detune=0.15):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    out = np.zeros_like(t)
    # soft additive tone: fundamental + gentle harmonics, slightly detuned pair
    for f in (freq, freq * (1 + detune / 100)):
        for h, ha in ((1, 1.0), (2, 0.35), (3, 0.12), (4, 0.05)):
            out += ha * np.sin(2 * np.pi * f * h * t + np.random.rand() * 6.28)
    # slow attack/release so chords bloom instead of hitting
    env = np.minimum(1, t / (dur * 0.35)) * np.minimum(1, (dur - t) / (dur * 0.4))
    return amp * out * env


def main(out_path, minutes=3.0, seed=7):
    np.random.seed(seed)
    # D natural minor pads: i - VI - III - VII, 16 s per chord
    A3 = 220.0
    semis = lambda n: A3 * 2 ** (n / 12)
    chords = [
        [semis(-7), semis(-2), semis(1)],    # D minor  (D F A)
        [semis(-9), semis(-2), semis(1)],    # Bb major (Bb D F -> voiced close)
        [semis(-4), semis(1), semis(5)],     # F major
        [semis(-2), semis(3), semis(6)],     # C major
    ]
    chord_len = 16.0
    loops = max(1, int(round(minutes * 60 / (chord_len * len(chords)))))
    pieces = []
    for _ in range(loops):
        for ch in chords:
            mix = np.zeros(int(SR * chord_len), dtype=np.float64)
            for i, f in enumerate(ch):
                mix += note(f / 2 if i == 0 else f, chord_len, amp=0.9 if i == 0 else 0.5)
            pieces.append(mix)
    mono = np.concatenate(pieces)
    # air layer: brown-ish noise, heavily low-passed by cumulative smoothing
    noise = np.random.randn(len(mono))
    for _ in range(3):
        noise = np.convolve(noise, np.ones(400) / 400, mode="same")
    mono += 0.6 * noise / (np.max(np.abs(noise)) or 1)
    # slow breathing on the whole bed
    t = np.arange(len(mono)) / SR
    mono *= 0.8 + 0.2 * np.sin(2 * np.pi * t / 37.0)
    # gentle stereo: haas-ish delay on one side
    d = int(SR * 0.013)
    left = mono
    right = np.concatenate([mono[d:], mono[:d]])
    st = np.stack([left, right], axis=1)
    st = st / (np.max(np.abs(st)) or 1) * 0.7
    sf.write(out_path, st.astype(np.float32), SR)
    print(f"wrote {out_path}  {len(mono)/SR/60:.1f} min")


if __name__ == "__main__":
    main(sys.argv[1],
         float(sys.argv[2]) if len(sys.argv) > 2 else 3.0,
         int(sys.argv[3]) if len(sys.argv) > 3 else 7)
