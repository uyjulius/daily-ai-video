#!/usr/bin/env python3
"""Build one chapter's moving background: stills -> Ken Burns -> slate on top.

Usage: make_kenburns.py <project_dir> <chapter-slug>

Reads <project_dir>/backgrounds/<slug>/*.jpg and <project_dir>/slates/<slug>.png
(which must have a transparent background), writes <project_dir>/backgrounds/<slug>.mp4
exactly as long as <project_dir>/mp3/<slug>.mp3.

This is pass 1 of two. The slate is composited HERE, so pass 2
(render_videos.py) sees an ordinary video input and its filter graph — which
carries several hard-won ffmpeg workarounds — needs no restructuring.

zoom/pan are driven by the output frame number 'on' rather than by feeding
'zoom' back into itself; the feedback form drifts and is far harder to reason
about.
"""
import json
import math
import os
import subprocess
import sys

FPS = 24
XFADE = 1.0
ZOOM_MAX = 1.3
LONG_CHAPTER_S = 300


def hold_for(duration_s):
    """Seconds to hold each still.

    Long chapters hold longer so the number of public-domain images they need
    stays obtainable: a 10-minute chapter at 15s would need ~43 images.
    """
    return 25.0 if duration_s > LONG_CHAPTER_S else 15.0


def images_needed(duration_s, hold_s, xfade_s=XFADE):
    """How many stills cover duration_s, given each pair overlaps by xfade_s."""
    if duration_s <= hold_s:
        return 1
    return int(math.ceil((duration_s - xfade_s) / (hold_s - xfade_s)))


def build_filter(n, hold_s, xfade_s, fps):
    """Filter graph: n zoompan segments, crossfaded, with the slate on top.

    Input n is the slate PNG; inputs 0..n-1 are the stills.
    """
    frames = int(round(hold_s * fps))
    inc = (ZOOM_MAX - 1.0) / frames
    parts = []
    for i in range(n):
        mode = i % 3
        if mode == 0:      # slow zoom in, centred
            z = f"min(1.0+{inc:.6f}*on,{ZOOM_MAX})"
            x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        elif mode == 1:    # slow zoom out, centred
            z = f"max({ZOOM_MAX}-{inc:.6f}*on,1.0)"
            x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        else:              # steady zoom, pan left to right
            z = "1.15"
            x, y = f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"
        # Oversample to 2560x1440 first so the 1.3x zoom still resolves detail.
        # force_original_aspect_ratio needs BOTH dimensions; "-2" here would be
        # a contradiction, not a shorthand.
        parts.append(
            f"[{i}:v]scale=2560:1440:force_original_aspect_ratio=increase,"
            f"crop=2560:1440,"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s=1920x1080:fps={fps},"
            f"setsar=1[v{i}]"
        )
    if n == 1:
        chain = "[v0]null[bg]"
    else:
        prev, step = "[v0]", hold_s - xfade_s
        for i in range(1, n):
            offset = step * i
            label = "[bg]" if i == n - 1 else f"[x{i}]"
            parts.append(
                f"{prev}[v{i}]xfade=transition=fade:duration={xfade_s:g}:"
                f"offset={offset:g}{label}"
            )
            prev = label
        chain = None
    if chain:
        parts.append(chain)
    # JPEG stills decode full-range (pix_fmt=yuvj420p, color_range=pc), which
    # this filter graph would otherwise carry straight through to the output.
    # Re-tag alone would be a lie -- the SAMPLE VALUES are still full-range --
    # so rescale the values to limited range here, then tag the encode to
    # match in main()'s ffmpeg command. Without this, a mixed complete.mp4
    # (concat_complete.py stream-copies, so the whole file inherits its
    # FIRST segment's flags) ships still-based segments as limited-range
    # samples mislabelled full-range: crushed blacks, clipped highlights.
    parts.append(f"[bg][{n}:v]overlay=0:0:format=auto,"
                 f"scale=in_range=full:out_range=tv,format=yuv420p[out]")
    return ";".join(parts)


