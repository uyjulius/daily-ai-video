#!/usr/bin/env python3
"""Fetch public-domain, CC0, CC-BY and CC-BY-SA stills from Wikimedia Commons
for one chapter.

Usage: fetch_images.py <project_dir> <chapter-slug> "<search terms>" [count]

Writes <project_dir>/backgrounds/<chapter-slug>/NN.jpg and merges attribution
into <project_dir>/backgrounds/credits.json.

Public domain, CC0, CC-BY and CC-BY-SA files are kept; NC (non-commercial)
and ND (no-derivatives) files are never kept -- the channel is monetised and
Ken Burns crops and zooms every still, so both restrictions are incompatible
outright. A Commons search returns MIXED licences -- a two-result probe
returned one "Public domain" file and one "CC BY-SA 2.5" file, both usable
under this filter -- so this filter is the whole safety mechanism, not a
refinement. A file whose licence cannot be determined -- including one
where the machine-readable `License` code and the human-readable
`LicenseShortName` disagree with each other -- is rejected.

Downloads the 1920px thumbnail, not the original: Commons originals are
routinely 20-50MB and the slate only ever shows 1920px under a scrim. If no
thumbnail URL is available for a candidate, that candidate is skipped
rather than silently falling back to the full-resolution original.
"""
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia blocks generic user agents.
USER_AGENT = "topic-to-youtube/1.0 (+https://github.com/uyjulius/daily-ai-video)"
MIN_LONG_EDGE = 1280
THUMB_WIDTH = 1920

# Structured-data recall aids: Commons' plain-text search spends its result
# budget on non-free licences (measured: 1-11 of 50 kept per query). Both
# statements below bias the SAME search toward machine-tagged public-domain /
# CC0 files (measured: 28-50 of 50 kept for the same queries) -- but a
# statement is user-editable and some genuinely-PD files carry none, so this
# is a RECALL AID, never a licence decision: the plain query stays in the
# union, and every hit -- tagged or not -- still goes through licence_ok()
# unmodified below.
_HASWBSTATEMENT_FILTERS = (
    "haswbstatement:P6216=Q19652",   # copyright status: public domain
    "haswbstatement:P275=Q6938433",  # copyright license: CC0 1.0
)

# This script's own output naming (see main()) -- used to clear a previous
# run's numbered files without touching anything a human dropped in by hand.
_NUMBERED_JPG_RE = re.compile(r"^\d{2,}\.jpg$")

# Exact-match allowlist for the human-readable LicenseShortName field.
# Deliberately NOT a substring test: "Public Domain Mark 1.0" means "no
# known copyright restrictions" -- an unverified claim, not a verified
# waiver -- and "Not in the public domain" / "Public domain claim
# disputed" both contain "public domain" as a substring while meaning the
# opposite. All three must fail.
_FREE_SHORT_NAMES = {
    "public domain",
    "cc0",
    "cc0 1.0",
    "cc zero",
    "cc zero 1.0",
}

# Exact-match patterns for the machine-readable License field. A bare
# prefix test (`startswith("pd-")` / `startswith("cc0")`) previously
# accepted look-alikes such as "cc0-like"; these patterns require the
# whole code to be well-formed.
_PD_MACHINE_RE = re.compile(r"^pd-[a-z0-9.-]+$")
_CC0_MACHINE_RE = re.compile(r"^cc0-1\.0$")

# CC-BY and CC-BY-SA are usable but require credit. NC and ND are NOT usable:
# NC forbids commercial use (the channel is monetised) and ND forbids
# derivative works (Ken Burns crops and zooms every still). These patterns
# require a bare BY or BY-SA with an explicit version -- "cc by-nc 4.0",
# "cc by-nd 4.0" and unversioned "cc by" all fail to match. A trailing
# jurisdiction or organisation port is allowed: a two-letter country code
# (bulk-uploaded German Bundesarchiv material commonly carries "CC BY-SA
# 3.0 DE" / "cc-by-sa-3.0-de") or the three-letter "IGO" port used by UN /
# WHO / World Bank material (measured: 38 of 50 files in
# Category:CC-BY-SA-3.0-IGO were wrongly rejected before "igo" was added
# here, even though CC BY-SA 3.0 IGO permits commercial use and
# derivatives just like the plain port). "nc" and "nd" are themselves
# valid two-letter strings, so the negative lookahead excludes them
# explicitly rather than trusting the suffix shape alone. The two suffix
# alternatives are spelled out explicitly (`[a-z]{2}` or `igo`) rather than
# `[a-z]{2,3}` so the accepted set stays enumerable instead of silently
# admitting any other three-letter code.
_ATTRIB_SHORT_RE = re.compile(
    r"^cc by(-sa)? [0-9]\.[0-9](?! (?:nc|nd)$)( [a-z]{2}| igo)?$")
