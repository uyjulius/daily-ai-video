#!/usr/bin/env python3
"""Render 1920x1080 title slates for an audiobook video series.

Usage: gen_slates.py <project_dir>

Reads <project_dir>/project.json (see SKILL.md for the schema) and the chapter
MP3s in <project_dir>/mp3/, writes slates to <project_dir>/slates/.

Design system: banknote x departure-board. Didot display, Avenir Next labels,
Menlo ledger figures. Per-chapter accent ink. The bottom 240px stays quiet as
the stage for the ffmpeg waveform + progress bar.
"""
import html
import json
import os
import subprocess
import sys

CHROME = os.environ.get("CHROME_BIN",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def wants_transparent(project_dir, slug):
    """True when this chapter has stills for a moving background.

    Keyed off the stills directory rather than backgrounds/<slug>.mp4, because
    slates are rendered before that video is built.
    """
    d = os.path.join(project_dir, "backgrounds", slug)
    if not os.path.isdir(d):
        return False
    return any(f.lower().endswith(IMAGE_SUFFIXES) for f in os.listdir(d))


def slate_layers(transparent, bg):
    """Decide a slate's background layers, body background, and file:// URL.

    transparent: from wants_transparent() -- True when a moving background
        will be composited over this slate later by make_kenburns.py, so it
        must carry only the scrim and the text, over transparency. This
        takes priority over `bg` no matter what background was resolved.
    bg: an absolute path to an existing background image, or a falsy value
        if there is none. Callers do the filesystem check; this function
        does no I/O, so it is safe (and fast) to unit test directly.

    Returns (bg_layers, body_bg, bg_url). This is the one place that
    decides scrim-only vs bg+scrim vs rosette-fallback, so the code path
    that renders and the code path that gets tested are the same function
    rather than two things that merely happen to agree.
    """
    if transparent:
        # The rosette fallback below is for "no background configured at
        # all" -- the wrong layer here, since make_kenburns.py composites
        # this slate onto moving footage as-is and depends on the scrim
        # (not a rosette) for text legibility. And body's own opaque paint
        # would hide the Chrome --default-background-color flag entirely,
        # so body_bg must go transparent too.
        return '<div class="scrim"></div>', "transparent", ""
    if bg:
        return '<div class="bg"></div><div class="scrim"></div>', "#0B1118", "file://" + bg
    return '<div class="rosette"></div><div class="rosette2"></div>', "#0B1118", ""


GRAIN = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'>"
         "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/>"
         "<feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.05 0'/></filter>"
         "<rect width='240' height='240' filter='url(%23n)'/></svg>")

TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:1920px; height:1080px; overflow:hidden; }}
  body {{ background:{body_bg}; position:relative; font-family:'Avenir Next',sans-serif; color:#E8E4DA; }}
  .bg {{ position:absolute; inset:0; background-image:url("{background}");
    background-size:cover; background-position:center; }}
  .scrim {{ position:absolute; inset:0;
    background:linear-gradient(100deg, #0B1118f5 0%, #0B1118e6 42%, #0B111880 72%, #0B111855 100%),
               linear-gradient(0deg, #0B1118cc 0%, transparent 30%); }}
  .rosette {{ position:absolute; right:-560px; top:-460px; width:1700px; height:1700px; border-radius:50%;
    background:repeating-radial-gradient(circle at center, {accent}12 0px, {accent}12 1.5px, transparent 1.5px, transparent 17px);
    -webkit-mask-image:radial-gradient(circle at center, black 30%, transparent 71%); }}
  .rosette2 {{ position:absolute; right:-260px; top:-160px; width:1100px; height:1100px; border-radius:50%;
    background:repeating-radial-gradient(circle at center, {accent}1a 0px, {accent}1a 1px, transparent 1px, transparent 9px);
    -webkit-mask-image:radial-gradient(circle at center, black 25%, transparent 66%); }}
  .grain {{ position:absolute; inset:0; background-image:url("{grain}"); opacity:.5; }}
  .stage {{ position:absolute; left:0; right:0; bottom:0; height:240px;
    background:linear-gradient(180deg, transparent, #05080Ccc 70%, #05080C); }}
  .rail {{ position:absolute; top:64px; left:96px; right:96px; display:flex; justify-content:space-between;
    align-items:baseline; border-bottom:1px solid #E8E4DA26; padding-bottom:22px; }}
  .masthead {{ font-family:Didot,serif; font-size:30px; letter-spacing:.02em; color:#E8E4DA; }}
  .masthead em {{ font-style:italic; color:{accent}; }}
  .rail .no {{ font-family:Menlo,monospace; font-size:17px; letter-spacing:.34em; color:#8B93A0; }}
  .main {{ position:absolute; left:96px; top:224px; right:120px; display:flex; gap:84px; align-items:flex-start; }}
  .denom {{ position:relative; flex:0 0 auto; margin-top:6px; }}
  .denom .big {{ font-family:Didot,serif; font-size:430px; line-height:.82; font-weight:700; color:transparent;
    background:repeating-linear-gradient(176deg, {accent} 0 2.5px, #0B1118 2.5px 4.4px);
    -webkit-background-clip:text; background-clip:text; }}
  .denom .ghost {{ position:absolute; inset:0; font-family:Didot,serif; font-size:430px; line-height:.82;
    font-weight:700; color:transparent; -webkit-text-stroke:2px {accent}66; }}
  .denom .unit {{ font-family:Menlo,monospace; font-size:15px; letter-spacing:.42em; color:#8B93A0;
    margin-top:26px; text-align:center; }}
  .text {{ flex:1; min-width:0; padding-top:18px; }}
  .eyebrow {{ font-size:21px; font-weight:600; letter-spacing:.46em; text-transform:uppercase;
    color:{accent}; margin-bottom:26px; }}
  .title {{ font-family:Didot,serif; font-weight:700; font-size:{title_size}px; line-height:1.04;
    color:#F2EEE4; max-width:1050px; margin-bottom:38px; text-wrap:balance; }}
  .hook {{ font-family:Didot,serif; font-style:italic; font-size:44px; line-height:1.3; color:{accent};
    max-width:900px; text-wrap:balance; }}
  .hook::before {{ content:""; display:block; width:120px; height:3px; background:{accent}; margin-bottom:30px; }}
  .strip {{ position:absolute; left:96px; right:96px; bottom:252px; display:flex; gap:56px; align-items:baseline;
    font-family:Menlo,monospace; font-size:16px; letter-spacing:.24em; color:#77808E;
    border-top:1px solid #E8E4DA1f; padding-top:20px; }}
  .strip b {{ color:#BFC6D0; font-weight:400; }}
</style></head><body>
  {bg_layers}
  <div class="grain"></div>
  <div class="stage"></div>
  <div class="rail">
    <div class="masthead">{masthead} &mdash; <em>{masthead_rest}</em></div>
    <div class="no">{ledger}</div>
  </div>
  <div class="main">
    <div class="denom"><div class="big">{numeral}</div><div class="ghost">{numeral}</div>
      <div class="unit">{unit}</div></div>
    <div class="text">
      <div class="eyebrow">{eyebrow}</div>
      <div class="title">{title}</div>
      <div class="hook">{hook}</div>
    </div>
  </div>
  <div class="strip">
    <span>RUNTIME&nbsp;<b>{runtime}</b></span>
    <span>SOURCE&nbsp;<b>PUBLIC RECORD</b></span>
    <span>RESEARCH&nbsp;<b>{research}</b></span>
    <span>NARRATION&nbsp;<b>AI &mdash; UNAFFILIATED</b></span>
  </div>
</body></html>"""


def duration(path):
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True).stdout.strip()
    s = int(float(d))
    return (f"{s//60:02d}:{s%60:02d}" if s < 3600 else f"{s//3600}:{(s%3600)//60:02d}:{s%60:02d}"), float(d)


def main(project_dir):
    # Pre-existing bug fix, unrelated to transparency: a relative project_dir
    # produced an invalid `file://{hpath}` URL below, which Chrome silently
    # replaced with its own (opaque) error page instead of the slate.
    project_dir = os.path.abspath(project_dir)
    cfg = json.load(open(os.path.join(project_dir, "project.json")))
    out = os.path.join(project_dir, "slates")
    os.makedirs(out, exist_ok=True)
    entries = list(cfg["chapters"])
    if cfg.get("complete"):
        entries.append({**cfg["complete"], "slug": "complete"})
    n_chapters = max([int(c["numeral"]) for c in cfg["chapters"] if c["numeral"].isdigit()]
                     + [len(cfg["chapters"])])
    durations = {}
    for ch in entries:
        slug = ch["slug"]
        mp3 = os.path.join(project_dir, "mp3", ch.get("mp3", slug + ".mp3"))
        runtime, secs = duration(mp3)
        durations[slug] = secs
        if slug == "complete":
            # Overridable: "AUDIOBOOK" is wrong on a nine-minute explainer,
            # which is the default length now.
            ledger, unit = ch.get("ledger", "AUDIOBOOK · COMPLETE"), ch.get("unit", "MINUTES")
        else:
            ledger, unit = f"LEDGER {ch['numeral']} / {n_chapters}", "CHAPTER"
        title_size = 108 if len(ch["title"]) < 26 else (88 if len(ch["title"]) < 40 else 76)
        bg = ch.get("background") or cfg.get("background")
        # A moving background is composited later by make_kenburns.py, so this
        # slate must carry only the scrim and the text, over transparency.
        transparent = wants_transparent(project_dir, slug)
        bg_path = os.path.join(project_dir, bg) if bg and not transparent else None
        resolved_bg = os.path.abspath(bg_path) if bg_path and os.path.exists(bg_path) else None
        if bg and not transparent and not resolved_bg:
            # Configured but missing. Falling back silently ships a video
            # with no artwork and no clue why — say so on stderr.
            print(f"WARNING: {slug}: background {bg!r} not found, "
                  f"using rosette fallback", file=sys.stderr)
        bg_layers, body_bg, bg_url = slate_layers(transparent, resolved_bg)
        page = TEMPLATE.format(
            background=bg_url, bg_layers=bg_layers, body_bg=body_bg,
            accent=ch["accent"], grain=GRAIN, ledger=ledger, numeral=ch["numeral"], unit=unit,
            eyebrow=html.escape(ch["eyebrow"]).upper(), title=html.escape(ch["title"]),
            hook=html.escape(ch["hook"]), runtime=runtime, title_size=title_size,
            masthead=html.escape(cfg["masthead"]), masthead_rest=html.escape(cfg["masthead_rest"]),
            research=html.escape(cfg.get("research_stamp", "")))
        hpath = os.path.join(out, slug + ".html")
        with open(hpath, "w") as f:
            f.write(page)
        chrome_args = [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                       "--force-device-scale-factor=1", "--window-size=1920,1080"]
        if transparent:
            # Verified 2026-08-10: this yields PNG colour type 6 (RGBA).
            chrome_args.append("--default-background-color=00000000")
        chrome_args += [f"--screenshot={out}/{slug}.png", f"file://{hpath}"]
        subprocess.run(chrome_args, capture_output=True)
        print("slate", slug, runtime)
    with open(os.path.join(out, "durations.json"), "w") as f:
        json.dump(durations, f, indent=1)
    print("done:", len(entries), "slates")


if __name__ == "__main__":
    main(sys.argv[1])
