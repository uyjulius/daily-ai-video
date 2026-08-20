# Beats

A **beat** is a subject the channel covers *every* night — with its own sourcing rules,
its own verification rules, and its own runtime. Beats recur. The `TOPICS.md` queue is
for one-offs and is consumed.

Slot *N* takes a queued topic if one is waiting, otherwise beat *N*, cycling if there are
fewer beats than `VIDEOS_PER_RUN`.

## Format

`beats/NN-name.md`, in filename order:

```
RUNTIME_MIN: 30
---
BEAT: <one paragraph — what this beat is about and what angle you want>

WHERE TO LOOK. <specific sources. Name them.>

WHAT MAKES A GOOD ONE. <what to pick, and explicitly what to avoid>

⚠️ VERIFICATION. <the rules for THIS beat's failure modes>
```

Everything after `---` is injected as the topic section of the nightly brief.
`RUNTIME_MIN` drives the word budget via `WPM`, so a 20-minute beat gets a shorter script
rather than a padded one.

## Writing a good beat

**Be specific about sources.** "Sweep the news" produces roundups nobody watches. Name
the forums, the filings, the T&C pages, the databases. The best beats send it somewhere
the coverage isn't.

**Say what to avoid.** Launch hype, funding rounds, and pure sentiment are what it will
drift toward unless you rule them out.

**Ask for one argument, not a summary.** A beat that says "pick the story with a real
disagreement and published data underneath" gets a thesis. One that says "cover the news"
gets a list.

**Put the verification rules in the beat itself**, not just in your head — see below.

## Verification rules belong per-beat

Different subjects fail differently, and this is the highest-value part of a beat file.

**Discourse beats** (forums, social) must separate two claim types that social sourcing
collapses together:

> 1. "PERSON X SAID Y" — the primary source is the post itself. Link it, quote exactly.
>    If it is a screenshot, find the original; screenshots are routinely faked or stripped
>    of context. If you cannot, cut it.
> 2. "Y IS TRUE" — a thousand upvotes is not evidence. Verify against the paper, docs, or
>    filing separately.

Without that split, the beat launders a confident forum comment into a stated fact. In a
live run this rule caught a search summary citing findings from a report **that does not
exist**.

**Terms-and-prices beats** must require every figure to come from the organisation's own
page *with a retrieval date*, because those pages change silently and secondary coverage
gets them wrong. It must also forbid stating a future effective date as already in force.

**Market beats** must require an explicit as-of timestamp on every number, distinguish
completed sessions from after-hours, and ban price targets and buy/sell framing outright.

## Disclosure

**If you have any connection to something you cover — you work there, hold equity,
consult, compete, or were paid — the beat must require that the video say so, in the
narration and the description, plainly.**

Put it in the beat file as a hard rule, because the pipeline runs unattended and will not
infer it:

```
⚠️ DISCLOSURE — MANDATORY WHENEVER <ORG> IS DISCUSSED. Any video covering <ORG> must
state, in narration AND description, that this is independent analysis from public
sources, not affiliated with, endorsed by, or produced with the cooperation of <ORG>.
Do not soften it and do not omit it.
```

A run once produced a description missing its required disclosures entirely. Beats are
instructions, not guarantees — spot-check published descriptions.

## Testing a beat

Queue a topic that fits it and watch one run end to end before trusting it nightly:

```bash
daily/new-video.sh --now "a topic squarely inside the beat"
```

Read the `verification.md` it produces. If the fact-check corrected or cut a large share
of claims, the beat is pointing at thin sources — tighten `WHERE TO LOOK`.
