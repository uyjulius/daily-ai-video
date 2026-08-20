#!/bin/bash
# Morning re-check for the daily AI video job.
#
# WHY THIS EXISTS: run-daily.sh fires its failure notification at ~02:07-05:00, which
# lands while the Mac is in Sleep Focus. It is delivered (verified against Notification
# Center's db), but it is silent and easy to swipe away with the night's other noise.
# This agent re-announces at 09:00 as long as $ROOT/NEEDS-ATTENTION.md exists,
# so a broken night cannot pass unnoticed. A successful run deletes the marker, and
# this becomes a no-op.
#
# Lives outside ~/Documents — see docs/TROUBLESHOOTING.md for the TCC reason.

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ROOT="${DAILY_VIDEO_ROOT:-$HOME/ai-videos}"
ATTENTION="$ROOT/NEEDS-ATTENTION.md"
LOG="$ROOT/daily/logs/$(date +%Y-%m-%d).log"

[ -f "$ATTENTION" ] || exit 0

# Pull the recorded reason out of the marker so the reminder is specific, not generic.
REASON="$(grep -m1 '^\*\*Reason:\*\*' "$ATTENTION" | sed 's/^\*\*Reason:\*\* *//')"
WHEN="$(grep -m1 '^\*\*20' "$ATTENTION" | sed 's/\*\*//g; s/ — .*//')"
[ -n "$REASON" ] || REASON="unknown failure"

MSG="No video published ($WHEN). Reason: $REASON. Open NEEDS-ATTENTION.md to resume."

if command -v terminal-notifier >/dev/null 2>&1; then
  terminal-notifier -title "Daily AI Video — still unresolved" \
    -subtitle "$REASON" -message "$MSG" \
    -open "file://$ATTENTION" -group com.dailyaivideo.daily-ai-video-check >/dev/null 2>&1
else
  osascript -e "display notification \"${MSG//\"/}\" with title \"Daily AI Video — still unresolved\"" >/dev/null 2>&1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') morning check: NEEDS-ATTENTION present — re-notified ($REASON)" >> "$LOG"
