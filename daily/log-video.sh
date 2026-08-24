#!/bin/bash
# Append one line to the ledger, safely, when several runs may be writing at once.
#
# Usage: log-video.sh "YYYY-MM-DD | topic (slug) | url | runtime | claims checked: N, corrected: N, cut: N"
#
# With PARALLEL_VIDEOS>1 there are several agents finishing at unpredictable moments
# and all of them want the same file. mkdir is atomic on every POSIX filesystem, which
# flock is not on macOS, so it is the mutex.
set -uo pipefail
ROOT="${DAILY_VIDEO_ROOT:-$HOME/ai-videos}"
LEDGER="$ROOT/DAILY-LOG.md"
LOCK="$ROOT/daily/.ledger.lock"

[ $# -ge 1 ] || { echo "usage: log-video.sh \"<ledger line>\"" >&2; exit 1; }

for _ in $(seq 1 300); do
  if mkdir "$LOCK" 2>/dev/null; then
    trap 'rmdir "$LOCK" 2>/dev/null' EXIT
    printf '%s\n' "$*" >> "$LEDGER"
    echo "logged: $*"
    exit 0
  fi
  # A holder that died without cleaning up would block everyone; take a stale lock.
  if [ -d "$LOCK" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
    [ "$age" -gt 60 ] && rmdir "$LOCK" 2>/dev/null
  fi
  sleep 0.2
done
echo "could not acquire the ledger lock after 60s" >&2
exit 1