_ATTRIB_MACHINE_RE = re.compile(
    r"^cc-by(-sa)?-[0-9]\.[0-9](?!-(?:nc|nd)$)(-[a-z]{2}|-igo)?$")


def _val(extmetadata, key):
    return str((extmetadata.get(key) or {}).get("value", "")).strip().lower()


def _machine_state(machine):
    """Classify the normalised `License` code.

    Returns 'public-domain', 'attribution', 'not-free', or 'absent'.
    """
    if not machine:
        return "absent"
    if machine in ("pd", "cc0"):
        return "public-domain"
    if _PD_MACHINE_RE.match(machine) or _CC0_MACHINE_RE.match(machine):
        return "public-domain"
    if _ATTRIB_MACHINE_RE.match(machine):
        return "attribution"
    return "not-free"


def _short_state(short):
    """Classify the normalised `LicenseShortName`.

    Returns 'public-domain', 'attribution', 'not-free', or 'absent'.
    """
    if not short:
        return "absent"
    if short in _FREE_SHORT_NAMES:
        return "public-domain"
    if _ATTRIB_SHORT_RE.match(short):
        return "attribution"
    return "not-free"


def licence_class(extmetadata):
    """Return 'public-domain', 'attribution', or None if the file is unusable.

    `License` (machine code) and `LicenseShortName` (human-readable) are two
    independently-sourced signals. If either is affirmatively not-free the file
    is rejected outright even if the other looks permissive -- a disagreement
    between them is exactly an undetermined licence, and undetermined licences
    are never assumed free.

    When both signals are free but disagree on class, the stricter one wins:
    a file is only attribution-free if nothing says it needs attribution.
    """
    if not extmetadata:
        return None
    if _val(extmetadata, "Restrictions"):
        return None
    states = (_machine_state(_val(extmetadata, "License")),
              _short_state(_val(extmetadata, "LicenseShortName")))
    if "not-free" in states:
        return None
    if "attribution" in states:
        return "attribution"
    if "public-domain" in states:
        return "public-domain"
    return None


def licence_ok(extmetadata):
    """True when the file is usable at all, whatever crediting it requires."""
    return licence_class(extmetadata) is not None


def usable(page):
    """True when this search result is free enough and big enough to use.

    The size floor is on the LONG edge, not the width: Ken Burns crops every
    still to 2560x1440 regardless of orientation (make_kenburns.py), so a
    portrait source is exactly as usable as a landscape one of the same long
    edge -- filtering on width alone drops ~9% of otherwise-good portrait
    images for no reason.
    """
    info = (page.get("imageinfo") or [{}])[0]
    if not licence_ok(info.get("extmetadata")):
        return False
    long_edge = max(int(info.get("width") or 0), int(info.get("height") or 0))
    return long_edge >= MIN_LONG_EDGE


def search(query, limit):
    params = {
        "action": "query", "format": "json",
        "prop": "imageinfo", "iiprop": "url|extmetadata|size",
        "iiurlwidth": str(THUMB_WIDTH),
        "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": "6", "gsrlimit": str(limit),
    }
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    return list(data.get("query", {}).get("pages", {}).values())


def search_union(query, limit):
    """The plain query plus each haswbstatement variant, deduped by title.

    Each variant is a separate request against the SAME `limit` (Commons
    caps gsrlimit at 50 regardless), so this can return more than `limit`
    pages in total -- main() applies `usable()` and its own `want` cap
    after the union, exactly as it did on a single plain search before.
    """
    seen = {}
    for variant in (query, *(f"{query} {f}" for f in _HASWBSTATEMENT_FILTERS)):
        for page in search(variant, limit):
            title = page.get("title")
            if title and title not in seen:
                seen[title] = page
    return list(seen.values())


