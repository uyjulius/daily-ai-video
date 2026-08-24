#!/bin/bash
# Daily AI-topic video runner.
#
# Fired by launchd (com.juliusuy.daily-ai-video) at ~02:07 local.
#
# WHY THIS LIVES IN ~/ai-videos AND NOT ~/Documents:
#   macOS TCC protects ~/Documents, ~/Desktop and ~/Downloads. A launchd-spawned
#   process gets NO access to them — directory listing and execution both fail with
#   "Operation not permitted", even though unix perms look fine. The first scheduled
#   run (18 Aug 2026, 02:07) died with exit 126 for exactly this reason.
#   Everything the automated path touches must therefore live outside those dirs:
#     - this script          -> ~/ai-videos/daily/
#     - the Kokoro TTS venv  -> ~/ai-videos/.venv-tts  (the ~/Documents one is unreachable)
#     - all run workspaces   -> ~/ai-videos/<slug>/
#   Readable from launchd and left in place: ~/.claude/skills, ~/.config/topic-to-youtube,
#   ~/.venv-ytapi  (dotfile dirs in $HOME are not TCC-protected).
#
# Disk is the binding constraint (~1.7GB/run raw), so the purge step is mandatory.

set -uo pipefail

# DAILY_VIDEO_ROOT exists so the failure paths can be exercised in a sandbox under
# launchd without touching the real ledger. Unset in production => identical behaviour.
ROOT="${DAILY_VIDEO_ROOT:-$HOME/ai-videos}"
DAILY="$ROOT/daily"
LOG="$DAILY/logs/$(date +%Y-%m-%d).log"
LEDGER="$ROOT/DAILY-LOG.md"
ATTENTION="$ROOT/NEEDS-ATTENTION.md"
STATUS_FILE="$DAILY/status.json"
TOPICS="$ROOT/TOPICS.md"
EXCLUDE="$ROOT/EXCLUDE.md"
BEATS_DIR="$ROOT/beats"
CONFIG="$DAILY/config.sh"

# Knobs live in config.sh so this script never needs editing to change cadence or voice.
VIDEOS_PER_RUN=1; PARALLEL_VIDEOS=1; VOICE=af_heart; SPEED=1.0; WPM=149; MAX_TURNS=800; MAX_ATTEMPTS=3
TTS_JOBS=6; TTS_THREADS=2; MP3_JOBS=6
# shellcheck source=/dev/null
[ -f "$CONFIG" ] && . "$CONFIG"
RUN_STARTED="$(date '+%Y-%m-%dT%H:%M:%S')"

# Must be set BEFORE auth_ok() runs — under `set -u` an unset reference would abort
# the run and report a false "sign-in expired".
CLAUDE_BIN="${CLAUDE_BIN:-/opt/homebrew/bin/claude}"
MIN_FREE_GB=12

# The skill reads $TTS_PY to locate the Kokoro interpreter; point it at the
# non-TCC-protected venv or every audio build fails under launchd.
export TTS_PY="$ROOT/.venv-tts/bin/python"
# build_audiobook.sh reads these; exported so they reach it through claude's shell.
export TTS_JOBS TTS_THREADS MP3_JOBS
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$DAILY/logs"
exec >>"$LOG" 2>&1
echo "=============================================================="
echo "START $(date '+%Y-%m-%d %H:%M:%S')"

# ------------------------------------------------------------------------- lock
# Two runs overlapped on 21 Aug 2026: a `launchctl kickstart -k` (the menu bar's
# "Run now") killed the 02:07 run mid-video-2 and started a fresh one at 04:20, which
# then re-did a beat that had already published. Two runs also share one ledger, one
# disk budget and one set of workspaces, so they can purge each other's work.
#
# The lock holds a PID, and staleness is decided by whether that PID is alive — a
# SIGKILLed run (which is what -k does) never gets to run its trap, so file existence
# alone would deadlock the job permanently.
LOCK="$DAILY/run.lock"
if [ -f "$LOCK" ]; then
  OTHER="$(cat "$LOCK" 2>/dev/null || true)"
  if [ -n "$OTHER" ] && kill -0 "$OTHER" 2>/dev/null; then
    echo "ALREADY RUNNING as pid $OTHER — this invocation exits without doing anything."
    echo "END $(date '+%Y-%m-%d %H:%M:%S')"
    exit 0
  fi
  echo "stale lock from dead pid ${OTHER:-unknown} — taking it"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

free_gb() { df -g "$HOME" | tail -1 | awk '{print $4}'; }

purge_assets() {
  local ws="$1"
  [ -d "$ws" ] || return 0
  rm -rf "$ws/videos" "$ws/wav" "$ws/mp3" "$ws/slates" \
         "$ws/backgrounds" "$ws/music.wav" "$ws/thumbnail.html" 2>/dev/null
  echo "  purged assets: $ws"
}

# ----------------------------------------------------------------------- beats
# A "beat" is a STANDING assignment — a subject this channel covers every night, with
# its own sourcing rules, its own verification rules and its own runtime. Beats recur;
# the TOPICS.md queue is for one-off ideas and is consumed. Slot N takes a queued topic
# if one is waiting, otherwise beat N.
#
# Each file in beats/ starts with `RUNTIME_MIN: <n>` then `---` then the directive.

beat_files() { ls "$BEATS_DIR"/*.md 2>/dev/null | sort; }

beat_runtime() {  # $1 = beat file
  local v
  v=$(sed -n 's/^RUNTIME_MIN:[[:space:]]*//p' "$1" | head -1)
  echo "${v:-30}"
}

beat_body() {     # $1 = beat file — everything after the first `---`
  sed '1,/^---$/d' "$1"
}

