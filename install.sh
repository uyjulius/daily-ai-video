#!/bin/bash
# Installer for the daily AI video pipeline (macOS).
#
#   ./install.sh                 install into ~/ai-videos, job at 02:07
#   ./install.sh --root ~/videos --at 03:30
#   ./install.sh --check         verify an existing install, change nothing
#
# Idempotent: safe to re-run. It never overwrites your config.sh or your beats.

set -uo pipefail

ROOT="$HOME/ai-videos"
HOUR=2; MINUTE=7
CHECK_ONLY=0
SRC="$(cd "$(dirname "$0")" && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --root)  ROOT="${2%/}"; shift 2 ;;
    --at)    HOUR="${2%%:*}"; MINUTE="${2##*:}"; HOUR=$((10#$HOUR)); MINUTE=$((10#$MINUTE)); shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

ok(){ printf "  \033[32m✓\033[0m %s\n" "$1"; }
no(){ printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn(){ printf "  \033[33m!\033[0m %s\n" "$1"; }

# ------------------------------------------------------------------ preflight
echo "Checking prerequisites..."
FAIL=0
need(){ if command -v "$1" >/dev/null 2>&1; then ok "$1"; else no "$1 — $2"; FAIL=1; fi }
need ffmpeg   "brew install ffmpeg"
need ffprobe  "brew install ffmpeg"
need claude   "https://claude.com/claude-code"
need python3  "brew install python@3.12"
command -v terminal-notifier >/dev/null 2>&1 && ok "terminal-notifier" \
  || warn "terminal-notifier not found (brew install terminal-notifier) — falls back to osascript"
[ -d "/Applications/Google Chrome.app" ] && ok "Google Chrome" \
  || { no "Google Chrome — required to render slates"; FAIL=1; }

PY312="$(command -v python3.12 || true)"
[ -n "$PY312" ] && ok "python3.12 ($PY312)" || { no "python3.12 — brew install python@3.12 (Kokoro needs it)"; FAIL=1; }

case "$ROOT" in
  "$HOME"/Documents/*|"$HOME"/Desktop/*|"$HOME"/Downloads/*)
    no "ROOT is under a TCC-protected directory ($ROOT)."
    echo "     launchd jobs cannot list or execute there — see docs/TROUBLESHOOTING.md."
    FAIL=1 ;;
  *) ok "ROOT is outside TCC-protected directories" ;;
esac

[ "$FAIL" -eq 1 ] && { echo; echo "Fix the above and re-run."; exit 1; }

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo; echo "Install state:"
  [ -f "$ROOT/daily/config.sh" ] && ok "config.sh" || no "config.sh missing"
  [ -x "$ROOT/.venv-tts/bin/python" ] && ok "TTS venv" || no "TTS venv missing"
  [ -x "$HOME/.venv-ytapi/bin/python" ] && ok "YouTube API venv" || no "YouTube API venv missing"
  [ -f "$HOME/.config/topic-to-youtube/token.json" ] && ok "YouTube token" || no "YouTube token — run yt_auth.py"
  # An expired CLI session breaks every run and nothing else detects it.
  if claude -p "Reply with the single word: ok" --max-turns 1 --output-format text >/tmp/.authck 2>&1 \
     && ! grep -qiE "Failed to authenticate|OAuth session expired" /tmp/.authck; then
    ok "Claude sign-in"
  else
    no "Claude sign-in EXPIRED — run  claude  then /login"
  fi
  rm -f /tmp/.authck
  for L in run check menubar; do
    launchctl list 2>/dev/null | awk -F'\t' -v l="com.dailyaivideo.$L" '$NF==l{f=1} END{exit !f}' \
      && ok "agent com.dailyaivideo.$L loaded" || no "agent com.dailyaivideo.$L NOT loaded"
  done
  exit 0
fi

# ------------------------------------------------------------------ layout
echo; echo "Installing into $ROOT ..."
mkdir -p "$ROOT/daily/logs" "$ROOT/beats"
cp "$SRC/daily/run-daily.sh" "$SRC/daily/check-attention.sh" "$SRC/daily/new-video.sh" \
   "$SRC/daily/menubar.py" "$SRC/daily/dashboard.py" "$SRC/daily/dashboard.html" "$ROOT/daily/"
chmod +x "$ROOT/daily/"*.sh
ok "scripts"

if [ -f "$ROOT/daily/config.sh" ]; then
  warn "config.sh already exists — left untouched"
else
  cp "$SRC/daily/config.sh.example" "$ROOT/daily/config.sh"; ok "config.sh (from example)"
fi

if [ -n "$(ls -A "$ROOT/beats" 2>/dev/null)" ]; then
  warn "beats/ already populated — left untouched"
else
  cp "$SRC/beats/"*.md "$ROOT/beats/"; ok "example beats (EDIT THESE — they are placeholders)"
fi

[ -f "$ROOT/DAILY-LOG.md" ] || printf '# Daily video ledger\n\nOne line per published video.\n\n' > "$ROOT/DAILY-LOG.md"
[ -f "$ROOT/EXCLUDE.md" ]   || printf '# Do not cover these\n\nOne rule per line, written the way you would say it.\n\n## Rules\n\n' > "$ROOT/EXCLUDE.md"
[ -f "$ROOT/TOPICS.md" ]    || printf '# Topic queue\n\nOne per line as `- [ ] your topic`.\nQueued topics take priority over the standing beats.\n\n## Queue\n\n' > "$ROOT/TOPICS.md"
ok "ledger + topic queue"

# ------------------------------------------------------------------ skill
mkdir -p "$HOME/.claude/skills"
rm -rf "$HOME/.claude/skills/topic-to-youtube"
cp -R "$SRC/skill/topic-to-youtube" "$HOME/.claude/skills/"
ok "skill installed to ~/.claude/skills/topic-to-youtube"

# ------------------------------------------------------------------ venvs
if [ -x "$ROOT/.venv-tts/bin/python" ]; then
  ok "TTS venv exists"
else
  echo "  building TTS venv (Kokoro, a few minutes)..."
  "$PY312" -m venv "$ROOT/.venv-tts" \
    && "$ROOT/.venv-tts/bin/pip" install -q --upgrade pip \
    && "$ROOT/.venv-tts/bin/pip" install -q kokoro soundfile numpy \
    && ok "TTS venv" || { no "TTS venv build failed"; exit 1; }
fi

if [ -x "$HOME/.venv-ytapi/bin/python" ]; then
  ok "YouTube API venv exists"
else
  python3 -m venv "$HOME/.venv-ytapi" \
    && "$HOME/.venv-ytapi/bin/pip" install -q --upgrade pip \
    && "$HOME/.venv-ytapi/bin/pip" install -q google-api-python-client google-auth-oauthlib \
    && ok "YouTube API venv" || { no "YouTube API venv build failed"; exit 1; }
fi

if [ -x "$ROOT/.venv-menubar/bin/python" ]; then
  ok "menu bar venv exists"
else
  python3 -m venv "$ROOT/.venv-menubar" \
    && "$ROOT/.venv-menubar/bin/pip" install -q --upgrade pip \
    && "$ROOT/.venv-menubar/bin/pip" install -q pyobjc-framework-Cocoa \
    && ok "menu bar venv" || warn "menu bar venv failed — indicator will not run"
fi

# ------------------------------------------------------------------ agents
LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
for pair in "run:com.dailyaivideo.run" "check:com.dailyaivideo.check" "menubar:com.dailyaivideo.menubar"; do
  name="${pair%%:*}"; label="${pair##*:}"
  sed -e "s|__ROOT__|$ROOT|g" -e "s|__HOUR__|$HOUR|g" -e "s|__MINUTE__|$MINUTE|g" \
      "$SRC/launchd/$label.plist.template" > "$LA/$label.plist"
  launchctl unload "$LA/$label.plist" 2>/dev/null
  launchctl load   "$LA/$label.plist" 2>/dev/null && ok "agent $label" || warn "agent $label failed to load"
done

# ------------------------------------------------------------------ next steps
cat <<NEXT

Installed.

  ▸ Everything below can also be done from the dashboard, which is the easier route:
        click the menu bar icon → "Open dashboard…"
    or from here:
        python3 $ROOT/daily/dashboard.py --open

Two things still need you:

  1. YouTube credentials (once):
       Create an OAuth *Desktop* client in Google Cloud Console, enable the
       YouTube Data API v3, download the client_secret JSON to ~/Downloads, then:
         ~/.venv-ytapi/bin/python ~/.claude/skills/topic-to-youtube/yt_auth.py

  2. Let the Mac wake for the job (needs your password, once):
       sudo pmset repeat wakeorpoweron MTWRFSU $(printf '%02d:%02d:00' "$HOUR" "$MINUTE")

The dashboard walks you through both, and shows a tick against each once it is done.

Then EDIT YOUR BEATS — $ROOT/beats/*.md ship as placeholders and will produce
generic videos until you make them yours. See docs/BEATS.md.

Verify any time with:  ./install.sh --check --root $ROOT
Run one now with:      launchctl kickstart gui/\$(id -u)/com.dailyaivideo.run
NEXT
