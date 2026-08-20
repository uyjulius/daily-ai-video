#!/usr/bin/env python3
"""Render audiobook chapters into YouTube-ready MP4s: slate + live waveform
in the chapter's accent ink + progress bar.

Usage: render_videos.py <project_dir> [slug ...]

Reads <project_dir>/project.json, <project_dir>/mp3/, <project_dir>/slates/;
writes <project_dir>/videos/. Requires gen_slates.py to have run first.

IMPORTANT recipe note: showwaves' cline mode mangles direct hex colors (renders
purple). Render the wave WHITE and tint with colorchannelmixer. The progress
bar must be an overlay slide, not a drawbox width expression ('t' is NAN there).
"""
import json
import os
import subprocess
import sys


# Long stitches justify a slow, high-CRF encode — it roughly halves a multi-hour
# file. Short videos do not: they would pay the slow preset for lower quality.
# Keyed off duration, not slug, because "complete" is only long at full length.
LONG_FORM_SECONDS = 3600


def encode_settings(duration_s):
    """Return (crf, preset) for a video of this duration."""
    if duration_s > LONG_FORM_SECONDS:
        return "27", "slow"
    return "23", "veryfast"


# Every segment must carry identical colour signalling or concat_complete.py's
# stream copy refuses to join them -- a video mixing Ken Burns chapters with
# looped-still chapters produced tv/bt709 and unknown/unknown segments and
# failed outright. These values match make_kenburns.py exactly; changing one
# without the other reintroduces the failure.
#
# The -x264-params duplication is deliberate: on ffmpeg 8.1.1 the bare
# -color_primaries/-color_trc flags do not reach libx264's VUI (verified with
# -bsf:v trace_headers), so the same values are passed both ways.
COLOUR_ARGS = [
    "-color_range", "tv",
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
]


def probe_duration(path):
    """ffprobe a media file's duration in seconds, or None on any failure.

    Guarded so a probe failure (missing ffprobe, corrupt file, IO error)
    can never crash the render -- the staleness warning below is
    best-effort, not load-bearing.
    """
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            return None
        return float(res.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def stale_motion_warning(slug, motion_duration_s, chapter_duration_s, threshold_s=0.5):
    """Message to print when a motion background is stale, or None when it's fine.

    Pure (no I/O) so it is unit-testable without ffmpeg. `overlay`'s default
    eof_action=repeat holds a motion background's LAST FRAME once it runs
    out, so a stale (too-short) Ken Burns MP4 -- e.g. narration re-recorded
    longer without re-running make_kenburns.py -- freezes the picture for
    the remainder of the chapter with no error and exit 0 (measured: 15 of
    25 seconds frozen, progress bar still sweeping).
    """
    if motion_duration_s is None:
        return None
    shortfall = chapter_duration_s - motion_duration_s
    if shortfall <= threshold_s:
        return None
    return (f"WARNING: {slug}: motion background is {motion_duration_s:.1f}s "
            f"but narration is {chapter_duration_s:.1f}s -- the picture will "
            f"freeze for the last {shortfall:.1f}s (re-run make_kenburns.py "
            f"for this chapter)")


def base_input_args(project_dir, slug, slate):
    """ffmpeg input arguments for the video base layer.

    A chapter with a Ken Burns background already has its slate composited in
    by make_kenburns.py, so the base is that video. Otherwise it is the slate
    still, looped. A video input must not get -loop/-framerate.
    """
    motion = os.path.join(project_dir, "backgrounds", slug + ".mp4")
    if os.path.exists(motion):
        return ["-i", motion]
    return ["-loop", "1", "-framerate", "24", "-i", slate]


def main(project_dir, only):
    cfg = json.load(open(os.path.join(project_dir, "project.json")))
    durations = json.load(open(os.path.join(project_dir, "slates", "durations.json")))
    out_dir = os.path.join(project_dir, "videos")
    os.makedirs(out_dir, exist_ok=True)
    entries = list(cfg["chapters"])
    if cfg.get("complete"):
        entries.append({**cfg["complete"], "slug": "complete"})
    music = cfg.get("music")
    music_path = os.path.join(project_dir, music) if music else None
    music_gain = float(cfg.get("music_gain_db", -26))
    for ch in entries:
        slug = ch["slug"]
        if only and slug not in only:
            continue
        accent = ch["accent"].lstrip("#")
        dur = durations[slug]
        mp3 = os.path.join(project_dir, "mp3", ch.get("mp3", slug + ".mp3"))
        slate = os.path.join(project_dir, "slates", slug + ".png")
        out = os.path.join(out_dir, slug + ".mp4")
        motion = os.path.join(project_dir, "backgrounds", slug + ".mp4")
        if os.path.exists(motion):
            warning = stale_motion_warning(slug, probe_duration(motion), dur)
            if warning:
                print(warning, file=sys.stderr)
        r, g, b = (int(accent[i:i + 2], 16) / 255 for i in (0, 2, 4))
        with_music = bool(music_path and os.path.exists(music_path))
        fc = (
            (f"[1:a]asplit=2[a_wave][a_mix];" if with_music else "") +
            f"[{'a_wave' if with_music else '1:a'}]aformat=channel_layouts=mono,"
            f"showwaves=s=1728x220:mode=cline:rate=24:scale=cbrt:colors=white,"
            f"format=rgba,colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f}[w];"
            f"color=c=0x{accent}:s=1920x8:r=24[pb];"
            f"[0:v][w]overlay=96:828:format=auto,"
            f"drawbox=x=0:y=ih-8:w=iw:h=8:color=0xFFFFFF@0.10:t=fill[base];"
            f"[base][pb]overlay=x='-main_w+main_w*t/{dur:.3f}':y=main_h-8:format=auto,"
            f"format=yuv420p[v]"
        )
        if with_music:
            # music bed: loop, drop to bed level, duck under the voice, mix
            fc += (
                f";[2:a]volume={music_gain}dB,aformat=sample_rates=44100:channel_layouts=stereo[bed];"
                f"[a_mix]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[voice_sc][voice_mix];"
                f"[bed][voice_sc]sidechaincompress=threshold=0.02:ratio=6:attack=250:release=1200[duck];"
                f"[voice_mix][duck]amix=inputs=2:duration=first:dropout_transition=3:normalize=0,"
                f"alimiter=limit=0.95[aout]"
            )
            amap = "[aout]"
        else:
            amap = "1:a"
        crf, preset = encode_settings(dur)
        cmd = (["ffmpeg", "-y", "-loglevel", "error"]
               + base_input_args(project_dir, slug, slate)
               + ["-i", mp3])
        if amap == "[aout]":
            cmd += ["-stream_loop", "-1", "-i", music_path]
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap,
                "-c:v", "libx264", "-preset", preset, "-tune", "stillimage", "-crf", crf,
                *COLOUR_ARGS,
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                "-movflags", "+faststart", "-shortest", out]
        print(f"rendering {slug} ({dur:.0f}s)...", flush=True)
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stderr[-2000:])
            sys.exit(1)
        print(f"  ok {out} {os.path.getsize(out)/1e6:.1f} MB", flush=True)
    print("all done")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