# ------------------------------------------------------------------ topic queue
# TOPICS.md is a human-editable checklist. `- [ ] foo` is pending, `- [x] ...` is done.
# The queue always wins over auto-picking, so a topic Julius actually wants is never
# displaced by whatever happened to be in the news that night.
next_topic() {
  nth_topic 1
}

# The Nth pending topic. Slots must be able to claim DIFFERENT queue entries: with
# PARALLEL_VIDEOS>1 every slot calls this at the same moment, before any of them has
# marked anything done, so "always give me the first one" hands all of them the same
# topic. That is not theoretical — a three-slot test assigned "topic alpha" three
# times and never touched "topic bravo".
nth_topic() {
  [ -f "$TOPICS" ] || return 1
  sed -n 's/^- \[ \] *//p' "$TOPICS" | grep -v '^[[:space:]]*$' | sed -n "${1}p"
}

# Subjects the operator never wants covered. Free text, read by the model rather than
# matched, so "anything about crypto prices" behaves the way it reads.
exclusions() {
  [ -f "$EXCLUDE" ] || return 0
  sed -n 's/^- *//p' "$EXCLUDE" | grep -v '^[[:space:]]*$'
}

# Mark a queued topic done, in place, with the date and URL for the record.
mark_topic_done() {
  TD_TOPIC="$1" TD_URL="$2" TD_FILE="$TOPICS" TD_DATE="$(date +%Y-%m-%d)" \
  /usr/bin/python3 -c '
import os, sys
f = os.environ["TD_FILE"]; topic = os.environ["TD_TOPIC"].strip()
url = os.environ["TD_URL"]; d = os.environ["TD_DATE"]
try:
    lines = open(f).read().splitlines()
except OSError:
    sys.exit(0)
for i, l in enumerate(lines):
    if l.strip().startswith("- [ ]") and l.split("]", 1)[1].strip() == topic:
        lines[i] = "- [x] %s %s — %s" % (d, url, topic)
        break
open(f, "w").write("\n".join(lines) + "\n")
' 2>/dev/null || true
}

