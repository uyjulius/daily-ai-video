# The dashboard

The route that needs no terminal. If someone else set this machine up for you, this is
the only page you need.

## Opening it

Click the icon in your menu bar — the small ✓, ● or ▲ near the clock — and choose
**Open dashboard…**. It opens in your browser.

If there is no menu bar icon, someone can start it once with:

```bash
python3 ~/ai-videos/daily/dashboard.py --open
```

The address looks like `http://127.0.0.1:55600/?t=…`. That long code at the end is an
access key. **Don't bookmark it** — it changes every time, and an old one stops working.
Always come in through the menu bar.

## What you see

**At the top — what it is doing.** If it is working, the stage it has reached and how
long it has been going. If last night failed, what stopped it and what to do. You can
close the browser at any point; it keeps working.

**Finish setting up.** Only appears while something is missing. Each line says exactly
what to do, and the one genuinely fiddly step — connecting YouTube — is a button.

**What it has published.** Every video, newest first. The coloured bar under each is the
fact-check:

> **green** claims confirmed · **gold** claims corrected · **red** claims cut

A little gold and red is a *good* sign — it means the checking is doing something. **Fact-check**
opens the full record: every claim, the source checked, and what was decided.

**Up next.** Type a topic and press Add. Anything you queue is made before the standing
subjects. A ▸ marks the ones going out tonight.

**What it will never cover.** Subjects to skip however good the story looks. Write them
the way you would say them — *"anything about crypto prices"* reads better than
*"crypto"*, because a language model reads this, not a keyword matcher. The × on a pill
allows the subject again.

**What it covers.** The subjects it works through every night. **Edit** to change what a
subject means, where it looks, and how long the video should be.

**Settings.** Videos per night, narrator, reading pace.

## Things worth knowing

**Videos per night.** Each takes about an hour, one after another. Three means it is still
working at breakfast. Start with one.

**Narrator.** Pick by ear. Changing the narrator also changes how fast it reads, which
would change how long each video runs — the dashboard adjusts the script length for you.
Voices marked *(uncalibrated)* have not been measured yet, so their videos may come out
slightly long or short until they are.

**Make one now.** Starts a video immediately. It refuses while one is already running,
because starting a second would destroy the first one's work.

**Nightly schedule.** The switch at the top. Off means nothing is made at all — useful
for a holiday.

## Editing what it covers

The **Edit** box is the most important control in the whole tool, because those words are
handed to the machine every night.

A good subject says three things:

1. **What to cover** — and what to ignore.
2. **Where to look** — name real sources.
3. **What counts as proof** — the strictest part, and the one that keeps the channel
   honest. For example: *every price must come from the company's own page, with the date
   you read it.*

If you have any connection to something it covers — you work there, own part of it, or
were paid by them — say so here and require that every video states it. The machine runs
unattended and will not work that out on its own.

There is more on this in [BEATS.md](BEATS.md).

## If it says your sign-in expired

This is the one thing that stops everything, and the only one the tool cannot fix
itself. Open Terminal, type `claude`, press return, then type `/login`. Come back and
press **Check sign-in**.

It happens every so often because the sign-in is time-limited. Nothing is lost — the
next run carries on.

## If something looks wrong

The status panel names the problem. Beyond that, **Open log** shows the raw record — not
meant to be readable, but it is the thing to send to whoever helps you.

Nothing is ever lost when a run fails. The work is saved and the next run picks it up.

## Is it private?

Yes. The dashboard runs on your own Mac and is reachable only from it — not from your
network, not from the internet. The access key in the address stops other websites in your
browser from talking to it. Nothing about your setup is sent anywhere.
