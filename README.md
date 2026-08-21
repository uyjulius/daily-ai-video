# daily-ai-video

An unattended pipeline that researches a topic, writes a script, **fact-checks every
load-bearing claim against primary sources**, narrates it, renders it to video, and
publishes it to YouTube — on a schedule, while you sleep.

It runs on your own Mac using [Claude Code](https://claude.com/claude-code), local
[Kokoro](https://github.com/hexgrad/kokoro) text-to-speech, and ffmpeg. There is no
server, no subscription beyond your Claude plan, and nothing leaves your machine except
the finished upload.

```
02:07  wake → pick a topic → research primary sources → write narration
       → ADVERSARIAL FACT-CHECK (hard gate) → narrate → render → publish → purge → log
```

---

## The part you should read before anything else

**This publishes to the internet with nobody reviewing it first.** That is the whole
point of the tool and also its entire risk. A language model writing confidently about
current events will get things wrong, and unattended publishing turns a private error
into a public one.

The mitigation is the **adversarial verification gate**, and it is not decoration. Before
anything uploads, the pipeline lists every load-bearing claim, re-checks each against the
*primary* source — the paper, the filing, the terms page, the transcript, not the article
that summarised it — and cuts or corrects whatever does not survive. In production runs
this routinely rejects 5–20% of claims. Real examples from live runs:

- A statistic quoted with **the sign inverted**, which would have published a false
  accusation of misconduct against three named researchers.
- A confidently-worded search result citing findings from a report **that does not
  exist**.
- A membership figure a year out of date, recycled by a summary as current.
- A coefficient pair used as evidence of disagreement that the source cites as the case
  where two datasets **agree**.

Every one of those was caught by the gate, in an unattended run, before publication.
**If you weaken or remove that step, do not run this unattended.** Consider setting
`--privacy unlisted` in the upload call while you build confidence in your own beats.

You are the publisher. You are responsible for what goes out under your name.

---

## The dashboard

Everything below can be driven from a local web dashboard — no terminal, no editing
config files. Click the menu bar icon and choose **Open dashboard…**, or run
`python3 daily/dashboard.py --open`.

It shows what the machine is doing right now and which stage it has reached, the fact-check
record behind every published video, and a setup checklist that names the exact command
for anything still missing. You can queue a topic, rewrite what it covers, change the
narrator, and start a run — all from the page.

It binds to `127.0.0.1` only and requires a token generated at startup, so nothing on the
network and no other site in your browser can reach it.

## What you get

- **~20–35 minute narrated explainers**, chaptered, with slate cards and abstract
  backdrops, rendered to 1080p.
- **A verification record per video** (`verification.md`) — every claim, the primary
  source checked, and the verdict. Published descriptions disclose corrections.
- **A menu bar indicator** showing running / published / failed at a glance, with the
  current stage, queue depth, and one-click access to logs and the topic queue.
- **Failure that is impossible to miss**: a marker file plus a notification, re-announced
  every morning until resolved.
- **A ledger** of everything published, and automatic purging of ~1.7GB of intermediates
  per video once the upload is confirmed public.

## Requirements

| | |
|---|---|
| macOS | Apple Silicon recommended. `/bin/bash` 3.2 is assumed throughout |
| [Claude Code](https://claude.com/claude-code) | the `claude` CLI, signed in |
| Python 3.12 | Kokoro requires it specifically (`brew install python@3.12`) |
| ffmpeg | `brew install ffmpeg` |
| Google Chrome | used headlessly to render slate cards |
| A Google Cloud OAuth *Desktop* client | with YouTube Data API v3 enabled |
| ~10GB free disk | ~1.7GB per video in flight, purged after |
| `terminal-notifier` | optional; `brew install terminal-notifier` |

## Install

```bash
git clone https://github.com/uyjulius/daily-ai-video.git
cd daily-ai-video
./install.sh                      # or: ./install.sh --root ~/videos --at 03:30
```

Then the two things the installer cannot do for you:

```bash
# 1. YouTube credentials (once) — put the Desktop client_secret JSON in ~/Downloads first
~/.venv-ytapi/bin/python ~/.claude/skills/topic-to-youtube/yt_auth.py

# 2. Let the Mac wake for the job (needs your password, once)
sudo pmset repeat wakeorpoweron MTWRFSU 02:07:00
```

Verify at any time — this changes nothing:

```bash
./install.sh --check
```

**Then edit your beats.** `beats/*.md` ship as placeholders and will produce generic
videos until you make them yours. See [docs/BEATS.md](docs/BEATS.md).

## Telling it what to cover

Two mechanisms, and they compose:

**Standing beats** — subjects covered *every* night, one per slot, each with its own
sourcing rules, verification rules, and runtime. A beat is a plain Markdown file:

```
RUNTIME_MIN: 30
---
BEAT: what the conversation in your field is actually saying this week...
WHERE TO LOOK: ...
⚠️ VERIFICATION: ...
```

**A topic queue** for one-offs — `TOPICS.md`, or the menu bar's *Add topic…*, or:

```bash
daily/new-video.sh "why RAG is losing to long context"
daily/new-video.sh --now "..."     # queue it and start immediately
daily/new-video.sh --list
```

Queued topics take priority over that slot's beat. Anything left over waits for tomorrow.
A video that fails leaves its topic unchecked, so it gets retried.

## Configuration

Everything lives in `daily/config.sh` — cadence, narrator voice, retry limits,
parallelism. You should never need to edit `run-daily.sh`. See
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

The one setting people get wrong is `WPM`. Scripts are written to a word budget *up
front*, so the narrator's real speaking rate decides whether a video hits its target
length — and it is a property of the voice, not the pipeline. Changing `VOICE` without
re-measuring `WPM` silently produces videos of the wrong length:

```bash
$ROOT/.venv-tts/bin/python tools/audition-voices.py                  # hear them, measure pitch
$ROOT/.venv-tts/bin/python tools/audition-voices.py --measure am_liam --workspace <a finished run>
```

## What it costs

Compute is local and free. The real costs:

- **Claude usage.** A 30-minute video is a long agent run — research, drafting, and a
  verification pass over dozens of claims. Three videos a night is a lot of tokens.
- **YouTube API quota.** 10,000 units/day by default; an upload costs ~1,600. That caps
  you at **6 uploads/day**, which the runner enforces.
- **Wall clock.** Roughly 45–90 minutes per video end to end, run sequentially.

## Documentation

| | |
|---|---|
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | the non-technical route — running it without a terminal |
| [docs/SETUP.md](docs/SETUP.md) | full install, including the Google Cloud side |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | every setting, and what breaks if it is wrong |
| [docs/BEATS.md](docs/BEATS.md) | writing beats, and the verification rules that belong in them |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how the pieces fit; where the time goes |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | every failure mode hit in production, and the fix |

`docs/TROUBLESHOOTING.md` is worth reading *before* you have a problem. Several of the
failures there are silent — they exit 0 and look like success.

## Credits

- [Kokoro](https://github.com/hexgrad/kokoro) — local TTS (Apache-2.0)
- [Paged.js](https://pagedjs.org/) — bundled in `skill/topic-to-youtube/vendor/` (MIT)
- Built with [Claude Code](https://claude.com/claude-code)

## License

MIT — see [LICENSE](LICENSE).

Licensed for the code. What you publish with it is yours, and so is the responsibility
for it.
