#!/bin/bash
# Run a command holding the machine-wide render lock.
#
# Usage: with-render-lock.sh <command...>
#
# Slates and video rendering are CPU-bound. With PARALLEL_VIDEOS>1 several videos reach
# those stages at once and simply contend — three ffmpeg pipelines on twelve cores is
# slower in total than three taken in turn, and it starves the model-bound stages of
# the other videos too. Research, drafting and fact-checking are NOT wrapped: those are
# network and model bound, they overlap cleanly, and they are most of what parallelism
# is worth.
set -uo pipefail
ROOT="${DAILY_VIDEO_ROOT:-$HOME/ai-videos}"
LOCK="$ROOT/daily/.render.lock"
mkdir -p "$(dirname "$LOCK")" 2>/dev/null

waited=0
until mkdir "$LOCK" 2>/dev/null; do
  if [ -d "$LOCK" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
    if [ "$age" -gt 5400 ]; then
      echo "[render-lock] taking a stale lock (${age}s old)" >&2
      rmdir "$LOCK" 2>/dev/null
    fi
  fi
  [ "$waited" -eq 0 ] && echo "[render-lock] waiting; another video is rendering..." >&2
  waited=$((waited + 5)); sleep 5
done
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
[ "$waited" -gt 0 ] && echo "[render-lock] acquired after ${waited}s" >&2

"$@"
rc=$?
rmdir "$LOCK" 2>/dev/null; trap - EXIT
exit $rc
