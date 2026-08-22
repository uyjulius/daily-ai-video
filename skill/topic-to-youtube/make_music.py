#!/usr/bin/env python3
"""Generate a rights-free ambient score for narration.

Usage: <tts venv python> make_music.py <out.wav> [minutes] [seed|slug]

PASS THE VIDEO'S ACTUAL RUNTIME. render_videos.py loops this file with
`-stream_loop -1`, so a 3-minute bed under a 30-minute video is heard ten times.
Generating to length costs a few seconds and removes the repetition entirely.

Designed to sit UNDER a voice at about -26 dB: present, but never competing.

WHAT CHANGED (22 Aug 2026) AND WHY
The previous version looped four 16-second chords — a 64-second cycle repeated ~28
times across a half-hour video — with a hardcoded seed, so every video on the channel
carried the identical bed. It was correct and inoffensive and extremely dull.

Four things fix that, in rough order of how much they matter:

  1. NOTHING REPEATS ON A SHORT CYCLE. Chord lengths are irregular (11-23 s) and the
     progression is 8-10 chords, so the harmonic cycle is 2-3 minutes rather than 64
     seconds, and the layers above it never line up the same way twice.
  2. SPARSE BELLS. Occasional single notes high above the pad, struck on no fixed
     grid, with long decays. This is what gives the ear something to follow without
     giving it something to listen TO.
  3. SLOW TIMBRAL MOVEMENT. A one-pole lowpass whose cutoff drifts over minutes, so
     the pad opens and closes rather than sitting still.
  4. SEEDED PER VIDEO. Pass the slug; key, mode, progression and bell placement all
     derive from it. Two videos never sound the same.

Plus a dynamic arc: density and level rise and fall over the piece instead of running
flat for thirty minutes.

Needs numpy + soundfile (both present in the Kokoro TTS venv).
"""
import hashlib
import sys

import numpy as np
import soundfile as sf

SR = 24_000