# ----------------------------------------------------------------------- status
# Publishes machine-readable state for the menu bar indicator
# (~/ai-videos/daily/menubar.py). The indicator degrades gracefully if this file is
# missing or stale, so a failure to write it must never abort a run — hence `|| true`.
# Uses /usr/bin/python3 for json only; safe because cwd is $ROOT, never ~/Documents
# (a cwd under TCC makes every Python import fail — see RESUME.md).
set_status() {
  ST_STATE="$1" ST_REASON="${2:-}" ST_STARTED="$RUN_STARTED" ST_PID="$$" \
  ST_FILE="$STATUS_FILE" ST_LOG="$LOG" ST_LEDGER="$LEDGER" \
  /usr/bin/python3 -c '
import json, os, datetime, re
p = os.environ["ST_FILE"]
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["state"]      = os.environ["ST_STATE"]
d["reason"]     = os.environ.get("ST_REASON", "")
d["started_at"] = os.environ.get("ST_STARTED", "")
d["pid"]        = int(os.environ.get("ST_PID", "0"))
d["log"]        = os.environ.get("ST_LOG", "")
d["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
if d["state"] != "running":
    d["finished_at"] = d["updated_at"]
# Carry the most recent published video forward so the indicator can show it while idle.
try:
    rows = [l for l in open(os.environ["ST_LEDGER"]) if "youtu.be/" in l]
    if rows:
        last = rows[-1]
        m = re.search(r"https://youtu\.be/\S+", last)
        d["last_url"]   = m.group(0) if m else ""
        d["last_date"]  = last.split("|")[0].strip()
        d["last_topic"] = last.split("|")[1].strip() if last.count("|") >= 1 else ""
except Exception:
    pass
json.dump(d, open(p, "w"), indent=2)
' 2>/dev/null || true
}

# ------------------------------------------------------------------ notification
# WHY: a failed run used to be silent — it appended INCOMPLETE to the ledger and
# nothing else. Nobody found out until they happened to look. Both mechanisms below
# were probed under launchd (not just in a shell) on 18 Aug 2026 and both delivered:
# exit 0 AND a row in Notification Center's db. terminal-notifier is preferred because
# it is its own signed bundle; osascript's notifications are attributed to Script
# Editor and can be blocked by Automation TCC without warning.
notify() {
  local sub="$1" msg="$2"
  # Strip double quotes; they would break the osascript fallback's string literal.
  sub="${sub//\"/}" ; msg="${msg//\"/}"
  if command -v terminal-notifier >/dev/null 2>&1; then
    terminal-notifier -title "Daily AI Video" -subtitle "$sub" -message "$msg" \
      -open "file://$LOG" -group com.juliusuy.daily-ai-video >/dev/null 2>&1 && return 0
  fi
  osascript -e "display notification \"$msg\" with title \"Daily AI Video\" subtitle \"$sub\"" \
    >/dev/null 2>&1
}

# Record a failure durably AND interactively. The marker file is the load-bearing part:
# a notification fired at 02:07 lands during Sleep Focus and can be swiped away unseen.
# The marker survives until the next successful run deletes it, and the 09:00 check
# agent (com.juliusuy.daily-ai-video-check) re-notifies while it exists.
fail() {
  local reason="$1" detail="$2"
  echo "FAILURE: $reason — $detail"
  cat > "$ATTENTION" <<EOM
# Daily AI video — NEEDS ATTENTION

**$(date '+%Y-%m-%d %H:%M')** — the run did not publish.

**Reason:** $reason

$detail

- Log: \`$LOG\`
- Ledger: \`$LEDGER\`
- Full context: \`~/ai-videos/RESUME.md\`

Retry now:
\`\`\`
launchctl kickstart -k "gui/\$(id -u)/com.juliusuy.daily-ai-video"
\`\`\`

Deleted automatically by the next successful run.
EOM
  set_status failed "$reason"
  notify "$reason" "$detail — see NEEDS-ATTENTION.md"
}

# ----------------------------------------------------------------------- auth
# WHY THIS EXISTS (22 Aug 2026): the CLI's OAuth session expired overnight. Every
# attempt died in seconds with "Failed to authenticate: OAuth session expired and
# could not be refreshed" — all three beats, nine attempts, whole run over in 43
# seconds. Retrying is worse than useless against an expired credential, and the
# generic "claude exited 1" in the marker told nobody what to actually do.
#
# So: check once up front, and if an attempt dies this way, stop retrying and say
# plainly that a human has to sign in.
AUTH_STATE="$DAILY/auth.json"

auth_error_in() {  # $1 = file — does this output carry an auth failure?
  grep -qiE "Failed to authenticate|OAuth session expired|Invalid API key|Please run .?claude login" "$1" 2>/dev/null
}

# Record auth state for the dashboard, which must not run its own probe on every
# refresh. Written even on success so the age of the last check is visible.
record_auth() {
  RA_OK="$1" RA_FILE="$AUTH_STATE" /usr/bin/python3 -c '
import json, os, datetime
json.dump({"ok": os.environ["RA_OK"] == "1",
           "checked_at": datetime.datetime.now().isoformat(timespec="seconds")},
          open(os.environ["RA_FILE"], "w"))
' 2>/dev/null || true
}

# One cheap round-trip. Cheaper than discovering the problem after a wasted night.
auth_ok() {
  local out="$DAILY/logs/authcheck.txt"
  "$CLAUDE_BIN" -p "Reply with the single word: ok" --max-turns 1 \
    --output-format text >"$out" 2>&1
  local rc=$?
  if [ $rc -ne 0 ] || auth_error_in "$out"; then
    record_auth 0
    return 1
  fi
  record_auth 1
  return 0
}

# ------------------------------------------------------------- pre-flight checks
echo "disk free before: $(free_gb)G"
echo -n "tts interpreter: "
if [ -x "$TTS_PY" ]; then
  echo "OK ($TTS_PY)"
else
  echo "MISSING — aborting"
  echo "$(date '+%Y-%m-%d') | ABORTED — TTS venv missing at $TTS_PY" >> "$LEDGER"
  fail "TTS venv missing" "No Kokoro interpreter at $TTS_PY — no audio can be built. Rebuild with: python3.12 -m venv ~/ai-videos/.venv-tts && ~/ai-videos/.venv-tts/bin/pip install kokoro soundfile numpy"
  exit 1
fi

if [ "$(free_gb)" -lt "$MIN_FREE_GB" ]; then
  echo "WARN: below ${MIN_FREE_GB}G free — purging assets from all prior workspaces"
  for ws in "$ROOT"/*/; do
    [ -f "$ws/writeup.md" ] && purge_assets "$ws"
  done
  echo "disk free after sweep: $(free_gb)G"
fi

if [ "$(free_gb)" -lt 6 ]; then
  echo "ABORT: under 6G free even after sweep."
  echo "$(date '+%Y-%m-%d') | ABORTED — insufficient disk ($(free_gb)G free)" >> "$LEDGER"
  fail "Out of disk" "Only $(free_gb)G free after purging every prior workspace. A run needs ~1.7G of working space. Free some disk, then retry."
  exit 1
fi

# ------------------------------------------------------------------- the brief
read -r -d '' PROMPT <<'BRIEF'
You are running unattended on a schedule. Nobody will review your output before it goes
public. Work accordingly.

IMPORTANT ENVIRONMENT NOTE: you are running under launchd, which has NO access to
~/Documents, ~/Desktop or ~/Downloads (macOS TCC — listing and executing there fail with
"Operation not permitted"). Therefore:
  - Create the workspace at ~/ai-videos/<slug>/ , NOT ~/Documents/audiobooks/<slug>/.
    This overrides the path in the topic-to-youtube skill's section 0.
  - The Kokoro TTS interpreter is at ~/ai-videos/.venv-tts/bin/python and is already
    exported as $TTS_PY. Do not use the ~/Documents/heymax one; it is unreachable.
  - Everything else (the skill, the YouTube token, ~/.venv-ytapi) is reachable normally.

STEP 1 - THE TOPIC.
@@TOPIC_DIRECTIVE@@

STEP 2 - BUILD IT — AND PUBLISH BEFORE YOU WRITE PROSE.

⚠️ ORDER MATTERS MORE THAN ANYTHING ELSE IN THIS STEP. Measured on the 21 Aug 2026 run:
the narration script was finished 13 minutes in, but the video did not go public for
another 95 minutes, because the run wrote `writeup.md` (a ~10-30k word prose companion)
and polished the description first. Nothing in the video pipeline reads writeup.md —
verified: no audio, slate, render or upload script touches it; only the optional
transcript PDF does. So it must NOT sit between research and publication.

Do it in exactly this order, and do not reorder it to match the skill's narrative:
  a. Research from primary sources.
  b. Write narration/ and project.json. THIS is the script the video uses.
     SPEAK TO SOMEONE. Measured: these scripts use you/your 2-7 times per 1000 words
     against 20-30 in ordinary speech, and some carry 1-4 questions in a whole half-hour.
     It reads as a lecture to an empty room. Count pronouns AND second-person
     imperatives ("Hold that number next to this one" counts). Measured across the
     published set the median is 7.4 per 1000, the best is 21.7 and the worst 3.7 - and
     the loyalty videos score three to five times the markets and discourse ones, which
     is habit rather than subject. TARGET: no video below 12 per 1000, plus about two
     real questions per chapter - with question marks, not imperatives dressed as
     questions. Kokoro ignores punctuation, question marks and capitals
     entirely - verified - so the ONLY emphasis you have is silence, via: paragraph break
     (0.55s), single line break (0.32s), em-dash (0.22s), and **marked span** (0.34s
     either side plus 10% slower, two or three per chapter at most). Recent scripts used
     ZERO em-dashes and averaged 41-word paragraphs, so the voice got a beat only every
     13 seconds. Break far more often than looks right on the page - it is heard, not read.
     TAPER THE CHAPTERS. Every one of the first thirteen videos got HEAVIER as it went —
     second half 7-46% longer per chapter than the first, none tapering. Attention falls
     over half an hour; the load must fall with it. Put the longest chapters at positions
     2-4 and make the final third shorter than the middle. A closing chapter should be
     among the shortest.
     TITLE: under 60 characters where the argument survives it, 70 hard maximum - past
     that it truncates in search and on mobile. Front-load the distinctive words. Do not
     reuse the 'what X actually says' construction; 5 of the first 15 titles did.
     OPEN ON THE FACT, NOT THE DATE. Seven of twelve opened "On the Nth of August, X did
     Y". Lead with the number or the contradiction; date it in the next sentence.
  b2. RUN THE CRAFT CHECK before any audio:
        python3 $SKILL_DIR/check_narration.py <workspace>
     Fix every MISS it reports, then run it again. Rendering first wastes an hour on a
     script you already know is flat. The 23 Aug video failed all six checks.
  c. STEP 3 below — the adversarial verification gate. Still mandatory, still before
     anything is published. Do not weaken it to save time; it is the reason this
     channel is trustworthy.
  d. description.txt — good enough to publish, not polished to death. Two hard rules:
     the FIRST 157 CHARACTERS are all most people see, so spend them on the hook and
     never on corporate scaffolding; and it MUST carry a PRIMARY SOURCES block naming
     every load-bearing figure's document, publisher and retrieval date. Audited: the
     three markets videos carried 0, 1 and 1 sources against 6-12 everywhere else.
  e. A thumbnail — gen_thumbnail.py with a THREE-TO-SIX-WORD phrase, not the title —
     and pass it to the upload with --thumbnail. Without it YouTube picks an
     unreadable frame.
  f. Audio, slates, render. Audio runs in parallel across chapters via $TTS_JOBS;
     just call build_audiobook.sh normally and it handles that itself.
  g. Upload PUBLIC and verify with oEmbed (STEP 4).
  h. Purge (STEP 5) and log (STEP 6).
  i. ONLY NOW, if turns remain, write writeup.md. If you run out of turns here, that is
     a perfectly acceptable outcome — the video is already live and logged. Say so in
     your report rather than treating it as a failure.

Run the /topic-to-youtube skill for the mechanics, at a target of ~@@RUNTIME@@ minutes,
with the workspace path override above.

NARRATOR AND LENGTH BUDGET — both matter, and the second one is easy to get wrong:
  - Voice is @@VOICE@@ at speed @@SPEED@@. Pass BOTH to build_audiobook.sh instead of
    the skill's defaults:  bash $SKILL_DIR/build_audiobook.sh <workspace> @@VOICE@@ @@SPEED@@
  - This voice narrates at @@WPM@@ words per minute, MEASURED, including the pauses
    tts.py inserts at paragraph breaks. That is NOT the 149 figure in the skill's
    SKILL.md, which was measured for a different voice. Budget from @@WPM@@.
  - For the ~@@RUNTIME@@ minute target that is about @@WORDS@@ narrated words. Write to
    that budget up front; drafting long and trimming takes many passes and still overshoots. Follow the skill exactly, including its imagery
verification rule: read backgrounds/credits.json and check file titles actually match the
subject before rendering. Prefer abstract backdrops over photographs of real people — but note that ZERO of
the first seventeen runs fetched any real imagery at all, so every video looks
identical. Abstract is for when the subject IS named living people. For a card's
terms, an index, an outage or an airline estate, fetch the public-domain stills.

STEP 3 - ADVERSARIAL SELF-CHECK. THIS IS A HARD PUBLISH GATE.
Before uploading anything, attack your own narration script:
  a. List every load-bearing factual claim - every figure, date, attribution, causal assertion.
  b. Verify each against the PRIMARY source. Not the secondary article that repeated it.
     The paper, the filing, the company's own docs, the transcript. Secondary sources
     routinely upgrade hedged findings into striking ones, and the striking version travels.
  c. Hunt specifically for:
       - a claim attributed to a study that the study does not actually make
       - a figure whose date has drifted (stale numbers recycled as current)
       - a reported/rumoured event stated as confirmed fact
       - a correlation stated as causation
       - a single-source claim presented as established
  d. Fix or cut everything that does not survive. If a claim is load-bearing and cannot be
     verified, change the thesis rather than keep the claim.
  e. Write results to verification.md in the workspace: each claim, primary source checked,
     verdict (confirmed / corrected / cut).
If a substantial share of claims fail, that means the topic was too thin or too fresh.
Say so in the final report and publish the corrected, shorter version.

STEP 4 - PUBLISH.
Upload PUBLIC via the API path. The description must state the research date and must
label any reported-but-unconfirmed event as reported, not confirmed.

STEP 5 - PURGE. MANDATORY, ONLY AFTER A VERIFIED-PUBLIC UPLOAD.
Confirm the video is genuinely public (oEmbed returns HTTP 200), then delete from the
workspace: videos/ wav/ mp3/ slates/ backgrounds/ music.wav
Keep only: writeup.md research/ narration/ verification.md project.json description.txt
thumbnail.png  (delete thumbnail.html — it is scratch)
Disk is the binding constraint on this whole arrangement. Do not skip this.

STEP 5b - CONSISTENCY SWEEP BEFORE UPLOAD.
Corrections found in STEP 3 must propagate everywhere, not just the narration. Before
uploading, grep description.txt, project.json hooks, and the video title for every figure
you corrected or cut. A run on 18 Aug 2026 corrected "81-page system card" to "eighty page"
in the narration but left "81-page" sitting in the description — the published metadata
would have carried a number its own fact-check had already rejected. Check, then upload.

Also: YouTube caps descriptions at 5000 characters and chapter timestamps are added late.
Budget for them. If over cap, trim opening prose — never the reported-vs-confirmed
disclosures or the primary-source list.

STEP 6 - LOG. Append the ledger line by running:
    bash @@ROOT@@/daily/log-video.sh "<the line>"
Do NOT append to DAILY-LOG.md yourself. Other videos may be finishing at the same
moment, and that helper holds a lock so two writers cannot interleave.
Also COPY the tally out of verification.md rather than recalling it, and make
the ledger line, the description and verification.md agree exactly. One video published
94 in the ledger against 89 in both its own record and its description — harmless there,
since the audience saw the correct figure, but these numbers are the channel's evidence
that the gate is real, so they have to be exact.
The line must be in exactly this format:
YYYY-MM-DD | <topic> | <youtu.be URL> | <runtime> | claims checked: N, corrected: N, cut: N

Report at the end: topic, URL, what the adversarial pass caught, anything degraded or skipped.
BRIEF


# A second brief, used only to finish a run that did not reach upload. Attempt 1 builds
# from scratch; later attempts resume the workspace already on disk instead of throwing
# away a night's research and starting a new topic.
read -r -d '' RESUME_PROMPT <<'BRIEF'
You are RESUMING an unfinished daily video run. A previous attempt tonight built most of
it and stopped before publishing — most likely it hit the turn limit. Your job is to
finish that existing work, NOT to pick a new topic or rebuild from scratch.

ENVIRONMENT: you are under launchd with NO access to ~/Documents, ~/Desktop, ~/Downloads
(macOS TCC). The workspace is at ~/ai-videos/<slug>/ and the Kokoro interpreter is at
$TTS_PY. Do not use any ~/Documents path.

STEP 1 - FIND THE WORKSPACE.
Look in ~/ai-videos/ for the directory containing writeup.md whose slug does NOT appear
in ~/ai-videos/DAILY-LOG.md next to a youtu.be URL. That is tonight's unfinished run.
Read its project.json, verification.md and description.txt to load the context.

STEP 2 - WORK OUT WHAT IS ALREADY DONE, from the filesystem, not from assumptions:
  narration/*.txt  script written        wav/*.wav      audio rendered per chapter
  mp3/*.mp3        audio encoded         slates/        slates generated
  videos/*.mp4     chapter videos        videos/complete.mp4  final cut
Every stage is resumable and skips completed work, so re-running a stage is safe.
Run only the stages that are actually missing, in the order the topic-to-youtube skill
gives. Do not regenerate finished audio — it is the slowest step by far.

STEP 3 - FINISH AND PUBLISH. Publication comes before prose: if writeup.md is missing or
short, IGNORE IT until the video is public and logged. Nothing in the render or upload
path reads it.
For any audio you still have to render, use voice @@VOICE@@ at speed @@SPEED@@:
  bash $SKILL_DIR/build_audiobook.sh <workspace> @@VOICE@@ @@SPEED@@
Existing wav/mp3 files are skipped, so this will not re-render finished chapters.
Complete the remaining stages, then upload PUBLIC via the API path. verification.md
already records the adversarial pass; do not repeat it wholesale, but DO run the STEP 5b
consistency sweep before uploading: grep description.txt, project.json hooks and the
title for any figure the fact-check corrected.

STEP 4 - PURGE, then LOG one line via  bash @@ROOT@@/daily/log-video.sh "<line>"  in the required format:
YYYY-MM-DD | <topic> | <youtu.be URL> | <runtime> | claims checked: N, corrected: N, cut: N
Purge only after oEmbed confirms the video is public.

Report: what you found already done, what you completed, the URL.
BRIEF

# ------------------------------------------------------------------- execution
cd "$ROOT" || exit 1
TODAY="$(date +%Y-%m-%d)"

echo -n "claude auth: "
if auth_ok; then
  echo "OK"
else
  echo "FAILED"
  fail "Claude sign-in expired" \
       "The Claude CLI could not authenticate, so no video can be made. This needs a person: open Terminal and run  claude  then use /login . Nothing was lost; the next run will pick up normally once you are signed in."
  echo "END $(date '+%Y-%m-%d %H:%M:%S')"
  exit 1
fi

# Count, not boolean: with VIDEOS_PER_RUN>1 "something published today" is no longer
# the same question as "this video published". Each video compares against the count
# taken just before it started.
published_count() {
  [ -f "$LEDGER" ] || { echo 0; return; }
  local n
  n=$(grep -c "^$TODAY.*youtu.be/" "$LEDGER" 2>/dev/null || true)
  echo "${n:-0}"
}

# YouTube's default API quota is 10,000 units/day; an upload costs ~1,600. Seven would
# fail on quota partway through, which is a worse outcome than refusing up front.
if [ "$VIDEOS_PER_RUN" -gt 6 ]; then
  echo "WARN: VIDEOS_PER_RUN=$VIDEOS_PER_RUN exceeds the YouTube daily quota ceiling; clamping to 6"
  VIDEOS_PER_RUN=6
fi
[ "$VIDEOS_PER_RUN" -lt 1 ] && VIDEOS_PER_RUN=1

echo "plan: $VIDEOS_PER_RUN video(s) · voice $VOICE @ ${SPEED}x · ${WPM} wpm · turn cap $MAX_TURNS"

# WHY THE LOOP AND THE TURN CAP (bug found 19 Aug 2026):
# The 19 Aug run researched, wrote, fact-checked and rendered 7 of 9 audio segments,
# then stopped dead. Cause: `claude -p` enforces a default turn limit, this pipeline
# needs far more turns than that, and — the part that made it hard to see — hitting the
# limit prints "Error: Reached max turns (N)" and STILL EXITS 0. So the runner could not
# distinguish "finished" from "gave up" by exit code alone.
#   Fix 1: raise the cap explicitly.
#   Fix 2: never trust the exit code. The ledger is the only real evidence of success,
#          so re-invoke with a RESUME brief until a URL is actually logged.
# Attempt 1 builds from scratch; later attempts finish the workspace already on disk,
# so a turn-exhausted night costs minutes, not the whole day.
STATUS=1
MADE=0
FAILED_VIDEOS=0
AUTH_DIED=0

# ---------------------------------------------------------------- one video
# The whole per-video sequence — topic selection, the attempt loop, the ledger and
# queue bookkeeping — as a function, so it can be run in the foreground one at a time
# or in the background several at once.
#
# WHY PARALLEL IS WORTH IT (measured 24 Aug 2026): a three-video sequential run took
# over six hours and had published one video by 08:19. Per video, roughly 45 minutes
# goes on research, writing and fact-checking, which is model and network bound and
# contends with nothing, and roughly 75 minutes on slates and rendering, which is CPU
# bound. Running the videos concurrently overlaps all the model time; the CPU time
# costs about the same in total either way, it is just spread across the same cores.
#
# Two things make it safe:
#   - Every topic is chosen BEFORE anything launches. Parallel agents cannot see one
#     another's choices, so leaving them to pick would let two cover the same story.
#   - The ledger is written through daily/log-video.sh, which holds an mkdir mutex.
run_one_video() {
  local video="$1"
  echo "=== video $video starting $(date '+%H:%M:%S') ==="
  BASE=$(published_count)
  TOPIC_DIRECTIVE=""
  BEAT_FILE=""

  # Queue first, news second. A topic Julius actually asked for should never be
  # displaced by whatever happened to be in the news that night.
  # Runtime defaults to 30 and is overridden per beat below.
  RUNTIME_MIN=30

  # Assigned by assign_topics() before anything launched — never chosen here, or
  # parallel slots would race for the same queue entry.
  QUEUED="$(cat "$DAILY/slot-$video.topic" 2>/dev/null || true)"
  if [ -z "$QUEUED" ]; then
    # No one-off topic waiting — use this slot's standing beat, cycling if there are
    # fewer beats than videos.
    # launchd runs /bin/bash, which on macOS is 3.2 — no mapfile, no readarray.
    # Build the array the portable way; beat filenames are ours and contain no spaces.
    BEATS=()
    for bf in $(beat_files); do BEATS[${#BEATS[@]}]="$bf"; done
    if [ "${#BEATS[@]}" -gt 0 ]; then
      BEAT_IDX="$(cat "$DAILY/slot-$video.beatidx" 2>/dev/null || echo $(( video - 1 )))"
      BEAT_FILE="${BEATS[$(( BEAT_IDX % ${#BEATS[@]} ))]}"
      RUNTIME_MIN="$(beat_runtime "$BEAT_FILE")"
      echo "video $video/$VIDEOS_PER_RUN — beat: $(basename "$BEAT_FILE" .md) (${RUNTIME_MIN} min)"
      TOPIC_DIRECTIVE="$(beat_body "$BEAT_FILE")

Pick ONE specific, concrete story inside this beat — a single argument, not a roundup.
Everything below applies to it."
    fi
  fi

  if [ -n "$QUEUED" ]; then
    echo "video $video/$VIDEOS_PER_RUN — queued topic: $QUEUED"
    TOPIC_DIRECTIVE="Your topic is ALREADY CHOSEN. Do not sweep the news and do not pick
a different one. Build this:

    $QUEUED

Research it properly from primary sources. If it is broad, narrow it yourself to the
single most substantive, falsifiable argument inside it — one topic, one video."
  elif [ -z "${TOPIC_DIRECTIVE:-}" ]; then
    echo "video $video/$VIDEOS_PER_RUN — no queue, no beats: auto-picking from the news"
    TOPIC_DIRECTIVE="Sweep the last 24-48 hours of AI news with WebSearch. Look for the story
with the most substance to argue about: a real disagreement, published data, a strategic
shift, a falsifiable claim. Avoid pure product announcements and funding-round churn
unless you can find a genuine argument underneath. Pick exactly one topic."
  fi

  # Also tell it what is already published today, so a second video in one night does
  # not land on the same story as the first.
  # Recent coverage, not just today's. With three videos a night across three beats,
  # a today-only check lets the same story come back next week; over a fortnight it
  # would come back repeatedly.
  RECENT="$(grep "youtu.be/" "$LEDGER" 2>/dev/null | tail -40 \
            | sed 's/|[^|]*$//' | sed 's/^/    /')"
  if [ -n "$RECENT" ]; then
    TOPIC_DIRECTIVE="$TOPIC_DIRECTIVE

ALREADY PUBLISHED RECENTLY — pick something clearly distinct from every one of these,
and do not re-run an old angle on the same story:
$RECENT"
  fi

  EXCL="$(exclusions | sed 's/^/    - /')"
  if [ -n "$EXCL" ]; then
    TOPIC_DIRECTIVE="$TOPIC_DIRECTIVE

DO NOT COVER ANY OF THE FOLLOWING. These are standing exclusions set by the operator.
If the best story of the day falls under one of them, pick the next best instead — do
not cover it from a different angle to get around the rule:
$EXCL"
  fi

  THIS_PROMPT="${PROMPT/@@TOPIC_DIRECTIVE@@/$TOPIC_DIRECTIVE}"
  WORDS=$(( WPM * RUNTIME_MIN ))
  THIS_PROMPT="${THIS_PROMPT//@@ROOT@@/$ROOT}"
  THIS_PROMPT="${THIS_PROMPT//@@VOICE@@/$VOICE}"
  THIS_PROMPT="${THIS_PROMPT//@@SPEED@@/$SPEED}"
  THIS_PROMPT="${THIS_PROMPT//@@WPM@@/$WPM}"
  THIS_PROMPT="${THIS_PROMPT//@@WORDS@@/$WORDS}"
  THIS_PROMPT="${THIS_PROMPT//@@RUNTIME@@/$RUNTIME_MIN}"
  THIS_RESUME="${RESUME_PROMPT//@@ROOT@@/$ROOT}"
  THIS_RESUME="${THIS_RESUME//@@VOICE@@/$VOICE}"
  THIS_RESUME="${THIS_RESUME//@@SPEED@@/$SPEED}"

  set_status running "video $video/$VIDEOS_PER_RUN"

  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    if [ "$(published_count)" -gt "$BASE" ]; then
      echo "video $video published — no further attempts needed"
      break
    fi

    if [ "$attempt" -eq 1 ]; then
      echo "invoking claude headless (video $video, attempt $attempt/$MAX_ATTEMPTS, fresh build)..."
      BRIEF_TEXT="$THIS_PROMPT"
    else
      echo "invoking claude headless (video $video, attempt $attempt/$MAX_ATTEMPTS, RESUMING unfinished workspace)..."
      BRIEF_TEXT="$THIS_RESUME"
      set_status running "video $video/$VIDEOS_PER_RUN, resuming (attempt $attempt)"
    fi

    ATTEMPT_OUT="$DAILY/logs/attempt-$TODAY-v$video-$attempt.txt"
    caffeinate -dimsu "$CLAUDE_BIN" \
      -p "$BRIEF_TEXT" \
      --max-turns "$MAX_TURNS" \
      --permission-mode bypassPermissions \
      --output-format text 2>&1 | tee "$ATTEMPT_OUT"

    STATUS=${PIPESTATUS[0]}
    echo "claude exited: $STATUS (video $video, attempt $attempt)"

    if grep -q "Reached max turns" "$ATTEMPT_OUT" 2>/dev/null; then
      echo "NOTE: video $video attempt $attempt hit the $MAX_TURNS-turn cap (exits 0 — not a crash)"
    fi

    # Retrying an expired credential just fails faster. Abandon the whole run.
    if auth_error_in "$ATTEMPT_OUT"; then
      echo "AUTH FAILURE mid-run — abandoning remaining attempts and videos"
      record_auth 0
      AUTH_DIED=1
      break
    fi

    if [ "$(published_count)" -gt "$BASE" ]; then
      echo "video $video published on attempt $attempt"
      break
    fi
    echo "video $video attempt $attempt ended without a published URL"
  done

  if [ "$AUTH_DIED" -eq 1 ]; then
    FAILED_VIDEOS=$((FAILED_VIDEOS + 1))
    return 1
  fi

  if [ "$(published_count)" -gt "$BASE" ]; then
    MADE=$((MADE + 1))
    NEW_URL="$(grep "^$TODAY.*youtu.be/" "$LEDGER" 2>/dev/null | tail -1 \
               | grep -oE 'https://youtu\.be/[A-Za-z0-9_-]+' || true)"
    if [ -n "$QUEUED" ]; then
      mark_topic_done "$QUEUED" "$NEW_URL"
      echo "queue: marked done — $QUEUED"
    fi
  else
    FAILED_VIDEOS=$((FAILED_VIDEOS + 1))
    echo "video $video/$VIDEOS_PER_RUN FAILED after $MAX_ATTEMPTS attempts"
    # A queued topic stays unchecked so tomorrow's run picks it up again.
  fi

  echo "=== video $video finished $(date '+%H:%M:%S') ==="
}

# ----------------------------------------------------------- topic assignment
# Decide every slot's subject BEFORE any of them starts. Sequential runs could get
# away with choosing inside the slot, because each finished and marked its topic done
# before the next began. Parallel slots all start at once and would every one of them
# take the first pending queue entry.
assign_topics() {
  local slot=1 qn=1 beat_i=0
  rm -f "$DAILY"/slot-*.topic "$DAILY"/slot-*.beatidx 2>/dev/null
  while [ "$slot" -le "$VIDEOS_PER_RUN" ]; do
    local t
    t="$(nth_topic "$qn" 2>/dev/null || true)"
    if [ -n "$t" ]; then
      printf '%s' "$t" > "$DAILY/slot-$slot.topic"
      echo "  slot $slot <- queued: $t"
      qn=$((qn + 1))
    else
      echo "$beat_i" > "$DAILY/slot-$slot.beatidx"
      echo "  slot $slot <- beat index $beat_i"
      beat_i=$((beat_i + 1))
    fi
    slot=$((slot + 1))
  done
}

echo "assigning topics..."
assign_topics

# ------------------------------------------------------------- dispatch
STATUS=1
MADE=0
FAILED_VIDEOS=0
AUTH_DIED=0

# Never run more at once than videos requested, and never more than 3: beyond that the
# render stages thrash rather than scale, and each video wants ~1.7GB of working space.
[ "$PARALLEL_VIDEOS" -lt 1 ] && PARALLEL_VIDEOS=1
[ "$PARALLEL_VIDEOS" -gt "$VIDEOS_PER_RUN" ] && PARALLEL_VIDEOS="$VIDEOS_PER_RUN"
[ "$PARALLEL_VIDEOS" -gt 3 ] && PARALLEL_VIDEOS=3

if [ "$PARALLEL_VIDEOS" -gt 1 ]; then
  # Split the render budget between the concurrent videos, or three of them will each
  # try to use every core. TTS_JOBS x TTS_THREADS should stay near the core count.
  TTS_JOBS=$(( TTS_JOBS / PARALLEL_VIDEOS )); [ "$TTS_JOBS" -lt 1 ] && TTS_JOBS=1
  MP3_JOBS=$(( MP3_JOBS / PARALLEL_VIDEOS )); [ "$MP3_JOBS" -lt 1 ] && MP3_JOBS=1
  export TTS_JOBS MP3_JOBS
  echo "running $PARALLEL_VIDEOS video(s) concurrently · TTS_JOBS=$TTS_JOBS each"

  PIDS=""
  for video in $(seq 1 "$VIDEOS_PER_RUN"); do
    run_one_video "$video" >>"$DAILY/logs/video-$TODAY-$video.log" 2>&1 &
    PIDS="$PIDS $!"
    # keep at most PARALLEL_VIDEOS in flight
    while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL_VIDEOS" ]; do sleep 5; done
  done
  for pid in $PIDS; do wait "$pid" 2>/dev/null; done
  echo "all video slots finished $(date '+%H:%M:%S')"
  # per-video logs are separate files; fold them into the run log for one record
  for video in $(seq 1 "$VIDEOS_PER_RUN"); do
    LOGP="$DAILY/logs/video-$TODAY-$video.log"
    [ -f "$LOGP" ] && { echo; echo "----- video $video log -----"; cat "$LOGP"; }
  done
  # recount from the ledger, which is the only reliable record with parallel writers
  MADE=$(published_count)
  FAILED_VIDEOS=$(( VIDEOS_PER_RUN - MADE ))
  [ "$FAILED_VIDEOS" -lt 0 ] && FAILED_VIDEOS=0
else
  for video in $(seq 1 "$VIDEOS_PER_RUN"); do
    run_one_video "$video"
  done
fi

echo "run summary: $MADE/$VIDEOS_PER_RUN published, $FAILED_VIDEOS failed"

# ------------------------------------------------- post-run cleanup (CONDITIONAL)
# BUG FIX 18 Aug 2026: this sweep used to run unconditionally, which destroyed a
# finished-but-unpublished run's assets when the agent exited before uploading
# (it ran out of turns mid-verification). Never purge a workspace that has not
# been confirmed published. Regenerating audio+video is ~1h of compute; the text
# deliverables are cheap to keep.
echo "post-run cleanup..."

for ws in "$ROOT"/*/; do
  [ -f "$ws/writeup.md" ] || continue
  slug="$(basename "$ws")"

  # A workspace is safe to purge only if the ledger records a real URL for it.
  if grep -q "youtu.be/" "$LEDGER" 2>/dev/null && grep -q "$slug" "$LEDGER" 2>/dev/null; then
    purge_assets "$ws"
  elif [ -d "$ws/videos" ] || [ -d "$ws/wav" ]; then
    echo "  KEEPING assets in $slug — no published URL in ledger (unfinished run, resumable)"
  fi
done

# If nothing was published today, say so loudly in the log, the ledger, AND to Julius.
# The ledger line alone was the old silent-failure mode: written, and never read.
if [ "$MADE" -eq 0 ]; then
  echo "WARNING: no published URL logged for $TODAY — run did not complete to upload"
  echo "$TODAY | INCOMPLETE — built but not published; assets preserved for resume" >> "$LEDGER"

  if [ "$AUTH_DIED" -eq 1 ]; then
    fail "Claude sign-in expired" \
         "The Claude CLI stopped authenticating partway through, so the run was abandoned. This needs a person: open Terminal, run  claude  then use /login . Work already done was preserved and the next run will resume it."
  elif [ "$STATUS" -ne 0 ]; then
    fail "No video published today" \
         "claude exited $STATUS. Assets for any unfinished workspace were preserved, so a retry can resume rather than rebuild."
  else
    fail "No video published today" \
         "claude exited cleanly but never published — most likely it hit the turn cap. Assets preserved for resume."
  fi
elif [ "$MADE" -lt "$VIDEOS_PER_RUN" ]; then
  # Partial success still loses a video, so it still raises the marker. Silence here
  # would mean asking for 3 and quietly getting 1.
  echo "$TODAY | PARTIAL — $MADE of $VIDEOS_PER_RUN published; assets preserved for the rest" >> "$LEDGER"
  fail "Only $MADE of $VIDEOS_PER_RUN published" \
       "$FAILED_VIDEOS video(s) failed after $MAX_ATTEMPTS attempts each. Any queued topic stays unchecked in TOPICS.md and will be retried tomorrow. Assets preserved for resume."
else
  # Published. Clear any marker left by a previous bad night.
  if [ -f "$ATTENTION" ]; then
    rm -f "$ATTENTION"
    echo "cleared stale NEEDS-ATTENTION.md — today published successfully"
  fi
  set_status idle
fi

echo "disk free after: $(free_gb)G"
echo "END $(date '+%Y-%m-%d %H:%M:%S')"
exit $STATUS
