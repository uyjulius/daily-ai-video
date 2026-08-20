# Setup

Assumes macOS. Budget 30–45 minutes, most of it waiting on the Kokoro install and the
Google Cloud console.

## 1. Prerequisites

```bash
brew install ffmpeg python@3.12 terminal-notifier
# Google Chrome must be installed (slates are rendered headlessly through it)
# Claude Code: https://claude.com/claude-code — install and sign in
claude --version
```

Python **3.12 specifically** — Kokoro does not install cleanly on newer versions.

## 2. Install

```bash
git clone https://github.com/uyjulius/daily-ai-video.git
cd daily-ai-video
./install.sh
```

Options: `--root <dir>` (default `~/ai-videos`), `--at HH:MM` (default `02:07`),
`--check` to verify without changing anything.

**Do not put `--root` under `~/Documents`, `~/Desktop` or `~/Downloads`.** macOS TCC
blocks launchd from those directories and the job will fail with `Operation not
permitted`. The installer refuses.

The installer creates three virtualenvs (Kokoro TTS, the YouTube API client, and PyObjC
for the menu bar), installs the skill into `~/.claude/skills/`, generates the launchd
plists with your paths, and loads them. It is idempotent and never overwrites your
`config.sh` or your beats.

## 3. YouTube credentials

Once, by hand:

1. <https://console.cloud.google.com/> → create or pick a project.
2. **APIs & Services → Library →** enable **YouTube Data API v3**.
3. **OAuth consent screen** → External. Add your own Google account as a **test user**
   (otherwise tokens expire in 7 days).
4. **Credentials → Create credentials → OAuth client ID → Desktop app.** Download the
   JSON to `~/Downloads`.

   It must be a **Desktop** client. Android/iOS exports lack the `client_secret` field
   and will not work.

5. Authorise — a browser window opens; pick the channel identity you intend to publish as:

```bash
~/.venv-ytapi/bin/python ~/.claude/skills/topic-to-youtube/yt_auth.py
```

The refresh token is written to `~/.config/topic-to-youtube/token.json`. **That file is a
credential — it is outside the repo, and it must never be committed.**

### Uploads forced private?

New, un-audited API projects have uploads locked to private. The first upload of a
session uses `--check-lock` and prints `LOCKED_PRIVATE` if so. Request an audit at
<https://support.google.com/youtube/contact/yt_api_form>.

## 4. Let the Mac wake

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 02:07:00     # match your --at, minus a few minutes
pmset -g sched                                        # confirm
```

Without this the job only fires if the Mac happens to be awake.

## 5. Make it yours

`beats/*.md` are placeholders. Edit them, or the pipeline will produce competent videos
about nothing you care about. See [BEATS.md](BEATS.md).

Pick a narrator while you are at it:

```bash
$ROOT/.venv-tts/bin/python tools/audition-voices.py     # writes voice-audition/AUDITION-REEL.wav
```

Set `VOICE` in `daily/config.sh` — **and `WPM` with it**, measured, not guessed. See
[CONFIGURATION.md](CONFIGURATION.md).

## 6. First run

Start with **one** video and check the result before scaling up:

```bash
# in daily/config.sh: VIDEOS_PER_RUN=1
launchctl kickstart gui/$(id -u)/com.dailyaivideo.run
tail -f $ROOT/daily/logs/$(date +%F).log
```

Note there is no `-k`. That flag kills a running instance.

Strongly recommended for the first few: change `--privacy public` to `--privacy unlisted`
in the STEP 4 section of `daily/run-daily.sh`, and watch a couple of videos end to end
before letting it publish publicly unattended.

## 7. Verify

```bash
./install.sh --check
```

Checks config, all three venvs, the YouTube token, and that all three agents are loaded.
