# Architecture

## The pieces

```
launchd (02:07)
  └── daily/run-daily.sh          orchestration: lock, topic selection, retries, purge, ledger
        └── claude -p             one headless agent per video, driven by a generated brief
              └── skill/topic-to-youtube/    the actual pipeline
                    build_audiobook.sh  → Kokoro TTS, parallel, resumable
                    gen_slates.py       → chapter cards (headless Chrome)
                    make_kenburns.py    → motion backdrops where stills exist
                    render_videos.py    → per-chapter mp4
                    concat_complete.py  → final mp4 + chapter timestamps
                    yt_upload.py        → upload + privacy verification

daily/menubar.py        PyObjC status item — state, stage, queue, controls
daily/check-attention.sh  09:00 re-notify while a failure marker exists
```

The runner never does creative work; it decides *what* to build and *whether it worked*.
The agent does the work. The split matters: control flow that must be deterministic
(locking, retries, purge safety, quota limits) lives in bash, not in a prompt.

## Layout

```
$ROOT/                          default ~/ai-videos
├── daily/
│   ├── config.sh               your settings
│   ├── run-daily.sh            orchestrator
│   ├── status.json             machine-readable state for the indicator
│   ├── run.lock                PID lock, single instance
│   └── logs/YYYY-MM-DD.log
├── beats/*.md                  standing subjects
├── TOPICS.md                   one-off queue
├── DAILY-LOG.md                ledger — the only record of success
├── NEEDS-ATTENTION.md          present only when the last run failed
└── <slug>/                     one workspace per video
    ├── research/  narration/  writeup.md  verification.md  project.json
    └── wav/ mp3/ slates/ videos/ backgrounds/   ← purged after publish
```

Credentials live outside: `~/.config/topic-to-youtube/token.json`.

## Order of operations, and why

```
research → narration → VERIFICATION GATE → description → audio → render → PUBLISH → log → writeup
```

Two decisions are load-bearing:

**The verification gate precedes publication and cannot be skipped.** It is the only
thing standing between a confident wrong sentence and your channel.

**Publication precedes prose.** `writeup.md` — a long-form companion document — is
produced *last*, after the video is live. Nothing in the video path reads it. It used to
run before upload and delayed publication by ~95 minutes on a script that had been
finished 13 minutes in.

## Where the time goes

Measured on a real 31-minute video:

| Phase | Duration | Bound by |
|---|---|---|
| Research | ~13 min | model + network |
| Narration | included above | model |
| Verification gate | ~5 min | model + network |
| Description | ~2 min | model |
| Audio (parallel) | ~2 min | CPU |
| Slates + render | ~5 min | CPU |
| Upload | ~10 min | network |

**Roughly 45 minutes**, dominated by the agent's own research and verification. That is
the floor unless you weaken the fact-check, which you should not.

## Design decisions worth knowing

**Success is proven, never assumed.** `claude -p` exits 0 even when it gives up at the
turn limit, so the ledger is the sole evidence of success. Every retry re-reads it.

**Every stage is resumable and skips completed work.** A killed run resumes in minutes
instead of rebuilding. Nothing is purged until oEmbed confirms the upload is public.

**The purge is conditional.** An early version purged unconditionally and destroyed 1.6GB
of finished-but-unpublished work when an agent ran out of turns just before uploading.
Now a workspace is purged only if its slug appears in the ledger against a real URL.

**Failure is loud and persistent.** A marker file plus a notification, re-announced at
09:00 daily until a successful run clears it. A 02:07 notification lands during Sleep
Focus and is easy to miss.

**Two sources of truth for the indicator.** `status.json` gives state; the *stage within
a run* is inferred from which artefacts exist on disk, because the agent is one opaque
call and cannot report its own progress. If `status.json` is stale the indicator falls
back to what the disk shows rather than asserting something false.

## Portability

macOS-specific by design: launchd, TCC, `terminal-notifier`/`osascript`, PyObjC, and
`pmset` for wake scheduling. `/bin/bash` is **3.2** — no `mapfile`, no `wait -n`. The
scripts stay within 3.2, and you should test with `/bin/bash`, not zsh.

Porting to Linux would mean systemd timers, `notify-send`, dropping the menu bar item,
and dropping the TCC workarounds entirely. The pipeline itself would need no changes.