def download(url, out):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        blob = resp.read()
    with open(out, "wb") as fh:
        fh.write(blob)
    return len(blob)


def _load_credits(creds_path):
    """Load existing credits.json, tolerating a missing or corrupt file.

    A truncated or hand-edited file must not crash the run and strand
    freshly-downloaded, correctly-licensed images with no attribution
    record -- fall back to an empty dict and warn instead.
    """
    if not os.path.exists(creds_path):
        return {}
    try:
        with open(creds_path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        print(f"WARNING: {creds_path} could not be read ({exc}); "
              f"starting from empty credits instead of crashing", file=sys.stderr)
        return {}


def _credit_licence(extmeta):
    """The licence label to record in credits.json.

    LicenseShortName (human-readable) is preferred, but when the API omits
    it, falling back to the literal string "unknown" throws away real
    evidence: the machine `License` code is exactly what licence_ok()
    itself used to accept the file, so it belongs in the record instead.
    """
    short = (extmeta.get("LicenseShortName") or {}).get("value")
    if short:
        return short
    machine = (extmeta.get("License") or {}).get("value")
    return machine or "unknown"


def _write_credits_atomic(creds_path, all_credits):
    """Write credits.json atomically so an interrupted run can't truncate it."""
    directory = os.path.dirname(creds_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".credits-", suffix=".json.tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(all_credits, fh, indent=1)
        os.replace(tmp_path, creds_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def main(project_dir, slug, query, want):
    out_dir = os.path.join(project_dir, "backgrounds", slug)
    os.makedirs(out_dir, exist_ok=True)
    # Clear this script's own numbered files from a previous run before
    # writing new ones. Every run names files 01.jpg, 02.jpg... from 01 and
    # replaces credits.json[slug] wholesale, so a re-run with widened terms
    # that keeps FEWER images than last time would otherwise leave earlier
    # files on disk with no attribution record (measured: 6 kept -> 2 kept
    # left 4 uncredited images composited with no licence record at all).
    # Only this script's own NN.jpg naming is touched -- anything else in
    # the directory is left for make_kenburns.py's credits.json check below.
    for f in os.listdir(out_dir):
        if _NUMBERED_JPG_RE.match(f):
            os.remove(os.path.join(out_dir, f))
    # Over-fetch: most search hits fail the licence filter. Union of the
    # plain query and the structured-data variants -- see search_union().
    pages = search_union(query, min(want * 6, 50))
    kept, credits = 0, []
    for page in pages:
        if kept >= want:
            break
        if not usable(page):
            continue
        info = page["imageinfo"][0]
        url = info.get("thumburl")
        if not url:
            print(f"  skip {page['title']}: no {THUMB_WIDTH}px thumbnail available "
                  f"(refusing to fall back to the full-resolution original)",
                  file=sys.stderr)
            continue
        dest = os.path.join(out_dir, f"{kept + 1:02d}.jpg")
        try:
            size = download(url, dest)
        except Exception as exc:
            print(f"  skip {page['title']}: {exc}", file=sys.stderr)
            continue
        extmeta = info.get("extmetadata") or {}
        credits.append({
            "file": os.path.basename(dest),
            "title": page["title"],
            "source": info.get("descriptionurl") or info["url"],
            "licence": _credit_licence(extmeta),
            "licence_class": licence_class(extmeta),
        })
        kept += 1
        print(f"  {dest}  ({size / 1e6:.1f} MB)  {credits[-1]['licence']}")

    creds_path = os.path.join(project_dir, "backgrounds", "credits.json")
    all_credits = _load_credits(creds_path)
    all_credits[slug] = credits
    _write_credits_atomic(creds_path, all_credits)

    print(f"{slug}: kept {kept}/{want} usable images from {len(pages)} results")
    if kept < want:
        print(f"WARNING: {slug} is short {want - kept} images — the chapter will "
              f"fall back to the abstract backdrop unless you widen the search",
              file=sys.stderr)
    return kept


if __name__ == "__main__":
    proj, slug, query = sys.argv[1], sys.argv[2], sys.argv[3]
    count = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    main(proj, slug, query, count)
