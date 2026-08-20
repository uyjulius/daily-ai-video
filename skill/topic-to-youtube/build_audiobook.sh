#!/bin/bash
# Render every narration chapter to MP3 and stitch the complete audiobook.
#
# Usage: build_audiobook.sh <project_dir> [voice] [speed]
#
# Expects <project_dir>/narration/NN-slug.txt files. Produces:
#   <project_dir>/wav/NN-slug.wav      (Kokoro TTS, resumable — skips existing)
#   <project_dir>/mp3/NN-slug.mp3     (fades + loudnorm + metadata)
#   <project_dir>/mp3/complete.mp3    (all chapters stitched)
#
# TTS venv: uses $TTS_PY if set, else ~/.venv-tts. To create it:
#   python3.12 -m venv ~/.venv-tts && ~/.venv-tts/bin/pip install kokoro soundfile numpy
set -euo pipefail

PROJ="$1"
VOICE="${2:-af_heart}"
SPEED="${3:-1.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TTS_PY="${TTS_PY:-$HOME/.venv-tts/bin/python}"

TITLE=$(python3 -c "import json;print(json.load(open('$PROJ/project.json'))['series_title'])")
mkdir -p "$PROJ/wav" "$PROJ/mp3"

echo "Voice: $VOICE  Speed: $SPEED  Series: $TITLE"

# --- TTS, in parallel -----------------------------------------------------------
# This used to render one chapter at a time on a single core. On a 12-core machine a
# 30-minute video spent ~45 minutes here, which was the single largest block of wall
# clock in the whole pipeline. Chapters are independent, so they go in parallel.
#
# Each worker is capped to $TTS_THREADS threads: torch would otherwise grab every core
# per process and 6 workers x 12 threads thrashes instead of scaling.
# Still resumable — existing wav files are skipped, so a killed run resumes cheaply.
JOBS="${TTS_JOBS:-6}"
export OMP_NUM_THREADS="${TTS_THREADS:-2}"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"
export VECLIB_MAXIMUM_THREADS="$OMP_NUM_THREADS"
export TOKENIZERS_PARALLELISM=false

TODO=()
for f in "$PROJ"/narration/*.txt; do
  base=$(basename "$f" .txt)
  if [ -s "$PROJ/wav/$base.wav" ]; then echo "skip $base"; continue; fi
  TODO[${#TODO[@]}]="$f"
done

if [ "${#TODO[@]}" -gt 0 ]; then
  echo "--- TTS: ${#TODO[@]} chapter(s), up to $JOBS in parallel, $OMP_NUM_THREADS threads each ---"
  TTS_PIDS=""
  for f in "${TODO[@]}"; do
    base=$(basename "$f" .txt)
    echo "tts $base ..."
    "$TTS_PY" "$HERE/tts.py" "$f" "$PROJ/wav/$base.wav" "$VOICE" "$SPEED" 2>/dev/null &
    TTS_PIDS="$TTS_PIDS $!"
    # Portable throttle: /bin/bash on macOS is 3.2, which has no `wait -n`.
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 1; done
  done

  # Collect every worker explicitly. Background failures do not trip `set -e`, so an
  # unchecked wait would let a missing chapter through to the render stage silently.
  TTS_FAIL=0
  for p in $TTS_PIDS; do
    if ! wait "$p"; then TTS_FAIL=$((TTS_FAIL + 1)); fi
  done
  if [ "$TTS_FAIL" -gt 0 ]; then
    echo "ERROR: $TTS_FAIL TTS worker(s) failed" >&2
    exit 1
  fi

  # A worker can exit 0 having written nothing; verify every chapter really landed.
  for f in "${TODO[@]}"; do
    base=$(basename "$f" .txt)
    if [ ! -s "$PROJ/wav/$base.wav" ]; then
      echo "ERROR: $base.wav missing after TTS" >&2
      exit 1
    fi
  done
  echo "--- TTS complete: ${#TODO[@]} chapter(s) ---"
fi

echo "--- encoding chapter MP3s ---"
MP3_PIDS=""
for w in "$PROJ"/wav/*.wav; do
  base=$(basename "$w" .wav)
  [ -s "$PROJ/mp3/$base.mp3" ] && continue
  fade_at=$(python3 -c "import wave;f=wave.open('$w');print(max(0,f.getnframes()/f.getframerate()-0.6))")
  (
    ffmpeg -y -loglevel error -i "$w" \
      -af "afade=t=in:st=0:d=0.35,afade=t=out:st=$fade_at:d=0.6,loudnorm=I=-17:TP=-1.5:LRA=11" \
      -codec:a libmp3lame -b:a 128k -ar 44100 \
      -metadata title="$TITLE - $base" -metadata album="$TITLE" -metadata genre="Audiobook" \
      "$PROJ/mp3/$base.mp3"
    echo "  $base.mp3"
  ) &
  MP3_PIDS="$MP3_PIDS $!"
  while [ "$(jobs -rp | wc -l)" -ge "${MP3_JOBS:-6}" ]; do sleep 1; done
done
MP3_FAIL=0
for p in $MP3_PIDS; do
  if ! wait "$p"; then MP3_FAIL=$((MP3_FAIL + 1)); fi
done
if [ "$MP3_FAIL" -gt 0 ]; then echo "ERROR: $MP3_FAIL mp3 encode(s) failed" >&2; exit 1; fi

echo "--- stitching complete audiobook ---"
CONCAT=$(mktemp)
for m in "$PROJ"/mp3/*.mp3; do
  case "$(basename "$m")" in complete.mp3) continue;; esac
  echo "file '$m'" >> "$CONCAT"
done
ffmpeg -y -loglevel error -f concat -safe 0 -i "$CONCAT" \
  -codec:a libmp3lame -b:a 128k -ar 44100 \
  -metadata title="$TITLE" -metadata album="$TITLE" -metadata genre="Audiobook" \
  "$PROJ/mp3/complete.mp3"
rm -f "$CONCAT"

echo "=== DONE ==="
for m in "$PROJ"/mp3/*.mp3; do
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$m")
  printf "%-40s %6.1f min\n" "$(basename "$m")" "$(python3 -c "print($d/60)")"
done
