#!/usr/bin/env python3
"""
Menu bar indicator for the daily AI video job.

Shows, at a glance, whether the overnight run is working, finished, or broken:

    ●  running   (green, with elapsed time and current stage)
    ✓  published today
    ○  idle, waiting for tonight's 02:07 run
    ▲  failed — needs attention (red)

State comes from two places, deliberately:
  - $ROOT/daily/status.json           written by run-daily.sh at each transition
  - the newest workspace directory     inspected to infer the *stage* within a run

The second exists because run-daily.sh invokes `claude -p` as one opaque call and
cannot report its own progress from inside it. The artefacts appear on disk in a
known order, so the stage is read off the filesystem instead. If status.json is
missing or stale the indicator degrades to whatever the disk shows rather than lying.

Runs via com.dailyaivideo.daily-ai-video-menubar (login agent). Uses a contained venv at
$ROOT/.venv-menubar — nothing is installed system-wide.
"""

import json
import os
import sys
import subprocess
import time
from datetime import datetime, date

import AppKit
import Foundation
import objc
from PyObjCTools import AppHelper

HOME     = os.path.expanduser("~")
ROOT     = os.environ.get("DAILY_VIDEO_ROOT") or os.path.join(HOME, "ai-videos")
DAILY    = os.path.join(ROOT, "daily")
STATUS   = os.path.join(DAILY, "status.json")
LEDGER   = os.path.join(ROOT, "DAILY-LOG.md")
ATTENTION= os.path.join(ROOT, "NEEDS-ATTENTION.md")
TOPICS   = os.path.join(ROOT, "TOPICS.md")
CONFIG   = os.path.join(DAILY, "config.sh")
NEWVIDEO = os.path.join(DAILY, "new-video.sh")
BEATS_DIR= os.path.join(ROOT, "beats")
DASHBOARD= os.path.join(DAILY, "dashboard.py")
DASH_URL = os.path.join(DAILY, "dashboard.url")
PLIST    = os.path.join(HOME, "Library/LaunchAgents/com.dailyaivideo.daily-ai-video.plist")
LABEL    = "com.dailyaivideo.daily-ai-video"

# Most-advanced marker wins; order matters.
STAGES = [
    ("videos",          "rendering video"),
    ("wav",             "rendering audio"),
    ("mp3",             "rendering audio"),
    ("verification.md", "fact-checking claims"),
    ("narration",       "writing narration"),
    ("writeup.md",      "drafting"),
    ("research",        "researching"),
]

SKIP_DIRS = {"daily", "logs"}


def read_status():
    try:
        with open(STATUS) as fh:
            return json.load(fh)
    except Exception:
        return {}


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def published_slugs():
    """Slugs already published, per the ledger. Read fresh each refresh."""
    out = set()
    try:
        for line in open(LEDGER):
            if "youtu.be/" in line:
                for part in line.split("|"):
                    part = part.strip()
                    if "(" in part and part.endswith(")"):
                        out.add(part[part.rfind("(") + 1:-1])
    except OSError:
        pass
    return out


def newest_workspace():
    """The most recently touched workspace that has NOT already been published.

    Purging a finished workspace updates its mtime, so a plain newest-mtime pick
    reported a published-and-purged run as the one in progress — the indicator claimed
    "fact-checking claims" on a video that was already live. Skip anything the ledger
    records a URL for.
    """
    done = published_slugs()
    best, best_mtime = None, 0
    try:
        for name in os.listdir(ROOT):
            if name.startswith(".") or name in SKIP_DIRS or name in done:
                continue
            path = os.path.join(ROOT, name)
            if not os.path.isdir(path):
                continue
            m = os.path.getmtime(path)
            if m > best_mtime:
                best, best_mtime = path, m
    except OSError:
        pass
    return best


def infer_stage(ws):
    if not ws:
        return "starting up"
    for marker, label in STAGES:
        if os.path.exists(os.path.join(ws, marker)):
            return label
    return "starting up"