# Modes as semitone offsets. Each carries a different colour; aeolian is the safe
# documentary default, dorian lifts slightly, phrygian darkens.
MODES = {
    "aeolian":  [0, 2, 3, 5, 7, 8, 10],
    "dorian":   [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "minor_pent": [0, 3, 5, 7, 10],
}


def seed_from(arg):
    """Accept an int seed or any string (a slug); both give a stable integer."""
    try:
        return int(arg)
    except (TypeError, ValueError):
        return int(hashlib.sha256(str(arg).encode()).hexdigest()[:8], 16)


def one_pole_lp(x, cutoff_hz):
    """One-pole lowpass with a per-sample (array) cutoff, so it can sweep.

    Written as an explicit loop over blocks: a true per-sample IIR in numpy would be
    a Python loop over 40M samples. Blocks of 2048 keep the sweep smooth to the ear
    while staying fast.
    """
    out = np.empty_like(x)
    y = 0.0
    n = len(x)
    block = 2048
    for i in range(0, n, block):
        j = min(i + block, n)
        fc = float(np.mean(cutoff_hz[i:j])) if isinstance(cutoff_hz, np.ndarray) else float(cutoff_hz)
        a = np.exp(-2 * np.pi * max(20.0, fc) / SR)
        seg = x[i:j]
        # vectorised one-pole over the block, carrying y across blocks
        b = 1 - a
        acc = np.empty_like(seg)
        for k in range(len(seg)):
            y = a * y + b * seg[k]
            acc[k] = y
        out[i:j] = acc
    return out


def pad_voice(freq, dur, rng, detune=0.12):
    """One sustained voice: fundamental plus soft harmonics, gently detuned."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    out = np.zeros_like(t)
    for f in (freq, freq * (1 + detune / 100)):
        for h, ha in ((1, 1.0), (2, 0.32), (3, 0.11), (4, 0.045), (6, 0.02)):
            out += ha * np.sin(2 * np.pi * f * h * t + rng.random() * 6.28)
    # bloom in, fall away — long enough that chords overlap rather than step
    env = np.minimum(1, t / (dur * 0.38)) * np.minimum(1, (dur - t) / (dur * 0.45))
    return out * env


def bell(freq, dur, rng):
    """A struck note with inharmonic partials and a long exponential decay."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    out = np.zeros_like(t)
    for h, ha, dcy in ((1, 1.0, 1.0), (2.76, 0.28, 1.9), (5.4, 0.11, 2.8), (8.9, 0.04, 3.6)):
        out += ha * np.sin(2 * np.pi * freq * h * t + rng.random() * 6.28) * np.exp(-dcy * t / (dur * 0.42))
    out *= np.minimum(1, t / 0.004)          # tiny attack so it does not click
    return out


def main(out_path, minutes=3.0, seed_arg=7):
    seed = seed_from(seed_arg)
    rng = np.random.default_rng(seed)

    # --- identity: key and mode come from the seed, so each video differs ---------
    root_midi = 50 + int(rng.integers(0, 7))          # D3-ish through A3-ish
    mode_name = list(MODES)[int(rng.integers(0, len(MODES)))]
    mode = MODES[mode_name]
    f_of = lambda m: 440.0 * 2 ** ((m - 69) / 12)

    # --- progression: 8-10 chords, irregular lengths -----------------------------
    n_chords = int(rng.integers(8, 11))
    degrees = [0]
    for _ in range(n_chords - 1):
        # move by a mode degree, favouring stepwise-ish motion over random leaps
        degrees.append(int(rng.choice([1, 2, 3, 4, 5, 6], p=[.22, .12, .22, .18, .16, .10])))
    lengths = [float(rng.integers(11, 24)) for _ in degrees]

    total_s = max(60.0, minutes * 60.0)
    pieces, bells_at, cursor = [], [], 0.0
    while cursor < total_s:
        # Mutate the progression on every pass. Without this a half-hour piece runs
        # the same 8-10 chords eleven times; one substituted degree and a reshuffled
        # length per cycle keeps it recognisable but never literally repeating.
        if pieces:
            i = int(rng.integers(1, len(degrees)))
            degrees[i] = int(rng.choice([1, 2, 3, 4, 5, 6], p=[.22, .12, .22, .18, .16, .10]))
            j = int(rng.integers(0, len(lengths)))
            lengths[j] = float(rng.integers(11, 24))
        for deg, ln in zip(degrees, lengths):
            if cursor >= total_s:
                break
            base = root_midi + mode[deg % len(mode)] + 12 * (deg // len(mode))
            # triad from the mode, voiced open
            chord = [base, base + mode[(deg + 2) % len(mode)] - mode[deg % len(mode)] + 0,
                     base + 7 + int(rng.integers(-1, 2))]
            seg = np.zeros(int(SR * ln))
            for i, m in enumerate(chord):
                f = f_of(m - 12 if i == 0 else m)      # root an octave down
                seg += pad_voice(f, ln, rng) * (0.9 if i == 0 else 0.45)
            pieces.append(seg)
            # schedule bells inside this chord — sparse, never on a grid
            if rng.random() < 0.88:
                for _ in range(int(rng.integers(1, 4))):
                    at = cursor + float(rng.uniform(1.0, ln - 1.0))
                    deg_b = int(rng.integers(0, len(mode)))
                    oct_b = int(rng.choice([12, 24, 24, 36]))
                    bells_at.append((at, root_midi + mode[deg_b] + oct_b))
            cursor += ln

    mono = np.concatenate(pieces)[: int(SR * total_s)]
    n = len(mono)
    t = np.arange(n) / SR

    # --- slow filter movement: the pad opens and closes over minutes -------------
    cutoff = 520 + 380 * np.sin(2 * np.pi * t / 190.0) + 160 * np.sin(2 * np.pi * t / 71.0)
    mono = one_pole_lp(mono, cutoff)
    mono /= (np.max(np.abs(mono)) or 1)

    # --- bells: the layer that gives the ear something to follow ----------------
    bell_bus = np.zeros(n)
    for at, midi in bells_at:
        i0 = int(at * SR)
        dur = float(rng.uniform(3.5, 7.0))
        b = bell(f_of(midi), dur, rng) * float(rng.uniform(0.07, 0.15))
        i1 = min(n, i0 + len(b))
        if i1 > i0:
            bell_bus[i0:i1] += b[: i1 - i0]

    # --- sub swell: felt more than heard, keeps the floor from feeling empty -----
    sub = 0.16 * np.sin(2 * np.pi * f_of(root_midi - 24) * t) * (0.5 + 0.5 * np.sin(2 * np.pi * t / 23.0))

    # --- air ---------------------------------------------------------------------
    noise = rng.standard_normal(n)
    for _ in range(3):
        noise = np.convolve(noise, np.ones(420) / 420, mode="same")
    noise /= (np.max(np.abs(noise)) or 1)

    mix = mono + bell_bus + sub + 0.10 * noise

    # --- dynamic arc: three long swells, so half an hour is not flat -------------
    arc = 0.72 + 0.28 * (0.5 + 0.5 * np.sin(2 * np.pi * t / (total_s / 3.0) - np.pi / 2))
    mix *= arc

    # --- fades and stereo --------------------------------------------------------
    fade = int(SR * 4)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    d = int(SR * 0.017)
    st = np.stack([mix, np.concatenate([mix[d:], mix[:d]])], axis=1)
    st /= (np.max(np.abs(st)) or 1)
    st *= 0.7

    sf.write(out_path, st.astype(np.float32), SR)
    print(f"wrote {out_path}  {n/SR/60:.1f} min  key={root_midi} mode={mode_name} "
          f"chords={n_chords} bells={len(bells_at)}")


if __name__ == "__main__":
    main(sys.argv[1],
         float(sys.argv[2]) if len(sys.argv) > 2 else 3.0,
         sys.argv[3] if len(sys.argv) > 3 else 7)