def duration_of(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def credited_stills(project_dir, img_dir, slug):
    """Absolute paths of the stills credits.json says belong to this chapter.

    Composited stills are read from credits.json ONLY -- never a raw
    directory listing -- so "credited" is an enforced precondition, not a
    side-effect a widened re-search (or a file dropped into the directory by
    hand with no licence check at all) can silently defeat. fetch_images.py
    replaces credits.json[slug] wholesale on every run, so a credited file
    missing from disk means the two have drifted out of sync -- a genuine
    error, not a fallback case, so it fails loudly rather than silently
    dropping the entry.

    Returns [] when there is nothing credited for this chapter (missing
    credits.json, or an empty/absent entry for `slug`) -- the caller treats
    that the same as an empty stills directory.
    """
    creds_path = os.path.join(project_dir, "backgrounds", "credits.json")
    if not os.path.exists(creds_path):
        return []
    try:
        with open(creds_path) as fh:
            all_credits = json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise SystemExit(f"{creds_path} could not be read ({exc}) — cannot "
                          f"verify which stills in {img_dir} are credited")
    paths = []
    for entry in all_credits.get(slug, []):
        fname = entry.get("file")
        path = os.path.join(img_dir, fname) if fname else None
        if not fname or not os.path.exists(path):
            raise SystemExit(
                f"{slug}: credits.json lists {fname!r} but it is missing "
                f"from {img_dir} — re-run fetch_images.py for this chapter")
        paths.append(path)
    return paths


def main(project_dir, slug):
    img_dir = os.path.join(project_dir, "backgrounds", slug)
    slate = os.path.join(project_dir, "slates", slug + ".png")
    mp3 = os.path.join(project_dir, "mp3", slug + ".mp3")
    out = os.path.join(project_dir, "backgrounds", slug + ".mp4")

    # Zero stills is a normal outcome, not a failure: fetch_images.py can
    # legitimately keep nothing for a chapter (measured on the README's own
    # example topic, "airline loyalty": 0/8 images kept). That chapter falls
    # back to the still slate on the render_videos.py path instead, so this
    # exits 0 rather than hard-failing the per-chapter run partway through.
    if not os.path.isdir(img_dir):
        print(f"{slug}: no stills at {img_dir} — skipping Ken Burns, this "
              f"chapter falls back to the still slate", file=sys.stderr)
        return
    stills = credited_stills(project_dir, img_dir, slug)
    if not stills:
        print(f"{slug}: no credited stills for this chapter — skipping Ken "
              f"Burns, this chapter falls back to the still slate",
              file=sys.stderr)
        return
    for path in (slate, mp3):
        if not os.path.exists(path):
            raise SystemExit(f"missing {path}")

    duration = duration_of(mp3)
    hold = hold_for(duration)
    want = images_needed(duration, hold)
    if len(stills) < want:
        # Repeat rather than fail: a short chapter with 5 good images beats
        # no motion at all. The repeat is far apart in time.
        print(f"{slug}: {len(stills)} stills for {want} slots — cycling them",
              file=sys.stderr)
        stills = [stills[i % len(stills)] for i in range(want)]
    else:
        stills = stills[:want]

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for path in stills:
        # Deliberately NOT "-loop 1 -t": zoompan emits d frames per INPUT
        # frame, so a looped input would multiply d by every frame it is fed.
        # One still in, d frames out, is the whole point.
        cmd += ["-i", path]
    cmd += ["-loop", "1", "-i", slate]
    cmd += ["-filter_complex", build_filter(len(stills), hold, XFADE, FPS),
            "-map", "[out]", "-t", f"{duration:.3f}",
            # Intermediate: pass 2 re-encodes, so keep this one cheap but clean.
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            # Explicit signalling to match the filter graph's range conversion
            # above. The generic -color_primaries/-color_trc options alone do
            # not reach libx264's VUI on every ffmpeg build (verified by
            # inspecting the encoded SPS with `-bsf:v trace_headers`: without
            # -x264-params they land as "unspecified" even when passed), so
            # -x264-params pins them directly as the authoritative source.
            "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
            "-r", str(FPS), out]
    print(f"{slug}: {len(stills)} stills, hold {hold:g}s -> {duration:.1f}s")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"ffmpeg failed for {slug}")
    print(f"  ok {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
