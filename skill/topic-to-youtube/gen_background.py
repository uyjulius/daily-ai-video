#!/usr/bin/env python3
"""Fetch a free AI-generated slate background from Pollinations.ai (keyless, FLUX).

Usage: gen_background.py <workspace-or-outfile> "<prompt>" [seed]

If the first arg is a directory, saves to <dir>/background.jpg. Then set
"background": "background.jpg" in project.json so gen_slates.py picks it up.

Pollinations serves ~1024x576 for a 1920x1080 request; the slate CSS scales it
with background-size:cover under a heavy scrim, so that is plenty. No API key,
no quota — but it is a community service, so retry with backoff and fall back
to rendering slates without a background if it stays down.
"""
import os
import sys
import time
import urllib.parse
import urllib.request

MAGIC = (b"\xff\xd8\xff", b"\x89PNG")  # jpeg, png


def fetch(prompt, out, width=1920, height=1080, seed=None, tries=4):
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(prompt, safe="")
           + f"?width={width}&height={height}&nologo=true")
    if seed is not None:
        url += f"&seed={seed}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "topic-to-youtube/1.0"})
            data = urllib.request.urlopen(req, timeout=300).read()
            if not data.startswith(MAGIC):
                raise ValueError(f"response is not an image ({len(data)} bytes)")
            with open(out, "wb") as f:
                f.write(data)
            print("saved", out, f"({len(data)} bytes)")
            return
        except Exception as e:
            print(f"attempt {i + 1}/{tries} failed: {e}", file=sys.stderr)
            time.sleep(10 * (i + 1))
    sys.exit("pollinations unreachable — render slates without a background")


if __name__ == "__main__":
    target, prompt = sys.argv[1], sys.argv[2]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else None
    if os.path.isdir(target):
        target = os.path.join(target, "background.jpg")
    fetch(prompt, target, seed=seed)