def published_today():
    today = date.today().isoformat()
    try:
        for line in open(LEDGER):
            if line.startswith(today) and "youtu.be/" in line:
                return True
    except OSError:
        pass
    return False


def pending_topics():
    """The pending `- [ ]` topics in TOPICS.md, in the order they will be built."""
    out = []
    try:
        for l in open(TOPICS):
            l = l.strip()
            if l.startswith("- [ ]"):
                t = l.split("]", 1)[1].strip()
                if t:
                    out.append(t)
    except OSError:
        pass
    return out


def beats():
    """Standing beats, in slot order: [(name, runtime_min)]."""
    out = []
    try:
        for f in sorted(os.listdir(BEATS_DIR)):
            if not f.endswith(".md"):
                continue
            rt = 30
            try:
                for line in open(os.path.join(BEATS_DIR, f)):
                    if line.startswith("RUNTIME_MIN:"):
                        rt = int(line.split(":", 1)[1].strip())
                        break
            except (OSError, ValueError):
                pass
            name = f[:-3].split("-", 1)[-1].replace("-", " ")
            out.append((name, rt))
    except OSError:
        pass
    return out


def config_value(key, default=""):
    """Read a KEY=value out of config.sh without executing it."""
    try:
        for line in open(CONFIG):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].split("#")[0].strip().strip('"\'')
    except OSError:
        pass
    return default


def schedule_loaded():
    """True if the 02:07 job is loaded.

    Must match the label EXACTLY. `com.dailyaivideo.daily-ai-video` is a prefix of both
    `...-check` and `...-menubar`, so a substring test reports the schedule as loaded
    even while it is paused — which is precisely the state the user needs to see.
    `launchctl list` prints PID<TAB>STATUS<TAB>LABEL, so compare the final field.
    """
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
        return any(line.split("\t")[-1].strip() == LABEL for line in out.splitlines())
    except Exception:
        return True


def human_elapsed(started):
    try:
        t0 = datetime.fromisoformat(started)
    except Exception:
        return ""
    secs = int((datetime.now() - t0).total_seconds())
    if secs < 0:
        return ""
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


