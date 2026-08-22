#!/usr/bin/env python3
"""Generate a rights-free UPBEAT music bed for narration.

Usage: <tts venv python> make_music.py <out.wav> [minutes] [seed|slug]

PASS THE VIDEO'S ACTUAL RUNTIME. render_videos.py loops this file with
`-stream_loop -1`, so a 3-minute bed under a 30-minute video is heard ten times.
Generating to length costs a few seconds and removes the repetition entirely.

DESIGN (22 Aug 2026). This replaced an ambient pad score, which was correct,
inoffensive and dull. This version is rhythmic — kick, hats, bass and plucked chords
at 88-104 BPM — because the channel is an explainer, not a memorial.

Two constraints shape every choice:

  1. IT PLAYS UNDER A VOICE at about -26 dB, with sidechain ducking on top. So:
     no snare crack, no bright cymbals, no melodic hook that competes with the
     narration. The drums are felt more than heard — a soft kick, closed hats well
     down, and a rim tick rather than a backbeat.
  2. IT RUNS FOR HALF AN HOUR. So it is built in 8-bar sections that add and drop
     layers, with fills at section boundaries, rather than a loop repeated 200 times.

Key, mode, tempo, drum pattern and progression all seed from the slug, so no two
videos share a score.

Needs numpy + soundfile (both present in the Kokoro TTS venv).
"""
import hashlib
import sys

import numpy as np
import soundfile as sf

SR = 24_000

