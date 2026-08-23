---
name: topic-to-youtube
description: Full pipeline from a research topic to a published YouTube video — a ~9-minute narrated explainer by default, or a multi-hour audiobook with --length full. Use when given a topic to research, write up, narrate, render to MP4, and publish to YouTube — e.g. "/topic-to-youtube quantum computing for investors" or "research X and put it on my channel".
---

# Topic → YouTube video pipeline

Input: a topic — anything from a three-word phrase to a multi-paragraph brief (from the
skill arguments or the user's message). When the input is a long brief, read it as the
commissioning letter: extract the core topic for the slug/series title, and treat every
stated preference (audience, angle, tone, chapter count, emphases, exclusions, target
length) as a requirement that overrides this skill's defaults. Restate your reading of
the brief in one short paragraph before starting research so a misreading surfaces
early — then proceed without waiting. Strip any `--length` / `--split` flags out of the
arguments before slugifying: they configure the run, they are not part of the topic, and
they must never reach the slug or series title. Output: ONE chaptered, AI-narrated video
with chapter timestamps, published **public** on your configured YouTube channel. Default runtime ~30 minutes.

Work autonomously end to end. Ask only if the topic itself is ambiguous. Keep the user
posted at each phase boundary. Scripts live next to this file (`$SKILL_DIR` below).

## Length targets

Default: **`brief`** — ~30 minutes. Override in the brief ("keep it under ten minutes",
"feature length") or with `--length <preset|Nm>`. A length stated in the brief wins over
the flag.

Narration runs ~149 words per minute **including the paragraph pauses `tts.py` inserts** —
measured on a real af_heart run at speed 1.0, not estimated. Every budget below derives
from that. Budget from the rate, not from a raw speaking rate, or you will overshoot.

**The rate is a property of the voice, not of the pipeline.** The tables below assume
`af_heart` at 1.0. A different narrator changes the rate and therefore the word budget,
and nothing fails loudly when this is wrong — the video just misses its runtime target.
Measured on identical real chapters (1,622 words over three chapters, pauses included):

| Voice | Speed | Rate | Words for ~30 min |
|---|---|---|---|
| `af_heart` | 1.0 | 148.4 wpm | 4,450 |
| `am_liam` | 1.0 | 167.4 wpm | 5,020 |

To measure a new voice: render two or three real multi-paragraph chapters with it, divide
total words by total minutes. Do not estimate it from a short single-paragraph sample —
that omits the paragraph pauses and reads ~30 wpm too fast.

The automated daily runner carries its own rate in `~/ai-videos/daily/config.sh` (`WPM`,
alongside `VOICE` and `SPEED`) and passes it into its brief explicitly, overriding this
section. If you change the voice there, change `WPM` too.

| Preset | Runtime | Segments | Narrated words | Per segment |
|---|---|---|---|---|
| `short` | 8–10 min | intro + 5 | ~1,350 | intro ~110 (~45 s), chapters ~250 (~100 s) |
| `brief` *(default)* | ~30 min | intro + 8 | ~4,450 | intro ~200, chapters ~530 |
| `full` | 3–4 h | intro + 20 | ~30,000 | intro ~200, chapters 1,200–1,800 |

Off-preset target: words ≈ minutes × 149, then pick a segment count so each segment lands
90–180 s (targets under ~30 min) or 8–12 min (longer targets).

**The runtime window is a target, not a gate.** If landing inside it would mean deleting
load-bearing evidence — the named figure, the statistic a chapter turns on — ship the
longer cut and state the overrun in the final report. Do not spend repeated trim passes
shaving words, and do not block on asking. A script compressed past the point where its
concrete evidence survives becomes the table-of-contents-read-aloud failure in §3, which
is worse than running long.

Only `full` carries the long-form floor — at `full` the complete runtime must exceed 60
minutes. Never apply that floor to a shorter target.

**Research and the write-up do not shrink with the target.** The full sweep and the
~30,000-word `writeup.md` are produced at every length; only narration is distilled. A
short run therefore leaves everything needed to narrate the full audiobook later as a
second pass, with no re-research.

## Output shape

**One video per run**, at every length. Chapters surface as timestamps in the
description; YouTube renders them as player chapters. Length and output shape are
independent — changing the target changes the runtime, never the number of videos.

`--split` opts into one video per chapter plus the complete stitch, collected in a series
playlist. Accepted at any length, but it only makes sense at `full`: splitting the default
~30-minute video yields nine ~3-minute uploads, and splitting a `short` one is worse still.

Do not confuse two things both called "per-chapter". Per-chapter **backgrounds** render
one segment per chapter and stitch them into ONE file — that is the default, and it is
how a single video gets changing visuals. Per-chapter **uploads** is `--split`.

## 0. Workspace

Create `$WORKSPACE_ROOT/<slug>/` (slugified topic) with subdirs:
`research/ narration/ wav/ mp3/ slates/ backgrounds/ videos/`. Everything for the run
lives here.

## 1. Research (thorough)

- Multi-angle sweep: WebSearch + WebFetch; for breadth, dispatch parallel Explore/general
  agents on distinct facets (history, economics, key players, criticisms, current state).
  Agents must write findings to `research/*.md` early and incrementally.
- Standards: every load-bearing claim needs a real source consulted; label estimates as
  estimates; prefer primary sources; note research date. Never invent specifics.
- If WebSearch budget runs dry: WebFetch known URLs, Wikipedia REST/search API, and
  WordPress REST/RSS of specialist blogs still work (see docs/TROUBLESHOOTING.md).

## 2. Write-up (the deliverable document)

`writeup.md` in the workspace: **~30,000 words (25,000–35,000), 20 chapters** plus a
short intro, unless the brief says otherwise. At this depth, draft chapters in batches
with subagents if useful, but keep one consistent voice.
Voice: first-person independent analyst — direct, opinionated, falsifiable ("here is my
model, here is the working, here is what would change my mind"). Structure: intro (what
this is, ground rules), foundations, mechanics, the money, the players, risks, the
commissioned-style questions, verdict. End with what would falsify the thesis.

## 3. Narration scripts

One `narration/NN-slug.txt` per segment (NN = 00 for intro, then 01…), written **for the
ear**, not copied. Segment count and word budgets come from the length target above.

At `full`, segments map 1:1 onto write-up chapters — each chapter rewritten for the ear.

Below `full` there are fewer segments than write-up chapters, so the script is a
**selection, not a summary**:

- `00-intro` — the thesis stated outright. No throat-clearing, no "in this video we will".
- Each segment — one load-bearing argument, carrying its own concrete evidence from the
  write-up.
- Final segment — the falsification beat: what would change my mind.

A short script is NOT all twenty chapters compressed. That produces a table of contents
read aloud, which is the standard failure of this shape. It must stand on its own as an
argument that happens to be backed by a book.

**Delivery — write it to be spoken, not read.** The substance above is the argument; this
is how it lands:

- Open cold on something concrete: a scene, a number, a decision someone made. Never "in
  this video we will", never a definition, never throat-clearing.
- Vary sentence length on purpose. Long sentences build; short ones land.
- A paragraph break is a beat. `tts.py` turns it into a pause, so breaks are pacing
  instructions, not typography — put one where a speaker would stop for effect.
- Prefer the specific to the general: the named year, the actual figure, the person who
  chose. Abstraction is what makes narration sound like a paper being recited.
- End each segment on a turn — a consequence, a reversal, a question the next segment
  answers — not on a summary of what was just said.

This is delivery, not licence to soften the claim. The falsifiable thesis is why the
video is worth watching; storytelling is how it gets heard.

Plain text only. Spell out numbers, years ("twenty twenty-six"), currencies ("eleven
million dollars"); no markdown, tables, or URLs. Paragraph breaks become breathing
pauses. Open each chapter "Chapter N. <Title>." Keep the analyst voice.

### Speaking to someone, not at a wall

Measured 23 Aug 2026 across the published set, and this is the channel's biggest
remaining weakness. Ordinary conversation uses *you/your* around 20-30 times per
thousand words. These scripts run **2 to 7**, and several carry **one to four questions
across a full half-hour**. Nobody is being addressed. The prose is correct, well
evidenced, and talking to an empty room.

**Kokoro will not rescue this.** Measured: the same clause with a comma, an em-dash, a
full stop or a colon gives the same pause to within 6%; a question mark does not raise
the final pitch; CAPITALS produce a byte-identical pitch contour. Every expressive
device a writer reaches for dies in the model. So engagement has to be built into the
words and the pacing, both of which you control.

**Address the listener.** Not constantly, and never matily — but a half-hour argument
with no second person in it is a lecture delivered to furniture. Aim for 12-20 per
thousand. *"Hold that number next to this one."* *"So ask yourself what would have to
be true."* *"You have seen this before."*

**Ask real questions.** A question the video then answers is the cheapest way to make
someone lean in, and it costs nothing in rigour. Two per chapter is not too many. A
question is only dead if you answer it in the same breath.

**Use the pacing devices — they are the only emphasis you have.** `tts.py` turns four
things into real silence:

| Device | Silence | Use it for |
|---|---|---|
| paragraph break | 0.55 s | the argument moves on |
| single line break | 0.32 s | a beat inside an argument |
| em-dash | 0.22 s | the aside, the correction, the turn |
| `**marked span**` | 0.34 s either side, and 10% slower | the number or phrase the chapter turns on |

Two warnings from the audit. Recent scripts contain **zero em-dashes** — a device that
used to appear 288 times across the set has simply been dropped, and with it every
aside and turn. And paragraphs average 41 words, so the voice gets a real beat only
about **every 13 seconds**; that unbroken wall is most of what makes it feel robotic.
Break more often than feels necessary on the page. It is being *heard*, not read.

Use `**emphasis**` sparingly — two or three per chapter. It is the loudest tool here and
it stops meaning anything if every paragraph has one.

### A worked example, because the rules keep getting ignored

The em-dash was in the house style and recent scripts contain **zero** of them. Rules
alone do not survive. This is the target, written out — copy the *shape*, not the words.

**Before** — correct, evidenced, and talking to nobody. Two paragraphs, 71 words, one
pause in the middle:

> On Thursday the twentieth of August, twenty twenty-six, the Dow Jones Industrial
> Average closed at fifty-two thousand, seven hundred and fifty-nine point two one. It
> had fallen seven hundred and three point eight four points. One point three two
> percent. Its worst session since the twenty-ninth of July.
>
> By that evening the explanation was everywhere, and it was one word long. Walmart. The
> company had reported before the bell and its shares had fallen nine point one five
> percent. Here is the problem with that explanation. Walmart is one point two seven
> percent of the index.

**After** — same facts, same rigour, nothing softened:

> On Thursday the twentieth of August, the Dow fell seven hundred and three points.
>
> By that evening the explanation was everywhere. It was one word long.
>
> Walmart.
>
> The company had reported before the bell, and its shares fell nine point one five
> percent. So far, so reasonable.
>
> Now hold that number next to this one.
> Walmart is **one point two seven percent** of the index.
>
> That is the whole company — one and a quarter percent of the average.
>
> So ask yourself what would have to be true for that stock to move this index seven
> hundred points.

What changed, and why each one matters:

- **A one-word paragraph.** "Walmart." earns a full beat on its own. The before version
  buries it mid-sentence.
- **Two direct addresses** where there were none — *hold that number*, *ask yourself*.
- **A question at the end** that the next chapter answers, so there is a reason to stay.
- **One `**emphasis**` span**, on the number the whole chapter turns on. Only one.
- **An em-dash** doing the aside it was invented for.
- **Nine paragraphs instead of two**, so the voice breathes roughly every eight seconds
  rather than every thirty.
- The date is still there. It is just no longer the first thing anyone hears.

Nothing was dropped and no claim was weakened. It is the same argument, spoken to
someone.

### Pacing: every video so far gets heavier as it goes

Measured across thirteen videos: the second half runs **7% to 46% longer per chapter**
than the first, median about +26%. Not one tapers. Chapter 1 lands around 230-260 words
and chapters 8-10 around 550-620.

That is backwards. Attention falls across half an hour; the load should fall with it.
As built, the densest material arrives where the fewest people are still watching.

**Budget the chapters deliberately instead of letting them grow:**

| Position | Share of the word budget | Job |
|---|---|---|
| Opening | ~5% | the hook and the claim |
| Chapters 2-4 | **the longest chapters** | the evidence, while attention is highest |
| Middle | steady | the turn — the complication or counter-argument |
| Final third | **shorter than the middle** | consequence, then stop |

A closing chapter should be among the *shortest*, not the longest. If the ending needs
600 words to land, the argument has not been made yet — fix that earlier, not here.

### Craft: what an audit of the first twelve videos found

Measured across ~53,000 narrated words, not asserted. These are the house's actual bad
habits; each one is fixable and each one recurs unless you deliberately break it.

**1. Nobody ever does anything.** Fourteen concrete action verbs in 53,000 words. A
seven-hour outage happened and no engineer appears in it; companies "say", figures
"are", positions "are stated". The result is a well-argued lecture rather than a story.
*Fix:* find the human moment in the material and open on it — someone at a keyboard at
13:28 UTC, someone reading a clause, someone deciding. Then step back to the argument.
One concrete scene per video is the minimum; the evidence still carries the case.

**2. The ending is a formula.** Nine of twelve videos closed with a chapter titled
"What Would Change My Mind", six of them opening with the same two moves — *let me state
my position plainly*, then *here is how to break it*. Intellectually honest, and by the
fifth video, recitable.
*Fix:* keep the falsification conditions — they are the channel's integrity — but stop
making them a named chapter with a stock opening. Fold them into the closing argument,
or state them where the relevant claim is made rather than saving them all up.

**3. The narrator keeps announcing what he is about to do.** 115 instances of *let me /
let us / I want to*; "I want to be" alone appears 21 times. "Now, the chain of causation.
And I want to walk through it slowly, because…" — that is throat-clearing before content.
*Fix:* cut the announcement and do the thing. The sentence after it is almost always the
real opening.

**4. One judgement rhythm, repeated.** 249 sentences (one in eighteen) open with
"That is / It is / This is". Over half an hour it drones.
*Fix:* vary the cadence. Let some evidence land without a verdict attached.

**Lead with the fact, not the date.** Seven of the first twelve videos opened "On the
seventeenth of August, twenty twenty-six, X did Y" — the date first, the interesting
thing second. Compare the strongest opening in the set, which does the reverse:

> Ten million dollars. That is what Google paid, at auction, on Friday the fourteenth
> of August, for everything a dead airline ever wrote down about itself.

Same facts, same sentence even — but the arresting number goes first and the date lands
where it belongs, as context. The date is almost never the most interesting thing you
know. Open on the number, the contradiction, or the image; date it in the next breath.

**5. Seven of twelve open with the same dateline.** "On the seventeenth of August,
twenty twenty-six, X did Y." Reliable, and interchangeable.
*Fix:* the dateline is one option among several — a number with no context, a quotation,
a question the video will answer, a scene. Vary it.

**Never speak "Chapter zero" or "Introduction".** One video opened with the literal words
"Chapter zero. Introduction." — three seconds of administration in the most valuable
three seconds of the video. Numbered chapter labels are house style from Chapter One
onward; the intro just starts.

## 4. project.json

Write `project.json` in the workspace:

```json
{
  "slug": "...", "series_title": "<Topic> — The Complete Strategic Analysis",
  "masthead": "<Short name>", "masthead_rest": "<rest of series title>",
  "research_stamp": "AUG 2026",
  "chapters": [
    {"slug": "00-intro", "numeral": "00", "eyebrow": "Prologue", "title": "Introduction",
     "hook": "<one italic line from the chapter's core claim>", "accent": "#D4A24E",
     "background": "backgrounds/00.jpg"}
  ],
  "complete": {"numeral": "<total minutes>", "eyebrow": "<Complete Run>",
     "title": "The Complete <...>", "hook": "<N> chapters. One sitting.", "accent": "#D4A24E",
     "ledger": "<LEDGER STRIP — defaults to AUDIOBOOK · COMPLETE>", "mp3": "complete.mp3"}
}
```

The series title must suit the length: `"<Topic> — The Complete Strategic Analysis"` is
full-length branding — reserve wording like that for `full`. At `short`/`brief`, pick a
name that fits a single explainer instead (e.g. `"<Topic>"` or `"<Topic>: Explained"`),
split the same way into `masthead`/`masthead_rest`.

The same rule applies inside the `complete` block: its `eyebrow`, `title` and `ledger`
are rendered onto the complete slate, so "The Complete Audiobook" and the default
`AUDIOBOOK · COMPLETE` ledger strip are apt at `full` and wrong on a single-sitting
explainer at `short` or the default `brief`. Set `"ledger"` to override the strip (omit it to keep the default).

Give every chapter its own accent ink (curated, muted — gold/teal/amber/steel/green/
vermilion/emerald/violet/crimson/indigo/cyan/lime-gold/silver; never neon). Hooks come
from each chapter's actual argument. A chapter's own `"background"` key overrides the
project-level `"background"` (§6 covers how to generate `backgrounds/NN.jpg` per
chapter). The `complete` block is **optional** and unused on the default path (the
stitch is built from chapter segments, so its slate is never shown). Include it only for
a single-slate render; when you do, `complete.numeral` = total runtime in minutes, filled
in after TTS.

## 5. Audio

**Write project.json (§4) first.** `build_audiobook.sh reads project.json` on its first
line to get the series title, so running it earlier fails instantly with a traceback and
no audio. The section order here is a dependency, not a suggestion.

```bash
bash $SKILL_DIR/build_audiobook.sh <workspace> af_heart 1.0
```

Kokoro TTS (default voice **af_heart**) via `$TTS_VENV` (override with `$TTS_PY`;
rebuild with `python3.12 -m venv … && pip install kokoro soundfile numpy`). Resumable —
existing wav/mp3 are skipped. If you included a `complete` block (§4), update its
`complete.numeral` in project.json now; `concat_complete.py` (§6) emits the cumulative
chapter timestamps for the complete video's description.

## 6. Slates and videos

Every run produces ONE video, stitched from per-chapter segments so the backdrop changes
through it. Generate a fallback backdrop for every chapter as insurance against a thin
imagery search below — give each chapter its own `"background"` (distinct Pollinations
prompts per chapter, `backgrounds/NN.jpg`). A chapter that does end up with stills simply
ignores its configured backdrop.

**Imagery (default ON).** Chapters get real public-domain photographs that pan and zoom
slowly, not a static abstract backdrop. A chapter that ends up with neither fetched
stills nor a configured `backgrounds/NN.jpg` fails silently: unlike a background that
*was* configured but whose file is simply missing (that case prints a stderr warning),
a chapter with no imagery and no `"background"` key at all gets the plain rosette design
from `gen_slates.py` with no warning or error — so skipping a chapter here ships a
finished video with no artwork for it and nothing telling you why.

Two of the four stages below are per chapter — repeat them for every chapter slug before
moving on — and two are workspace-wide, run once after every chapter has been through the
per-chapter step that precedes them:

**The abstract escape hatch has become the default — check yourself.** Audited 22 Aug
2026: **zero of seventeen** workspaces had a `credits.json`, meaning every video ever
made took the AI-generated-abstract route and no video has ever carried a real
photograph. Every one of them looks the same as a result.

Abstract backdrops are the right answer when the subject *is* named living people and
a photograph would imply association — that is a real trap and it is why the option
exists. They are the wrong answer for a credit card's terms, a stock index, a data
centre outage, or an airline's bankruptcy estate, all of which have safe, plentiful
public-domain imagery. Reach for abstract when you can name the person a photograph
would misrepresent. Otherwise fetch the stills.

```bash
# 1. Per chapter — repeat for every chapter slug before moving on:
python3 $SKILL_DIR/fetch_images.py <workspace> <chapter-slug> "<search terms>" 8

# 2. Once, for the whole workspace, after every chapter above has run:
python3 $SKILL_DIR/gen_slates.py <workspace>        # needs Chrome; transparent where stills exist; slates/ + durations.json

# 3. Per chapter — after step 2, once per chapter.
#    Skip any chapter fetch_images.py left with no stills: make_kenburns.py exits 0
#    with a "no stills, skipping" message for those, which is a normal outcome, not a
#    failure. That chapter keeps its still slate over the fallback backdrop.
python3 $SKILL_DIR/make_kenburns.py <workspace> <chapter-slug>

# 4. Once, for the whole workspace:
python3 $SKILL_DIR/render_videos.py <workspace> 00-intro 01-<slug> 02-<slug> ...  # chapter slugs ONLY
python3 $SKILL_DIR/concat_complete.py <workspace>   # → videos/complete.mp4 + timestamps
```

Order matters and the stages detect each other: `gen_slates.py` renders a transparent
slate for any chapter that already has a `backgrounds/<slug>/` directory — which is why
every chapter's `fetch_images.py` must finish before the single `gen_slates.py` call, not
be interleaved with it, since `gen_slates.py` takes the whole workspace, not one chapter.
`render_videos.py` uses `backgrounds/<slug>.mp4` as its base layer when that file exists,
which is why `make_kenburns.py` — it composites that chapter's slate onto the moving
background — runs after `gen_slates.py` and before `render_videos.py`. No flags, no
project.json keys.

Search terms are yours to choose per chapter, and two rules matter more than instinct.

**Fewer words win.** Commons full-text search narrows fast, and a third word can empty a
query. Measured: `Square Enix` returned 143 results; `Hiromichi Tanaka game developer`
returned **zero**. `Game Developers Conference` returned 142; adding `talk` cut it to 48.
Two words is usually the sweet spot. If a chapter comes back short, shorten the query
before you widen it.

**Never search a person's name and trust the result.** Commons frequently
`returns a different person of the same name`. Searching `Naoki Yoshida` for a chapter
about the Final Fantasy XIV producer returned photographs of a Japanese jockey — correctly
licensed, correctly filtered, counted 8 of 8, and completely wrong. Searching
`video game developer` returned photographs of a named developer with no connection to the
subject, which is worse than wrong: it implies an association that does not exist.

**Look at what came back before you render.** No part of this pipeline can tell whether a
photograph is of the right subject. The licence filter checks licences, `credits.py` checks
attribution, and both will pass a chapter illustrated entirely with the wrong person. After
fetching, read `backgrounds/credits.json` and check the file titles against the chapter's
subject — this costs one command and is the only thing standing between a plausible-looking
run and a published mistake.

When a chapter has no honest imagery, prefer the abstract backdrop below. Photographs of
unrelated real people are worse than no photographs at all, and a mixed video — some
chapters photographic, some abstract — is a perfectly good outcome.

**Search the making, not the work.** For any subject whose own imagery is copyrighted —
games, films, characters, products — searching the work returns fan photography and
false matches on single words. Searching the people and events around it returns real
professional photography that is genuinely licensed. Measured on Commons, of 50 results:
`Hironobu Sakaguchi` yields 0 public-domain images but 8 of 8 usable once CC-BY counts;
`Tokyo Game Show` 0 and 50; `Naoki Yoshida` 1 and 47 — a licence tally only: this is the
same query that returned the jockey's photographs above, not the producer's. Prefer
developers and creators by name, the studio or publisher, industry conferences, concerts
and award shows, and period hardware — which is often public domain outright (`Super
Famicom console`: 32 of 50).

This is a search-strategy rule, not a licence relaxation:
**never screenshots, box art, or character art.** Those belong to the rights holder
whatever the filter says, and no licence field on Commons makes them yours to publish.

**Public domain, CC0, CC-BY and CC-BY-SA files are kept**; the script discards
everything else — never non-commercial or no-derivatives. If a chapter comes back short,
shorten the query before you widen it (above), or let it fall back to the abstract
backdrop below — a mixed video is fine.

Pass the chapter slugs explicitly to `render_videos.py`. Running it with no filter also
encodes a `complete.mp4` from the single complete slate, which `concat_complete.py` then
overwrites — pure waste.

For one fixed backdrop instead, set a single project-level `"background"` and render just
`complete` (`render_videos.py <workspace> complete`); no concat step, and no per-chapter
timestamps.

Under `--split`, the rendering above does not change: chapter segments are rendered and
`concat_complete.py` still runs to stitch them into `videos/complete.mp4`. What changes
is uploads — upload every chapter segment individually, AND the stitched
`videos/complete.mp4` from `concat_complete.py`, which is the one uploaded as the
complete/finale entry. Do not substitute the single fixed-backdrop `complete.mp4` from
`render_videos.py <workspace> complete` (that's the one-fixed-backdrop path above, not
`--split`) — uploading it as the finale would publish the wrong video.

**Slate background art (fallback, free):** atmospheric 16:9 images from Pollinations.ai
— keyless and free (FLUX under the hood), with retry-with-backoff built in. Use this when
you deliberately want a fixed abstract backdrop instead of photographs. One distinct
prompt per chapter, saved to the exact `backgrounds/NN.jpg` path referenced by that
chapter's `"background"` key:

```bash
python3 $SKILL_DIR/gen_background.py <workspace>/backgrounds/00.jpg "<prompt for chapter 0>"
```

`gen_background.py` writes exactly to the path you give it — pass the full
`backgrounds/NN.jpg` file, not the workspace, or you'll overwrite a single shared image
instead of generating one per chapter. For one fixed backdrop instead (the single-slate
path above), pass the workspace directory and it saves `<workspace>/background.jpg`:
`python3 $SKILL_DIR/gen_background.py <workspace> "<prompt>"`. Either way, set
`"background"` in project.json (a per-chapter key overrides the project-level one), and
the image replaces the rosettes and sits under the dark scrim, so slate text stays
readable. Prompt style: abstract/atmospheric, matched to the topic and the
banknote-engraved look (etching, engraving, blueprint, dark still-life); never ask for
text or lettering in the image — models render it garbled. Pollinations is a community
service: the script retries with backoff, and if it stays down just omit the key —
slates fall back to the rosette design. Do NOT reach for mcp-image (Gemini free-tier
daily quota) or Replicate (spends your Replicate credits) for backgrounds unless you have opted in.
Keep generated backdrops abstract. The YouTube altered-content answer turns on whether
**AI-generated** imagery depicts realistic people or events — if it does, answer Yes.
Public-domain photographs are not altered content and do not trigger it; a synthetic
voice reading your own script does not either.

**Background music (default ON):** generate a rights-free **rhythmic** bed once per project —
`$TTS_PY $SKILL_DIR/make_music.py <workspace>/music.wav <MINUTES> <slug>`

**Pass both arguments.** `render_videos.py` loops the bed with `-stream_loop -1`, so a
3-minute file under a 30-minute video is heard ten times — which is what made the score
on this channel monotonous through 21 Aug 2026. Generate to the video's actual runtime
plus a minute (31 minutes costs ~17 s) and it never repeats. The slug seeds key, mode,
chord progression and bell placement, so no two videos share a score; omit it and every
video gets the same one.

The bed is a beat — soft kick, low hats, rim tick, bass and plucked chords at 88-104
BPM, built in 8-bar sections that add and drop layers. It is deliberately not ambient:
this is an explainer channel. Everything is chosen to survive being ducked under a
voice — no snare crack, no bright cymbals, no melodic hook that competes with the
narration. If the pulse is too shy under narration, raise `music_gain_db` from the
default -26 toward -22; do not compensate by making the bed itself busier.
(name the interpreter explicitly: `$TTS_PY` is set inside build_audiobook.sh and never
exported, and make_music.py is not executable, so a bare `$TTS_PY …` fails with
permission denied) — and set `"music": "music.wav"`
in project.json (plus optional `"music_gain_db"`, default −26). render_videos.py loops it
under the narration with sidechain ducking. Set `"music": null` to disable, or point it
at any user-supplied audio file. (Fancier beds: Replicate MusicGen is available via MCP,
but it spends your Replicate credits — only if you have opted in.)

**Narrator (default `af_heart`):** pass a different Kokoro
voice to build_audiobook.sh to override. Good options — female: af_heart, af_bella,
bf_emma, bf_isabella; British male: bm_george, bm_fable, bm_lewis;
American male: am_michael, am_adam. For the storyteller register, bm_george and am_michael
carry authority well. Speed 0.95–1.0 gives the delivery room to breathe; faster than 1.0
flattens it. Honor any voice preference in the brief; a voice comparison page exists at
https://claude.ai/code/artifact/0cfea0bf-73c0-4d76-a678-cd8d55d24218

Kokoro will not produce a dramatic pause or a pitch drop on its own. Pacing comes from
the script — see the delivery rules in §3 — so write the breaks you want to hear.

Visually check ONE slate PNG (Read tool) and one mid-video frame before batch-rendering
everything. Design intent: banknote-engraved numeral + departure-board strip; the bottom
240px is reserved for the runtime waveform. Do not "fix" the showwaves-white +
colorchannelmixer recipe or the overlay progress bar — direct hex colors render purple
and drawbox width expressions freeze (details in the script headers).

### The description is a trust artefact, not an afterthought

Two rules, both from an audit of the published set.

**The first 157 characters are all most people see.** That is what YouTube shows above
the "…more" fold, in search results, and in the sidebar. Spend it on the hook, never on
scaffolding. From the audit — the weakest opening in the set spent its entire visible
portion on a corporate parenthetical:

> On 17 August 2026, GXS Bank — a Singapore digital bank with a full MAS banking licence,
> owned by a consortium of Grab Holdings and Singtel — launched the…

…and the claim the video is actually about (a headline 10% that pays 4%) never appears
above the fold at all. Compare the best:

> On Thursday 20 August 2026 the Dow fell 703.84 points, -1.32%. The explanation that
> travelled was one word: Walmart, down 9.15%. But Walmart was 1.27% of the…

**Always carry a PRIMARY SOURCES block.** Non-markets videos averaged 6-12 cited
sources; the three markets videos carried 0, 1 and 1 — the beat where figures rot
fastest was the one publishing nothing checkable. The description is where a sceptical
reader goes to re-derive your numbers. Name the document, the publisher, and the date
you read it, for every load-bearing figure.

### Titles: what the audit found

Fifteen published titles, measured:

- **5 of 15** use the same construction — *"...what the forensics actually say"*, *"...what
  Maybank's terms actually say"*, *"...what the filing actually says"*, *"...what the card's
  own terms say"*. It is a good move. It is not a good *only* move.
- **7 of 15** are the colon form, *"X: y"*.
- **4 run past 73 characters**, which truncates in YouTube search and on mobile. The
  longest was 84.

**Rules:**

1. **Under 60 characters** wherever the argument survives it. That is what shows before
   truncation on the surfaces where people actually browse. 70 is a hard ceiling.
2. **Front-load the distinctive words.** If it truncates, the half that survives must
   still say what the video is. *"GitHub's commits doubled in 4 months"* survives;
   *"The July 2026 OpenAI-Hugging Face agent intrusion:"* spends 50 characters before
   reaching a verb.
3. **Rotate the construction.** A specific number (*"The Dow's 704 points"*), a flat
   contradiction (*"GXS's 10% cashback that is 4%"*), a plain question - not "what X
   actually says" four times a fortnight.
4. **The title and the thumbnail are different jobs.** The title is searched and read;
   the thumbnail is glanced at. Never put the same words in both.

## 6b. Thumbnail (mandatory)

```bash
python3 $SKILL_DIR/gen_thumbnail.py <workspace> "Three to six words"
```

Then pass it to the upload: `--thumbnail <workspace>/thumbnail.png`.

**Without this YouTube picks its own frame** — always a chapter slate, whose largest
text is set for a 1920px canvas and is unreadable at the 168px a phone actually shows.
An unreadable thumbnail loses the click before anyone hears a word. Audited 22 Aug 2026:
none of the first fifteen videos had one.

Rules for the text, in order of how much they matter:

1. **Short.** Tested at true feed size: 33 characters reads instantly, 54 is legible but
   work. Three to six words. A number and a noun beats a sentence.
2. **Not the title.** The title explains; the thumbnail has to land in a quarter of a
   second. "Commits doubled. Nobody says why." not "GitHub's commits doubled in 4
   months; its outage report stopped saying why".
3. **State the tension, not the topic.** The gap, the contradiction, the number that
   does not add up.
4. Wrap one phrase in `_underscores_` to set it in the accent colour, if one phrase
   carries the point.

The generator takes the accent and numeral from the opening chapter, so the thumbnail
and the video match. Setting a thumbnail requires a phone-verified channel; if it is
not, the upload still succeeds and prints a notice.

## 7. YouTube upload

**Path A — API (preferred when available).** If `~/.config/topic-to-youtube/token.json`
exists, upload with:

```bash
~/.venv-ytapi/bin/python $SKILL_DIR/yt_upload.py <video.mp4> --title "..." \
  --description-file d.txt --tags "..." --privacy public \
  --thumbnail <workspace>/thumbnail.png
```

Add `--playlist "<series title>"` under `--split` only, to collect the chapter uploads.
(`yt_auth.py` mints the token from a Desktop OAuth client; venv:
`python3 -m venv ~/.venv-ytapi && pip install google-api-python-client google-auth-oauthlib`.)
Run the FIRST upload of a session with `--check-lock`: un-audited API projects get
uploads forced private ("Video locked"). If it prints LOCKED_PRIVATE, fall back to
Path B for everything and request an API audit at
https://support.google.com/youtube/contact/yt_api_form. API quota note: each upload
costs ~1,600 quota units of the default 10,000/day — that is only ~6 uploads/day. A
default run is a single upload, so quota is a non-issue. Under `--split`, upload the
first ~6 via API and the rest via Path B (or spread across days).

**Path B — browser chunk relay (always works for public).**
Read memory `youtube-upload-chunk-relay` first — it is the operating manual. Summary:

- claude-in-chrome, studio.youtube.com, verify the channel identity is your own.
- Files exceed the 10MB file_upload cap: `split -b 9000000`, relay chunks through a
  hidden `<input>` you inject, assemble with `new File(window.__cc, …)` into
  `ytcp-uploads-file-picker input[type=file]`, dispatch `change`.
- NEVER click "Select files" (native picker wedges CDP). NEVER fetch localhost from page
  JS (permission prompt freezes the tab). NO osascript keystrokes, ever.
- Metadata: engaging title — at short lengths a standalone hook, no `Ch. N` suffix; under
  `--split`, `<Hook> | <Series short name> — Ch. N`. Description = synopsis + chapter
  timestamps + ABOUT THIS SERIES footer (independent
  analysis, public sources, research date, AI-narrated, unaffiliated, not financial
  advice), ~12 tags, audience **not made for kids**, altered-content/AI disclosure **No**
  (abstract slates + generic synthetic narration; re-answer honestly if AI-generated
  visuals ever depict realistic people/events — public-domain photographs don't trigger
  it), visibility **Public**.
- Default run = ONE upload: no playlist step, no "Reuse details".
- **Under `--split` only:** create the series playlist (public) in the playlist picker on
  the first video; later videos use "Reuse details" with Title+Description UNCHECKED
  (carries playlist/tags/category). Reuse does NOT carry the kids answer or AI disclosure
  — set both every time, via page JS clicks on the `tp-yt-paper-radio-button`s
  (coordinate clicks break when the window resizes). Drive Next×3 → PUBLIC → publish via
  `#next-button` / `[name="PUBLIC"]` / `#done-button` in page JS. Upload order: chapters
  00→NN, complete last.
- Publishing mid-upload is fine (goes public when processing ends) but the Studio tab
  must stay open until "Uploading 100%" — leave the Claude tab group open.
- Capture every youtu.be URL from the details panel as you go.

Before uploading via either path, build the IMAGE CREDITS block with `python3
$SKILL_DIR/credits.py <workspace>` and paste its output into the description.

YouTube caps descriptions at five thousand characters, and full-URL credits blow through
it: the Final Fantasy XIV pilot produced fifty-one credit lines totalling over nine
thousand characters. Use `python3 $SKILL_DIR/credits.py <workspace> --compact` for the
description — it prints `Title (Licence)` under a single "all via Wikimedia Commons" line,
which keeps attribution adequate because every file is findable by title. Run the plain
form when you want the full URLs for your own records.

**This is now a publish gate, not a courtesy.** Public domain requires no attribution, but
CC-BY and CC-BY-SA do, and the imagery filter accepts both — so publishing a video whose
credits are incomplete is the licence violation itself. `credits.py` exits non-zero when
any image lacks a title, source or licence: if it does, fix the credits before uploading,
never after.

## 8. Verify, fix, clean up, report

- Content page: the video is Public/Published. Interrupted upload → delete the draft, re-relay.
- **Under `--split` only:** fetch the public playlist with curl and diff its videoIds
  against your captured list — reuse-clicks DO miss the playlist sometimes; bulk-fix via
  Content page checkboxes → "Add to playlist".
- Delete the chunk directories. Keep mp3/, videos/, writeup.md.
- Final report: link(s) — the one video by default, or playlist + every video under
  `--split` — the decisions made, and anything skipped or degraded. Nothing is "done"
  until seen Public on the channel.
