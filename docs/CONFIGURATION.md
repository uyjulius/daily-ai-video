# Configuration

Everything lives in `daily/config.sh`. You should never need to edit `run-daily.sh`.

## Cadence

### `VIDEOS_PER_RUN` (default `1`)
Videos per nightly run, built **sequentially**. Each takes 45–90 minutes and ~1.7GB of
working space (purged after). Clamped to **6** — YouTube's default quota is 10,000
units/day and an upload costs ~1,600.

Video *N* is told what videos 1…*N*−1 already published, so they cannot land on the same
story. Start at 1. Raise it once you trust your beats.

## Narrator

### `VOICE` (default `af_heart`)
Any Kokoro voice. `am_*` American male, `af_*` American female, `bm_*`/`bf_*` British.

```bash
$ROOT/.venv-tts/bin/python tools/audition-voices.py          # American male + a reel
$ROOT/.venv-tts/bin/python tools/audition-voices.py --all
```

### `SPEED` (default `1.0`)
Playback rate passed to Kokoro. Below ~0.85 sounds laboured; above ~1.15 gets hard to
follow for 30 minutes.

### `WPM` — the setting people get wrong
**Measured** words per minute for your `VOICE` at your `SPEED`, *including* the pauses
`tts.py` inserts at paragraph breaks.

Scripts are written to a word budget up front, so this number decides whether a video
lands on its target runtime. **It is a property of the voice, not of the pipeline.**

| Voice | Speed | Rate | Words for 30 min |
|---|---|---|---|
| `af_heart` | 1.0 | 148 wpm | 4,450 |
| `am_liam` | 1.0 | 167 wpm | 5,020 |

Those two are 12.8% apart. Change `VOICE` without changing `WPM` and your videos come out
the wrong length, with nothing erroring.

```bash
$ROOT/.venv-tts/bin/python tools/audition-voices.py --measure am_liam --workspace <a finished run>
```

⚠️ Measure on **real multi-paragraph chapters**. A short single-paragraph sample omits the
paragraph pauses and reads ~30 wpm too fast.

## Reliability

### `MAX_TURNS` (default `800`) — do not remove
Turn cap for each headless `claude -p`. The default cap is far too low for this pipeline,
and hitting it **prints an error and still exits 0**, so it looks like success. This flag
is undocumented in `claude --help` but functional.

### `MAX_ATTEMPTS` (default `3`)
Retries per video. Attempt 1 builds fresh; later attempts use a *resume* brief that finds
the unfinished workspace, works out from the filesystem what is already done, and
finishes only what is missing. A turn-exhausted night costs minutes, not the day.

Success is **never** inferred from an exit code — only from a URL in the ledger.

## Performance

### `TTS_JOBS` (default `6`), `TTS_THREADS` (default `2`), `MP3_JOBS` (default `6`)
Chapters render concurrently. `TTS_THREADS` caps each worker's internal threads —
without it torch grabs every core per process and the workers thrash instead of scaling.

Rule of thumb: `TTS_JOBS × TTS_THREADS ≈ your logical core count`. On a 12-core machine,
6 × 2. On an 8-core machine, 4 × 2.

This matters for more than speed: before it was parallel, the audio stage ran long enough
to be **killed by a timeout**, always partway through, so some videos could never finish.

## Things not in config.sh

| Want to change | Where |
|---|---|
| Schedule time | re-run `./install.sh --at HH:MM` |
| Workspace root | re-run `./install.sh --root <dir>` |
| Public vs unlisted | `--privacy` in STEP 4 of `daily/run-daily.sh` |
| Morning re-notify time | `launchd/com.dailyaivideo.check.plist.template`, then re-install |
| What gets covered | `beats/*.md` — see [BEATS.md](BEATS.md) |
| Per-beat runtime | `RUNTIME_MIN:` at the top of each beat file |
