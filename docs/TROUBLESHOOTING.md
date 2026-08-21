# Troubleshooting

Every failure mode below was hit in production. Several are **silent** — they exit 0 and
look like success, which is why they are worth reading before you need them.

---

## The four silent failures

### 1. `claude -p` hits its turn limit and exits 0

**Symptom:** a run does research, writes the script, renders most of the audio, then
stops. The log says `claude exited: 0`. Nothing published.

**Cause:** headless `claude -p` enforces a default turn limit. This pipeline needs far
more turns than it allows. Hitting the cap prints `Error: Reached max turns (N)` and
**still exits with status 0**, so an exit-code check cannot tell "finished" from
"gave up".

**Fix (already in the runner):**
- `--max-turns 800` is passed explicitly. Do not remove it from `config.sh`.
- **Success is never inferred from the exit code.** The ledger is the only evidence: the
  runner re-checks for a published URL and retries with a *resume* brief if absent.

Verify the flag is real on your install:
```bash
claude --max-turns 1 -p "Run 'echo A' with bash, then run 'echo B', then report both."
# → "Error: Reached max turns (1)" ... and exit code 0
```

### 2. A long shell stage is killed with no error written anywhere

**Symptom:** the audio builder stops mid-run, always around the same point. `tts.log`
ends mid-line. No error, no traceback. Re-running gets a bit further, then stops again.

**Cause:** the stage ran longer than the caller's command timeout and was killed. It is
not a bug in the stage — rendering that same chapter alone succeeds.

**Fix:** make the stage finish quickly. TTS now renders chapters in parallel
(`TTS_JOBS`), turning tens of minutes into ~1–2 minutes.

**General rule: when a long stage vanishes without an error, suspect a timeout on
whoever called it before you go hunting for a bug inside it.**

### 3. macOS TCC blocks launchd from `~/Documents`, `~/Desktop`, `~/Downloads`

**Symptom:** works perfectly when you run it by hand; fails as a scheduled job with
`Operation not permitted` — often exit 126.

**Cause:** a launchd-spawned process gets no access to TCC-protected directories.
Confusingly, *writing* often succeeds while listing and executing fail:

| Operation on `~/Documents` under launchd | Result |
|---|---|
| write a file | OK |
| list a directory | **BLOCKED** |
| execute a script | **BLOCKED** |

**Fix:** keep everything the automated path touches outside those directories.
`install.sh` refuses a `--root` under them. Dotfile dirs in `$HOME` (`~/.claude`,
`~/.config`, `~/.venv-*`) are fine.

**Corollary — the one that wastes an afternoon:** Python puts the current working
directory on `sys.path`, so the import scanner stats it. With a cwd inside `~/Documents`,
**every import fails** with `PermissionError: [Errno 1] Operation not permitted` — the
venv is fine, the cwd is the problem. Don't diagnose a venv from a protected cwd and
conclude the interpreter is broken.

> **Test scheduled jobs with `launchctl kickstart`, never only from your shell.** Your
> shell has permissions launchd does not. This is the single most valuable habit here.

### 4. Changing the voice silently changes video length

Scripts are written to a word budget *up front*, from `WPM`. That rate belongs to the
voice, not the pipeline. Measured on identical text: `af_heart` 148 wpm, `am_liam` 167 wpm
— 12.8% apart. Swap the voice without updating `WPM` and a "30 minute" video comes out at
26½, with nothing erroring.

```bash
$ROOT/.venv-tts/bin/python tools/audition-voices.py --measure <voice> --workspace <finished run>
```

Never measure from a short clip: a single-paragraph sample skips the pauses `tts.py`
inserts at paragraph breaks and reads ~30 wpm too fast.

---

## Loud failures

### "Run now" killed my running job

Fixed, but worth understanding: `launchctl kickstart -k` **kills the running instance
first**. The `-k` is gone from the menu bar, which now hides *Run now* entirely while a
run is live. There is also a PID-based lock (`daily/run.lock`) so two runs cannot
overlap — they share one ledger, one disk budget, and one set of workspaces, and can
purge each other's work. Staleness is judged by whether the PID is alive, because a
SIGKILLed run never runs its cleanup trap.

### Upload says `LOCKED_PRIVATE`

Un-audited Google API projects have uploads forced private. Request an audit at
<https://support.google.com/youtube/contact/yt_api_form>, or upload through the browser
path until it clears.

### Quota exceeded

10,000 units/day, ~1,600 per upload → 6 uploads/day. `VIDEOS_PER_RUN` is clamped to 6.
If you also upload by hand, you will hit it sooner.

### Disk fills up

~1.7GB per video in flight. Intermediates are purged **only after** oEmbed confirms the
upload is public — an unfinished run keeps its assets so it can resume. The runner aborts
below 6GB free and sweeps old workspaces below 12GB.

### The job never fires

- Is the Mac awake? `sudo pmset repeat wakeorpoweron MTWRFSU 02:07:00`
- Is the agent loaded? `./install.sh --check`
- Did something pause it? The menu bar shows `⏸ Schedule PAUSED`.

### A run failed and I want the work back

Nothing is thrown away. The workspace keeps `narration/`, `research/`, `verification.md`,
`writeup.md`, and any rendered audio. Every stage skips completed work, so re-running
resumes rather than rebuilds. The next scheduled run picks it up automatically.

---

## Reading the state

Most of this is visible in the dashboard (menu bar → **Open dashboard…**), which is the
faster route. From a terminal:

```bash
cat $ROOT/NEEDS-ATTENTION.md          # present = last run failed, says why
cat $ROOT/DAILY-LOG.md                # ledger of everything published
tail -f $ROOT/daily/logs/$(date +%F).log
$ROOT/.venv-menubar/bin/python $ROOT/daily/menubar.py --dump   # exactly what the indicator shows
```

`--dump` needs no Accessibility permission and is the fastest way to see indicator state.
