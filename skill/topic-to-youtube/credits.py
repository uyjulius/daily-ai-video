#!/usr/bin/env python3
"""Description credits for the imagery a video used, and their verification.

Usage: credits.py <project_dir> [--compact]

Prints the IMAGE CREDITS block for the description on stdout. Exits 1, with
problems on stderr, when the credits are incomplete. Plain output lists each
image's title, source URL and licence; --compact drops the URL to "Title
(Licence)" under a single "all via Wikimedia Commons" line instead. SKILL.md
mandates --compact for the published description -- YouTube caps it at five
thousand characters, and full-URL credits can blow through that alone.

Public domain imposes no attribution duty, so this block used to be a
courtesy. It is not any more: once a CC-BY or CC-BY-SA image is in the video,
publishing without credit IS the licence violation. make_kenburns.py
composites only files listed in credits.json, so verifying this file verifies
what is actually on screen.
"""
import json
import os
import sys

CREDITS_NAME = "credits.json"
REQUIRED_FIELDS = ("file", "title", "source", "licence")


def credits_path(project_dir):
    return os.path.join(project_dir, "backgrounds", CREDITS_NAME)


def _has_fetched_stills(project_dir):
    """True when fetch_images.py has populated any chapter's stills dir.

    fetch_images.py writes into backgrounds/<slug>/NN.jpg subdirectories.
    The fixed-backdrop fallback (gen_background.py) writes flat files
    straight into backgrounds/ itself (backgrounds/NN.jpg) and never runs
    fetch_images.py, so it is not stills and must not trip this check --
    only a populated subdirectory counts.
    """
    backgrounds_dir = os.path.join(project_dir, "backgrounds")
    if not os.path.isdir(backgrounds_dir):
        return False
    for name in os.listdir(backgrounds_dir):
        sub = os.path.join(backgrounds_dir, name)
        if not os.path.isdir(sub):
            continue
        if any(f.lower().endswith(".jpg") for f in os.listdir(sub)):
            return True
    return False


def load_credits(project_dir):
    """Return the credits mapping, or {} when absent or unreadable."""
    path = credits_path(project_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def _entries(credits):
    """Yield (slug, entry) for every well-formed entry.

    Tolerates a malformed shape -- a non-dict root, a per-slug value that
    isn't a list, or a list item that isn't an entry object -- by skipping
    the offending piece rather than raising. `verify()` is responsible for
    surfacing those shapes as problems (with a message naming what was
    found); this helper exists for callers (`attribution_required`,
    `credit_lines`) that just want whatever valid entries exist, without
    duplicating verify()'s shape checks or crashing on bad input.

    A slug mapped to `null` (no entries recorded yet) is treated the same
    as an empty list -- that was already tolerated before this function
    existed and isn't a shape error worth reporting.
    """
    if not isinstance(credits, dict):
        return
    for slug in sorted(credits):
        entries = credits.get(slug)
        if entries is None:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                yield slug, entry


def attribution_required(credits):
    """True when any image needs crediting.

    An entry with no recorded class is treated as needing attribution: it
    predates the class field, and assuming it attribution-free would be
    assuming the permissive case, which is exactly what the licence rules
    forbid elsewhere.
    """
    for _slug, entry in _entries(credits):
        if entry.get("licence_class", "") != "public-domain":
            return True
    return False


def credit_lines(credits, compact=False):
    """One line per distinct image: title, source URL, licence."""
    seen, lines = set(), []
    for _slug, entry in _entries(credits):
        # str()'d before use as a dedupe key: this runs ahead of verify()'s
        # problems gate (main() calls it unconditionally), so a malformed
        # credits.json -- title/source recorded as a dict or list instead
        # of a string -- must not raise TypeError out of a set membership
        # check and crash the CLI with a traceback before the gate even
        # gets a chance to report the problem cleanly.
        key = (str(entry.get("title", "")), str(entry.get("source", "")))
        if key in seen:
            continue
        seen.add(key)
        title = str(entry.get("title", "")).replace("File:", "")
        if compact:
            lines.append(f"{title} ({entry.get('licence', '')})")
        else:
            lines.append(
                f"{title} — {entry.get('source', '')} ({entry.get('licence', '')})")
    return lines


def verify(project_dir):
    """Return a list of problems; empty means the credits are complete.

    A structurally-unexpected shape (the JSON parses fine but isn't the
    {slug: [entry, ...]} schema this file exists to verify) is reported as
    a problem naming what was found, not raised as an exception -- a shape
    error is exactly as much "cannot confirm this video is properly
    credited" as a missing field is, and letting it crash out with a
    traceback would leave the publish gate's failure mode undocumented.
    """
    path = credits_path(project_dir)
    if not os.path.exists(path):
        # A missing file is only a problem when there is imagery it should
        # have credited. A workspace that never ran fetch_images.py -- the
        # fixed-backdrop path documented in SKILL.md -- has nothing to
        # attribute, so a missing credits.json there is the correct,
        # expected state, not a gate to route around.
        if _has_fetched_stills(project_dir):
            return [f"{path} is missing — no attribution record for this video"]
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            credits = json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return [f"{path} is unreadable ({exc}) — attribution cannot be verified"]

    if not isinstance(credits, dict):
        return [f"{path}: expected an object mapping chapter slugs to "
                f"lists of credit entries, found {type(credits).__name__}"]

    problems = []
    for slug in sorted(credits):
        entries = credits[slug]
        if entries is None:
            continue
        if not isinstance(entries, list):
            problems.append(
                f"{slug}: expected a list of credit entries, found "
                f"{type(entries).__name__}")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                problems.append(
                    f"{slug}: expected a credit entry object, found "
                    f"{type(entry).__name__}")

    for slug, entry in _entries(credits):
        for field in REQUIRED_FIELDS:
            if not str(entry.get(field, "")).strip():
                problems.append(
                    f"{slug}/{entry.get('file', '?')}: missing {field}")
    return problems


def main(project_dir, compact=False):
    credits = load_credits(project_dir)
    problems = verify(project_dir)
    lines = credit_lines(credits, compact=compact)

    if lines:
        print("IMAGE CREDITS")
        if compact:
            print("  All images via Wikimedia Commons, reused under the licence shown.")
        for line in lines:
            print(f"  {line}")
    if attribution_required(credits):
        print("\n(Attribution required — this block MUST appear in the description.)")

    if problems:
        print("\nINCOMPLETE CREDITS — do not publish:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--compact"]
    main(args[0], compact="--compact" in sys.argv[1:])