MODES = {
    "aeolian":    [0, 2, 3, 5, 7, 8, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "minor_pent": [0, 3, 5, 7, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
}


def seed_from(arg):
    try:
        return int(arg)
    except (TypeError, ValueError):
        return int(hashlib.sha256(str(arg).encode()).hexdigest()[:8], 16)


def f_of(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


# --------------------------------------------------------------------- drum voices
def kick(dur=0.32, f0=110.0, f1=44.0):
    """Soft round kick: a fast pitch sweep, no click. Felt, not heard."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    f = f1 + (f0 - f1) * np.exp(-t * 26)
    env = np.exp(-t * 11)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env


def hat(dur=0.055, bright=7000.0):
    """Closed hat: short filtered noise. Kept dull so it never sizzles."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    n = np.random.default_rng(int(bright)).standard_normal(len(t))
    n = n - np.convolve(n, np.ones(9) / 9, mode="same")      # crude highpass
    return n * np.exp(-t * 95)


def rim(dur=0.09):
    """Rim tick instead of a snare — presence on the backbeat without a crack."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    tone = np.sin(2 * np.pi * 340 * t) * np.exp(-t * 60)
    n = np.random.default_rng(3).standard_normal(len(t)) * np.exp(-t * 130)
    return 0.7 * tone + 0.3 * n


def pluck(freq, dur, rng):
    """Karplus-Strong-ish plucked string: warm, decays fast, sits in the mids."""
    n = int(SR * dur)
    period = max(2, int(SR / freq))
    buf = rng.standard_normal(period) * 0.5
    buf -= buf.mean()
    out = np.empty(n)
    idx = 0
    for i in range(n):
        v = buf[idx]
        nxt = buf[(idx + 1) % period]
        buf[idx] = 0.497 * (v + nxt)          # slightly <0.5 so it decays
        out[i] = v
        idx = (idx + 1) % period
    t = np.linspace(0, dur, n, endpoint=False)
    return out * np.exp(-t * 3.1)


def bass(freq, dur):
    """Round sub-forward bass note."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    w = (np.sin(2 * np.pi * freq * t)
         + 0.30 * np.sin(2 * np.pi * freq * 2 * t)
         + 0.10 * np.sin(2 * np.pi * freq * 3 * t))
    env = np.minimum(1, t / 0.012) * np.exp(-t * 2.3)
    return w * env


def add(buf, sig, at, gain=1.0):
    i0 = int(at * SR)
    i1 = min(len(buf), i0 + len(sig))
    if i1 > i0:
        buf[i0:i1] += sig[: i1 - i0] * gain


def main(out_path, minutes=3.0, seed_arg=7):
    rng = np.random.default_rng(seed_from(seed_arg))

    bpm = float(rng.integers(88, 105))
    beat = 60.0 / bpm
    bar = beat * 4
    root_midi = 33 + int(rng.integers(0, 8))            # A1..E2 region for bass
    mode_name = list(MODES)[int(rng.integers(0, len(MODES)))]
    mode = MODES[mode_name]

    # 4-chord progression, repeated with variation; degrees within the mode
    prog = [0] + [int(rng.choice([2, 3, 4, 5, 6])) for _ in range(3)]

    total_s = max(30.0, minutes * 60.0)
    n = int(SR * total_s) + SR * 4
    drums = np.zeros(n)
    tonal = np.zeros(n)

    # Kick placements within a bar, in beats. Two patterns, chosen per section.
    kick_sets = [[0, 1.5, 2.5], [0, 2.5], [0, 1.5, 2, 3.5], [0, 2, 3.5]]
    hat_div = float(rng.choice([0.5, 0.5, 0.25]))       # 8ths, sometimes 16ths

    bars = int(total_s / bar) + 1
    section = 0
    for b in range(bars):
        t0 = b * bar
        if t0 > total_s:
            break
        # --- section logic: every 8 bars, change what is playing ----------------
        if b % 8 == 0:
            section += 1
            kpat = kick_sets[int(rng.integers(0, len(kick_sets)))]
            # density rises and falls so half an hour is not one texture
            has_hat = (section % 4) != 1
            has_rim = (section % 3) != 1
            has_pluck = (section % 5) != 2
            level = 0.75 + 0.25 * float(rng.random())
        chord_deg = prog[(b // 2) % len(prog)]
        base = root_midi + mode[chord_deg % len(mode)]

        # --- drums ---------------------------------------------------------------
        for kb in kpat:
            add(drums, kick(), t0 + kb * beat, 0.90 * level)
        if has_hat:
            steps = int(4 / hat_div)
            for sidx in range(steps):
                if rng.random() < 0.90:
                    v = 0.16 if sidx % 2 == 0 else 0.10
                    add(drums, hat(bright=6000 + 400 * (sidx % 5)), t0 + sidx * hat_div * beat, v * level)
        if has_rim:
            add(drums, rim(), t0 + 1 * beat, 0.30 * level)
            add(drums, rim(), t0 + 3 * beat, 0.30 * level)
        # fill on the last bar of a section
        if b % 8 == 7:
            for k in range(3):
                add(drums, rim(), t0 + (3 + k * 0.25) * beat, 0.22 * level)

        # --- bass: root on 1, a syncopated answer ---------------------------------
        add(tonal, bass(f_of(base), beat * 1.1), t0, 0.55 * level)
        if rng.random() < 0.7:
            add(tonal, bass(f_of(base), beat * 0.55), t0 + 2.5 * beat, 0.38 * level)
        if rng.random() < 0.35:
            add(tonal, bass(f_of(base + 7), beat * 0.5), t0 + 3.5 * beat, 0.30 * level)

        # --- plucked chord tones: the melodic interest, kept sparse ---------------
        if has_pluck:
            for off in (0, 2, 4):
                if rng.random() < 0.55:
                    m = base + 24 + mode[(chord_deg + off) % len(mode)] - mode[chord_deg % len(mode)]
                    at = t0 + float(rng.choice([0, 1, 1.5, 2, 2.5, 3, 3.5])) * beat
                    add(tonal, pluck(f_of(m), 0.9, rng), at, 0.20 * level)

    drums = drums[: int(SR * total_s)]
    tonal = tonal[: int(SR * total_s)]
    t = np.arange(len(drums)) / SR

    # gentle air so the gaps are not silent
    air = rng.standard_normal(len(drums))
    for _ in range(3):
        air = np.convolve(air, np.ones(300) / 300, mode="same")
    air /= (np.max(np.abs(air)) or 1)

    mix = 0.85 * drums + 1.0 * tonal + 0.05 * air

    # long arc so the whole piece breathes
    mix *= 0.80 + 0.20 * np.sin(2 * np.pi * t / (total_s / 2.5) - np.pi / 2)

    fade = int(SR * 3)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)

    d = int(SR * 0.011)
    st = np.stack([mix, np.concatenate([mix[d:], mix[:d]])], axis=1)
    st /= (np.max(np.abs(st)) or 1)
    st *= 0.72
    sf.write(out_path, st.astype(np.float32), SR)
    print(f"wrote {out_path}  {len(mix)/SR/60:.1f} min  {bpm:.0f} BPM  mode={mode_name} "
          f"hats={'16th' if hat_div==0.25 else '8th'}")


if __name__ == "__main__":
    main(sys.argv[1],
         float(sys.argv[2]) if len(sys.argv) > 2 else 3.0,
         sys.argv[3] if len(sys.argv) > 3 else 7)
