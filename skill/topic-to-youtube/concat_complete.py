#!/usr/bin/env python3
"""Stitch per-chapter MP4 segments into the single complete video.

Usage: concat_complete.py <project_dir>

Concatenates <project_dir>/videos/<chapter>.mp4 in project.json order into
<project_dir>/videos/complete.mp4 with stream copy (no re-encode — segments
must all come from render_videos.py so codecs/params match). This is how the
default single-video output gets a DIFFERENT topic background per chapter:
render every chapter segment, then concat.
"""
import json
import os
import subprocess
import sys
import tempfile


def dur(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True).stdout.strip())


def segment_paths(project_dir):
    """Absolute paths to every chapter segment, in project.json order.

    Absolute is not cosmetic: these paths are written into an ffmpeg concat
    list file created in the system temp directory, and ffmpeg resolves
    relative entries against THAT directory rather than the caller's cwd.
    A relative project_dir therefore produced a list of paths pointing into
    /var/folders/..., and ffmpeg exited 254 with no usable message.
    """
    project_dir = os.path.abspath(project_dir)
    with open(os.path.join(project_dir, "project.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    vids = [os.path.join(project_dir, "videos", ch["slug"] + ".mp4")
            for ch in cfg["chapters"]]
    missing = [v for v in vids if not os.path.exists(v)]
    if missing:
        raise SystemExit("missing segments: " + ", ".join(missing))
    return vids


def main(project_dir):
    project_dir = os.path.abspath(project_dir)
    cfg = json.load(open(os.path.join(project_dir, "project.json")))
    vids = segment_paths(project_dir)
    out = os.path.join(project_dir, "videos", "complete.mp4")
    lst = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    for v in vids:
        lst.write(f"file '{v}'\n")
    lst.close()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst.name, "-c", "copy", "-movflags", "+faststart", out],
                   check=True)
    os.unlink(lst.name)
    total, parts = dur(out), sum(dur(v) for v in vids)
    print(f"complete.mp4  {total/60:.1f} min (segments sum {parts/60:.1f} min)")
    if abs(total - parts) > 2:
        raise SystemExit("WARNING: concat duration mismatch — inspect before uploading")
    # cumulative timestamps for the YouTube description
    t = 0.0
    for ch, v in zip(cfg["chapters"], vids):
        m, s = divmod(int(t), 60)
        h, m2 = divmod(m, 60)
        stamp = f"{h}:{m2:02d}:{s:02d}" if h else f"{m2}:{s:02d}"
        print(stamp, ch["title"])
        t += dur(v)


if __name__ == "__main__":
    main(sys.argv[1])
