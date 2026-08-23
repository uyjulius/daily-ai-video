#!/bin/bash
# Add a topic to the queue and (optionally) start a run immediately.
#
#   new-video.sh "why RAG is losing to long context"        # queue it, run tonight
#   new-video.sh --now "why RAG is losing to long context"  # queue it and start now
#   new-video.sh --list                                     # show the queue
#   new-video.sh --drop "why RAG"                           # remove a queued topic
#   new-video.sh --never "anything about crypto prices"     # never cover this again
#   new-video.sh --allow "anything about crypto prices"     # undo a --never
#
# Queued topics always take priority over the nightly auto-pick.

set -uo pipefail
ROOT="$HOME/ai-videos"
TOPICS="$ROOT/TOPICS.md"
EXCLUDE="$ROOT/EXCLUDE.md"
LABEL="com.juliusuy.daily-ai-video"

if [ "${1:-}" = "--drop" ]; then
  shift; want="$*"
  [ -f "$TOPICS" ] || { echo "no queue yet" >&2; exit 1; }
  # substring match, so you do not have to retype the whole thing
  if grep -qiF -- "$want" "$TOPICS"; then
    grep -viF -- "- [ ] $want" "$TOPICS" > "$TOPICS.tmp" 2>/dev/null || true
    awk -v w="$want" 'tolower($0) ~ tolower("^- \\[ \\].*" w) {next} {print}' "$TOPICS" > "$TOPICS.tmp"
    mv "$TOPICS.tmp" "$TOPICS"
    echo "dropped from the queue: $want"
  else
    echo "nothing queued matching: $want" >&2; exit 1
  fi
  exit 0
fi

if [ "${1:-}" = "--never" ]; then
  shift; rule="$*"
  [ -n "$rule" ] || { echo "usage: new-video.sh --never \"a subject\"" >&2; exit 1; }
  [ -f "$EXCLUDE" ] || printf '# Do not cover these\n\n## Rules\n\n' > "$EXCLUDE"
  printf -- "- %s\n" "$rule" >> "$EXCLUDE"
  echo "will not cover: $rule"
  exit 0
fi

if [ "${1:-}" = "--allow" ]; then
  shift; rule="$*"
  [ -f "$EXCLUDE" ] || { echo "nothing excluded yet" >&2; exit 1; }
  awk -v w="$rule" 'tolower($0) ~ tolower("^- .*" w) {next} {print}' "$EXCLUDE" > "$EXCLUDE.tmp"
  mv "$EXCLUDE.tmp" "$EXCLUDE"
  echo "allowed again: $rule"
  exit 0
fi

if [ "${1:-}" = "--list" ]; then
  echo "Pending:"; sed -n 's/^- \[ \] */  · /p' "$TOPICS" 2>/dev/null | grep -v '^  · $' || true
  echo; echo "Done:";  sed -n 's/^- \[x\] */  ✓ /p' "$TOPICS" 2>/dev/null | tail -10
  echo; echo "Never cover:"; sed -n 's/^- */  ✗ /p' "$EXCLUDE" 2>/dev/null | grep -v '^  ✗ $' || true
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
