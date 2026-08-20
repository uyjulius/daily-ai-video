#!/bin/bash
# Add a topic to the queue and (optionally) start a run immediately.
#
#   new-video.sh "why RAG is losing to long context"        # queue it, run tonight
#   new-video.sh --now "why RAG is losing to long context"  # queue it and start now
#   new-video.sh --list                                     # show the queue
#
# Queued topics always take priority over the nightly auto-pick.

set -uo pipefail
ROOT="${DAILY_VIDEO_ROOT:-$HOME/ai-videos}"
TOPICS="$ROOT/TOPICS.md"
LABEL="com.dailyaivideo.daily-ai-video"

if [ "${1:-}" = "--list" ]; then
  echo "Pending:"; sed -n 's/^- \[ \] */  · /p' "$TOPICS" 2>/dev/null | grep -v '^  · $' || true
  echo; echo "Done:";  sed -n 's/^- \[x\] */  ✓ /p' "$TOPICS" 2>/dev/null | tail -10
  exit 0
fi

NOW=0
if [ "${1:-}" = "--now" ]; then NOW=1; shift; fi

TOPIC="$*"
if [ -z "$TOPIC" ]; then
  echo "usage: new-video.sh [--now] \"topic\"   |   new-video.sh --list" >&2
  exit 1
fi

[ -f "$TOPICS" ] || printf '# Topic queue\n\n## Queue\n\n' > "$TOPICS"
printf -- "- [ ] %s\n" "$TOPIC" >> "$TOPICS"
echo "queued: $TOPIC"

if [ "$NOW" -eq 1 ]; then
  echo "starting a run now (takes roughly an hour; watch the menu bar indicator)"
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
else
  echo "it will be built on the next nightly run at 02:07"
fi
