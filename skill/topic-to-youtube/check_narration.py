#!/usr/bin/env python3
"""Check a narration set against the channel's craft targets, before it is rendered.

Usage: python3 check_narration.py <workspace> [--strict]

WHY THIS EXISTS. Craft rules written into SKILL.md get followed for a while and then
quietly stop being followed. The em-dash was house style and recent scripts contained
zero of them; the closing-chapter formula survived nine videos of being told not to.
Instruction is not enforcement. This turns the targets into something checkable, so a
run can catch its own drift before spending an hour rendering.

Every threshold here came from measuring the published set, not from taste. Where the
channel has already beaten a target, the target is set to what it achieved.

Exit code is 0 unless --strict is passed, in which case any MISS exits 1.
"""
import argparse
import glob
import os
import re
import sys

IMPERATIVE = (r"^(Hold|Ask|Look|Notice|Consider|Watch|Read|Compare|Remember|Imagine|"
              r"Picture|Take|Note|Start|Keep|Try|Think|Count|Check)\b")


def analyse(ws):
    files = sorted(glob.glob(os.path.join(ws, "narration", "*.txt")))
    if not files:
        sys.exit(f"no narration/*.txt in {ws}")
    chapters = []
    for f in files:
        t = open(f).read()
        # the spoken chapter label is not prose; do not score it
        body = re.sub(r"^Chapter [A-Za-z]+\.\s*[^\n]*\n", "", t).strip()
        words = body.split()
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        sents = re.split(r'(?<=[.!?])\s+', body)
        chapters.append(dict(
            name=os.path.basename(f)[:-4],
            words=len(words),
            paras=len(paras),
            mean_para=len(words) / max(1, len(paras)),
            pron=len(re.findall(r"\b(you|your|yourself|you're)\b", body, re.I)),
            imper=sum(1 for s in sents if re.match(IMPERATIVE, s.strip())),
            questions=body.count("?"),
            dashes=body.count("—"),
            emph=body.count("**") // 2,
            linebreaks=sum(p.count("\n") for p in paras),
        ))
    return chapters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--tsv", action="store_true",
                    help="one machine-readable line, for sweeping many workspaces")
    a = ap.parse_args()
    ch = analyse(a.workspace)
    tw = sum(c["words"] for c in ch)
    addr = sum(c["pron"] + c["imper"] for c in ch)
    rate = addr * 1000 / max(1, tw)
    qs = sum(c["questions"] for c in ch)
    dashes = sum(c["dashes"] for c in ch)
    emph = sum(c["emph"] for c in ch)
    mean_para = tw / max(1, sum(c["paras"] for c in ch))
    half = len(ch) // 2
    first = sum(c["words"] for c in ch[:half]) / max(1, half)
    second = sum(c["words"] for c in ch[half:]) / max(1, len(ch) - half)
    taper = (second / first - 1) * 100 if first else 0

    rows = [
        ("direct address per 1000", f"{rate:.1f}", rate >= 12,
         "median of published set is 7.4; best is 21.7"),
        ("real questions (>= 1 per chapter)", f"{qs} in {len(ch)}", qs >= len(ch),
         "question marks, not imperatives dressed as questions"),
        ("mean paragraph words (<= 30)", f"{mean_para:.0f}", mean_para <= 30,
         "published mean is 41, a beat only every 13 s"),
        ("em-dashes (>= 1 per 2 chapters)", f"{dashes}", dashes >= len(ch) // 2,
         "recent scripts contained zero"),
        ("emphasis spans (1-3 per chapter)", f"{emph}", len(ch) <= emph <= 3 * len(ch),
         "**marked** — the loudest tool, so use it sparingly"),
        ("second half not heavier (<= +5%)", f"{taper:+.0f}%", taper <= 5,
         "all 13 published videos back-loaded, +7% to +46%"),
    ]
    if a.tsv:
        n_pass = sum(1 for r in rows if r[2])
        print("\t".join([os.path.basename(os.path.abspath(a.workspace)),
                         f"{rate:.1f}", f"{qs}/{len(ch)}", f"{mean_para:.0f}",
                         str(dashes), str(emph), f"{taper:+.0f}%", f"{n_pass}/6"]))
        sys.exit(1 if (n_pass < 6 and a.strict) else 0)

    width = max(len(r[0]) for r in rows)
    print(f"\n  narration check — {len(ch)} chapters, {tw} words\n")
    misses = 0
    for label, val, ok, why in rows:
        if not ok:
            misses += 1
        print(f"  {'PASS' if ok else 'MISS'}  {label:{width}s}  {val:>12s}   {why}")
    weakest = sorted(ch, key=lambda c: (c["pron"] + c["imper"]) / max(1, c["words"]))[:2]
    print(f"\n  least engaging chapters: " +
          ", ".join(f"{c['name']} ({(c['pron']+c['imper'])*1000/max(1,c['words']):.0f}/1000)"
                    for c in weakest))
    print()
    if misses and a.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