class Indicator(AppKit.NSObject):

    def init(self):
        self = objc.super(Indicator, self).init()
        if self is None:
            return None
        self.dash = None
        self.item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        self.menu = AppKit.NSMenu.alloc().init()
        self.item.setMenu_(self.menu)
        self.last_url = ""
        self.refresh_(None)
        self.timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            8.0, self, "refresh:", None, True)
        return self

    # ------------------------------------------------------------------ rendering
    # @objc.python_method keeps these as ordinary Python methods. Without it PyObjC
    # reads `set_title_` as the selector `set:title:` and rejects the signature.
    @objc.python_method
    def setTitleSpec(self, spec):
        glyph, colour, suffix = spec
        text = glyph + (f"  {suffix}" if suffix else "")
        attrs = {
            AppKit.NSForegroundColorAttributeName: colour,
            AppKit.NSFontAttributeName: AppKit.NSFont.menuBarFontOfSize_(0),
        }
        astr = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        self.item.button().setAttributedTitle_(astr)

    @objc.python_method
    def add(self, title, action=None, enabled=True, indent=0):
        it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            it.setTarget_(self)
        it.setEnabled_(enabled and action is not None)
        if indent:
            it.setIndentationLevel_(indent)
        self.menu.addItem_(it)
        return it

    @objc.python_method
    def sep(self):
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())

    def refresh_(self, _timer):
        st       = read_status()
        state    = st.get("state", "")
        running  = state == "running" and pid_alive(st.get("pid"))
        stalled  = state == "running" and not pid_alive(st.get("pid"))
        failed   = state == "failed" or os.path.exists(ATTENTION)
        done     = published_today()

        self.menu.removeAllItems()

        if running:
            ws      = newest_workspace()
            stage   = infer_stage(ws)
            elapsed = human_elapsed(st.get("started_at", ""))
            self.setTitleSpec(("●", AppKit.NSColor.systemGreenColor(), elapsed))
            self.add(f"Running — {stage}")
            if elapsed:
                self.add(f"Started {st.get('started_at','')[11:16]} · {elapsed} elapsed", indent=1)
            if ws:
                self.add(f"Workspace: {os.path.basename(ws)}", indent=1)
        elif stalled:
            self.setTitleSpec(("▲", AppKit.NSColor.systemOrangeColor(), "stalled"))
            self.add("Marked running, but the process is gone")
            self.add("Likely killed mid-run — check the log", indent=1)
        elif failed:
            self.setTitleSpec(("▲", AppKit.NSColor.systemRedColor(), ""))
            self.add("Failed — needs attention")
            reason = st.get("reason") or "see NEEDS-ATTENTION.md"
            self.add(reason, indent=1)
        elif done:
            self.setTitleSpec(("✓", AppKit.NSColor.systemGreenColor(), ""))
            self.add("Published today")
        else:
            self.setTitleSpec(("○", AppKit.NSColor.secondaryLabelColor(), ""))
            self.add("Idle — next run 02:07")

        self.sep()
        self.add("Open dashboard…", "openDashboard:")

        # Last published video, always useful.
        self.sep()
        url = st.get("last_url", "")
        if url:
            topic = (st.get("last_topic") or "last video")[:44]
            self.last_url = url
            self.add(f"▸ {topic}", "openLast:")
            self.add(f"{st.get('last_date','')} · {url}", "openLast:", indent=1)
        else:
            self.add("No published video recorded yet", enabled=False)

        self.sep()
        topics  = pending_topics()
        per_run = config_value("VIDEOS_PER_RUN", "1")
        voice   = config_value("VOICE", "af_heart")
        try:
            n_per_run = int(per_run)
        except ValueError:
            n_per_run = 1

        if topics:
            self.add(f"Queue — {len(topics)} pending, next {min(n_per_run, len(topics))} tonight:",
                     "openTopics:")
            for i, t in enumerate(topics[:6]):
                # Mark which ones actually get built on the next run.
                bullet = "▸" if i < n_per_run else "·"
                self.add(f"{bullet} {t[:52]}", "openTopics:", indent=1)
            if len(topics) > 6:
                self.add(f"… and {len(topics) - 6} more", "openTopics:", indent=1)
        else:
            bs = beats()
            if bs:
                self.add(f"Tonight — {min(n_per_run, len(bs))} standing beats:", "openBeats:")
                for i, (name, rt) in enumerate(bs[:n_per_run]):
                    self.add(f"▸ {name} · {rt} min", "openBeats:", indent=1)
                if len(bs) > n_per_run:
                    self.add(f"({len(bs) - n_per_run} more beat(s) not run tonight)",
                             "openBeats:", indent=1)
            else:
                self.add("Queue empty — topics auto-picked from AI news", "openTopics:")

        self.add("Add topic…", "addTopic:")
        self.add(f"{per_run}/night · voice {voice}", "openConfig:", indent=1)

        self.sep()
        if not schedule_loaded():
            self.add("⏸ Schedule PAUSED", enabled=False)
            self.add("Resume daily schedule", "toggleSchedule:")
        elif running:
            # Deliberately no "Run now" here — starting one would mean killing this one.
            self.add("Run in progress — leave it to finish", enabled=False)
            self.add("Pause daily schedule", "toggleSchedule:")
        else:
            self.add("Run now", "runNow:")
            self.add("Pause daily schedule", "toggleSchedule:")

        self.sep()
        self.add("Open today's log", "openLog:")
        self.add("Open ledger", "openLedger:")
        if os.path.exists(ATTENTION):
            self.add("Open NEEDS-ATTENTION", "openAttention:")
        self.sep()
        self.add("Quit indicator", "quit:")

    # -------------------------------------------------------------------- actions
    def openDashboard_(self, _):
        """Open the web dashboard, reusing the running server if there is one.

        Spawning a second server would mean a second port and a second token, so
        the URL is published to a file and reused while the process is alive.
        """
        alive = self.dash is not None and self.dash.poll() is None
        if alive and os.path.exists(DASH_URL):
            subprocess.Popen(["open", open(DASH_URL).read().strip()])
            return
        env = dict(os.environ, DAILY_VIDEO_ROOT=ROOT)
        try:
            self.dash = subprocess.Popen(
                ["/usr/bin/python3", DASHBOARD, "--open"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            subprocess.Popen(["osascript", "-e",
                              'display notification "Could not start the dashboard." '
                              'with title "Daily AI Video"'])

    def openLast_(self, _):
        if self.last_url:
            subprocess.Popen(["open", self.last_url])

    def openLog_(self, _):
        log = read_status().get("log") or os.path.join(
            DAILY, "logs", f"{date.today().isoformat()}.log")
        subprocess.Popen(["open", "-a", "TextEdit", log] if os.path.exists(log)
                         else ["open", os.path.join(DAILY, "logs")])

    def addTopic_(self, _):
        """Prompt for a topic and queue it.

        The dialog runs in a DETACHED osascript, never in this process — a modal
        dialog on the app's own event loop would freeze the indicator until it was
        dismissed. osascript's `quoted form of` handles the shell escaping, so a
        topic containing quotes or $ is passed through safely.
        """
        script = (
            'set r to display dialog "Add a topic to the queue:" default answer "" '
            'with title "Daily AI Video" buttons {"Cancel", "Add"} default button "Add"\n'
            'set t to text returned of r\n'
            'if t is not "" then do shell script '
            + '"%s " & quoted form of t' % NEWVIDEO
        )
        subprocess.Popen(["osascript", "-e", script])

    def openBeats_(self, _):
        subprocess.Popen(["open", BEATS_DIR])

    def openTopics_(self, _):
        subprocess.Popen(["open", "-a", "TextEdit", TOPICS])

    def openConfig_(self, _):
        subprocess.Popen(["open", "-a", "TextEdit", CONFIG])

    def openLedger_(self, _):
        subprocess.Popen(["open", "-a", "TextEdit", LEDGER])

    def openAttention_(self, _):
        subprocess.Popen(["open", "-a", "TextEdit", ATTENTION])

    def runNow_(self, _):
        """Start a run — but never on top of one already going.

        This used `kickstart -k`. The -k kills any running instance first, so clicking
        "Run now" during a run destroyed hours of finished work and restarted from
        scratch. That happened on 21 Aug 2026. No -k, and the item is not even offered
        while a run is live.
        """
        st = read_status()
        if st.get("state") == "running" and pid_alive(st.get("pid")):
            subprocess.Popen([
                "osascript", "-e",
                'display notification "A run is already in progress — leaving it alone." '
                'with title "Daily AI Video"'])
            return
        subprocess.Popen(["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"])
        self.refresh_(None)

    def toggleSchedule_(self, _):
        cmd = "unload" if schedule_loaded() else "load"
        subprocess.run(["launchctl", cmd, PLIST], capture_output=True)
        self.refresh_(None)

    def quit_(self, _):
        AppKit.NSApp.terminate_(self)


def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # no Dock icon
    indicator = Indicator.alloc().init()
    app.setDelegate_(indicator)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    # `menubar.py --dump` builds the menu exactly as the live app does and prints it,
    # then exits. Lets the menu be verified without Accessibility permissions, and is
    # the fastest way to see what the indicator would be showing right now.
    if "--dump" in sys.argv:
        _app = AppKit.NSApplication.sharedApplication()
        _app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        _ind = Indicator.alloc().init()
        title = _ind.item.button().attributedTitle().string()
        print("menu bar title: %r" % title)
        for _it in _ind.menu.itemArray():
            if _it.isSeparatorItem():
                print("  " + "-" * 40)
            else:
                print("  " + "    " * _it.indentationLevel() + (_it.title() or ""))
        sys.exit(0)
    main()
