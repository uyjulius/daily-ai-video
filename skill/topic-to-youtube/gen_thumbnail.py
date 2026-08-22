#!/usr/bin/env python3
"""Render a YouTube thumbnail for a project.

Usage: python3 gen_thumbnail.py <workspace> ["Three To Six Words"] [accent_hex]

WHY THIS EXISTS (22 Aug 2026). The pipeline never set a thumbnail, so YouTube picked
a frame on its own — always a chapter slate, whose largest text is a chapter title set
for a 1920px canvas. At the 168px wide a phone actually shows, that is unreadable, and
an unreadable thumbnail is the cheapest way to lose a click before anyone hears a word.

This makes a purpose-built 1280x720: three to six words at a size that survives being
shrunk to a fingernail, the channel's hatched numeral as a watermark, and the accent
colour of the video's own opening chapter so the thumbnail and the video match.

The text is NOT the video title. A title explains; a thumbnail has to be legible in a
quarter of a second. Give it the shortest phrase that carries the argument — a number
and a noun beats a sentence.
"""
import json
import os
import subprocess
import sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

HTML = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bodoni+Moda:opsz,wght@6..96,700;6..96,800&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  html,body{{width:1280px;height:720px;overflow:hidden}}
  body{{background:#14161C;position:relative;font-family:'Bodoni Moda',Georgia,serif;
       display:flex;flex-direction:column;justify-content:center;padding:0 84px}}
  /* vignette + accent wash, so the flat panel has depth at small size */
  .wash{{position:absolute;inset:0;
     background:radial-gradient(120% 90% at 88% 12%, {accent}42, transparent 62%),
                radial-gradient(90% 70% at 0% 100%, {accent}22, transparent 60%);}}
  /* the channel's hatched numeral, oversized and cropped — visual signature */
  .mark{{position:absolute;right:-70px;bottom:-190px;font-size:660px;font-weight:800;
     line-height:.8;letter-spacing:-.05em;color:{accent};opacity:.30;
     background:repeating-linear-gradient(0deg,currentColor 0 5px,transparent 5px 10px);
     -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}}
  .eyebrow{{position:relative;font-family:'IBM Plex Mono',monospace;font-size:26px;
     font-weight:600;letter-spacing:.34em;text-transform:uppercase;color:{accent};
     margin-bottom:26px}}
  h1{{position:relative;font-size:{size}px;font-weight:700;line-height:.98;
     letter-spacing:-.022em;color:#F4F1EA;max-width:{maxw}px;
     text-shadow:0 6px 40px rgba(0,0,0,.65)}}
  h1 em{{font-style:italic;color:{accent}}}
  .rule{{position:relative;width:150px;height:7px;background:{accent};margin-top:34px}}
</style></head><body>
  <div class="wash"></div><div class="mark">{numeral}</div>
  <div class="eyebrow">{eyebrow}</div>
  <h1>{headline}</h1>
  <div class="rule"></div>
</body></html>"""


def size_for(text):
    """Fewer words, bigger type. Tuned so the longest line still fits 1112px."""
    n = len(text)
    if n <= 18:  return 168, 1000
    if n <= 28:  return 140, 1060
    if n <= 40:  return 116, 1090
    if n <= 55:  return 96, 1112
    return 80, 1112


def main(ws, headline=None, accent=None):
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(ws, "project.json")))
    except Exception:
        pass
    chapters = cfg.get("chapters") or []
    first = chapters[0] if chapters else {}

    if not headline:
        # Fall back to the opening chapter's hook, first clause only — better than
        # the title, which is written to explain rather than to be seen.
        hook = (first.get("hook") or cfg.get("series_title") or "").strip()
        headline = hook.split(".")[0][:60] or "Untitled"
    accent = accent or first.get("accent") or "#D4A24E"
    numeral = (first.get("numeral") or "00")
    eyebrow = (cfg.get("masthead") or "").strip() or "Explained"

    size, maxw = size_for(headline)
    # allow a single *emphasised* span:  "16% off *a price* it stopped publishing"
    hl = headline.replace("*", "", 0)
    if hl.count("_") == 2:
        a, b, c = hl.split("_")
        hl = f"{a}<em>{b}</em>{c}"

    html = HTML.format(accent=accent, numeral=numeral, eyebrow=eyebrow[:26],
                       headline=hl, size=size, maxw=maxw)
    hpath = os.path.join(ws, "thumbnail.html")
    open(hpath, "w").write(html)
    out = os.path.join(ws, "thumbnail.png")
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=1280,720",
                    f"--screenshot={out}", f"file://{hpath}"], capture_output=True)
    if not os.path.exists(out):
        raise SystemExit("thumbnail render failed — is Chrome installed?")
    print(f"wrote {out}  ({len(headline)} chars @ {size}px, accent {accent})")


if __name__ == "__main__":
    main(sys.argv[1],
         sys.argv[2] if len(sys.argv) > 2 else None,
         sys.argv[3] if len(sys.argv) > 3 else None)
