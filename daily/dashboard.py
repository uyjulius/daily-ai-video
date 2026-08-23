#!/usr/bin/env python3
"""Local web dashboard for the daily video pipeline.

Runs a small HTTP server bound to 127.0.0.1 and serves a single page that lets a
non-technical operator do everything the shell scripts do: check what happened last
night, read the fact-check record, change what gets covered, queue a topic, and adjust
settings — without a terminal.

    python3 daily/dashboard.py            # prints a URL with an access token
    python3 daily/dashboard.py --open     # and opens it

SECURITY
  - Binds 127.0.0.1 only. Never reachable from the network.
  - Every request must carry a token generated at startup, either as ?t= or as an
    X-Token header. Without it a page in your browser on some other site could POST
    to localhost and drive this thing; the token makes that impossible.
  - Config writes go through an allowlist with per-key validation, so nothing the
    browser sends can inject shell into config.sh.
"""
import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
ROOT = os.environ.get("DAILY_VIDEO_ROOT") or os.path.join(HOME, "ai-videos")
DAILY = os.path.join(ROOT, "daily")
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HOME, ".claude", "skills", "topic-to-youtube")

CONFIG = os.path.join(DAILY, "config.sh")
STATUS = os.path.join(DAILY, "status.json")
LEDGER = os.path.join(ROOT, "DAILY-LOG.md")
TOPICS = os.path.join(ROOT, "TOPICS.md")
EXCLUDE = os.path.join(ROOT, "EXCLUDE.md")
BEATS = os.path.join(ROOT, "beats")
ATTENTION = os.path.join(ROOT, "NEEDS-ATTENTION.md")
AUTH_STATE = os.path.join(DAILY, "auth.json")
TOKEN_FILE = os.path.join(HOME, ".config", "topic-to-youtube", "token.json")
LABEL = "com.dailyaivideo.run"

TOKEN = secrets.token_urlsafe(24)

# Voices with a MEASURED words-per-minute (real multi-paragraph chapters, pauses
# included). Anything not listed needs calibrating before its word budget is right.
VOICE_WPM = {"af_heart": 148, "am_liam": 167}
VOICES = [
    ("am_onyx", "Onyx", "Deepest — true bass register"),
    ("am_echo", "Echo", "Deep, slightly brighter"),
    ("am_adam", "Adam", "Warm, even"),
    ("am_liam", "Liam", "Deep, brisk delivery"),
    ("am_michael", "Michael", "Most deliberate reader"),
    ("am_fenrir", "Fenrir", "Lighter, energetic"),
    ("af_heart", "Heart", "Warm, measured"),
    ("af_bella", "Bella", "Bright, conversational"),
    ("bm_george", "George", "British, formal"),
    ("bm_fable", "Fable", "British, storyteller"),
    ("bf_emma", "Emma", "British, crisp"),
]

# key -> (kind, validator) — nothing outside this can be written to config.sh
CONFIG_KEYS = {
    "VIDEOS_PER_RUN": ("int", lambda v: 1 <= v <= 6),
    "VOICE": ("str", lambda v: re.fullmatch(r"[a-z]{2}_[a-z]+", v) is not None),
    "SPEED": ("float", lambda v: 0.7 <= v <= 1.3),
    "WPM": ("int", lambda v: 60 <= v <= 400),
    "MAX_TURNS": ("int", lambda v: 50 <= v <= 5000),
    "MAX_ATTEMPTS": ("int", lambda v: 1 <= v <= 10),
    "TTS_JOBS": ("int", lambda v: 1 <= v <= 32),
    "TTS_THREADS": ("int", lambda v: 1 <= v <= 16),
    "MP3_JOBS": ("int", lambda v: 1 <= v <= 32),
}


# ----------------------------------------------------------------------- readers
def read_config():
    out = {}
    try:
        for line in open(CONFIG):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m and m.group(1) in CONFIG_KEYS:
                out[m.group(1)] = m.group(2).split("#")[0].strip().strip("\"'")
    except OSError:
        pass
    return out


def write_config(key, value):
    """Rewrite one KEY= line. Allowlisted and type-checked before it gets here."""
    kind, ok = CONFIG_KEYS[key]
    if kind == "int":
        value = int(value)
    elif kind == "float":
        value = float(value)
    else:
        value = str(value)
    if not ok(value):
        raise ValueError(f"{key} out of range")
    lines = open(CONFIG).read().splitlines() if os.path.exists(CONFIG) else []
    hit = False
    for i, l in enumerate(lines):
        if re.match(rf"^{key}=", l.strip()):
            lines[i] = f"{key}={value}"
            hit = True
            break
    if not hit:
        lines.append(f"{key}={value}")
    open(CONFIG, "w").write("\n".join(lines) + "\n")
    return value


def read_status():
    try:
        return json.load(open(STATUS))
    except Exception:
        return {}


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_ledger():
    """Ledger rows, newest first. Tolerates the informational lines too."""
    rows = []
    try:
        for line in open(LEDGER):
            if "youtu.be/" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            title = parts[1]
            slug = ""
            m = re.search(r"\(([^)]+)\)\s*$", title)
            if m:
                slug = m.group(1)
                title = title[:m.start()].strip()
            url = next((p for p in parts if p.startswith("http")), "")
            tally = {}
            for k, pat in (("checked", r"checked:\s*(\d+)"),
                           ("corrected", r"corrected:\s*(\d+)"),
                           ("cut", r"cut:\s*(\d+)")):
                mm = re.search(pat, line)
                if mm:
                    tally[k] = int(mm.group(1))
            rows.append({"date": parts[0], "title": title, "slug": slug, "url": url,
                         "runtime": parts[3] if len(parts) > 3 else "", "tally": tally})
    except OSError:
        pass
    return list(reversed(rows))


def read_topics():
    pend, done = [], []
    try:
        for l in open(TOPICS):
            s = l.strip()
            if s.startswith("- [ ]"):
                t = s[5:].strip()
                if t:
                    pend.append(t)
            elif s.startswith("- [x]"):
                done.append(s[5:].strip())
    except OSError:
        pass
    return pend, done[-8:]


def read_exclusions():
    out = []
    try:
        for l in open(EXCLUDE):
            l = l.strip()
            if l.startswith("- ") and l[2:].strip():
                out.append(l[2:].strip())
    except OSError:
        pass
    return out


def read_beats():
    out = []
    try:
        for f in sorted(os.listdir(BEATS)):
            if not f.endswith(".md"):
                continue
            raw = open(os.path.join(BEATS, f)).read()
            rt = 30
            m = re.search(r"^RUNTIME_MIN:\s*(\d+)", raw, re.M)
            if m:
                rt = int(m.group(1))
            body = raw.split("---", 1)[1].strip() if "---" in raw else raw
            summary = ""
            ms = re.search(r"^BEAT:\s*(.+?)(?:\n\n|\nWHERE)", body, re.S | re.M)
            if ms:
                summary = " ".join(ms.group(1).split())
            out.append({"file": f, "name": f[:-3].split("-", 1)[-1].replace("-", " "),
                        "runtime": rt, "summary": summary, "body": body})
    except OSError:
        pass
    return out


def schedule_on():
    try:
        o = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
        return any(l.split("\t")[-1].strip() == LABEL for l in o.splitlines())
    except Exception:
        return False


def infer_stage():
    """Which stage the running video is in, read off the artefacts on disk."""
    done_slugs = {r["slug"] for r in read_ledger() if r["slug"]}
    best, best_m = None, 0
    try:
        for n in os.listdir(ROOT):
            if n.startswith(".") or n in ("daily", "beats", "logs") or n in done_slugs:
                continue
            p = os.path.join(ROOT, n)
            if os.path.isdir(p) and os.path.getmtime(p) > best_m:
                best, best_m = p, os.path.getmtime(p)
    except OSError:
        pass
    if not best:
        return None, None
    for marker, label in (("videos", "Rendering video"), ("wav", "Recording narration"),
                          ("mp3", "Recording narration"), ("verification.md", "Checking the facts"),
                          ("narration", "Writing the script"), ("research", "Reading sources")):
        if os.path.exists(os.path.join(best, marker)):
            return os.path.basename(best), label
    return os.path.basename(best), "Starting up"


def auth_state():
    """What the last run found. Never probes on its own — the dashboard refreshes
    every 20s and a live check per refresh would be an API call per refresh."""
    try:
        d = json.load(open(AUTH_STATE))
        return bool(d.get("ok")), d.get("checked_at", "")
    except Exception:
        return None, ""


def auth_probe():
    """One live round-trip, only when the operator asks for it."""
    try:
        r = subprocess.run(["claude", "-p", "Reply with the single word: ok",
                            "--max-turns", "1", "--output-format", "text"],
                           capture_output=True, text=True, timeout=90)
        out = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0 and not re.search(
            r"Failed to authenticate|OAuth session expired|Invalid API key", out, re.I)
    except Exception:
        ok = False
    try:
        os.makedirs(DAILY, exist_ok=True)
        json.dump({"ok": ok, "checked_at": __import__("datetime").datetime.now()
                   .isoformat(timespec="seconds")}, open(AUTH_STATE, "w"))
    except OSError:
        pass
    return ok


def health():
    """Plain-language setup checks. Each item says what to do if it is not ready."""
    def have(cmd):
        return subprocess.run(["which", cmd], capture_output=True).returncode == 0
    items = [
        ("Video tools", have("ffmpeg"),
         "Install ffmpeg: open Terminal and run  brew install ffmpeg"),
        ("Claude Code", have("claude"),
         "Install Claude Code from claude.com/claude-code, then sign in"),
        ("Claude sign-in", auth_state()[0] is not False,
         "Your Claude session expired. Open Terminal, run  claude  then type /login"),
        ("Google Chrome", os.path.isdir("/Applications/Google Chrome.app"),
         "Install Google Chrome — it is used to draw the title cards"),
        ("Narration engine", os.path.exists(os.path.join(ROOT, ".venv-tts", "bin", "python")),
         "Run ./install.sh from the project folder"),
        ("YouTube connection", os.path.exists(TOKEN_FILE),
         "Connect YouTube below — this is the one step that needs you"),
        ("Nightly schedule", schedule_on(),
         "Turn the schedule on using the switch at the top"),
    ]
    wake = False
    try:
        wake = "wakepoweron" in subprocess.run(["pmset", "-g", "sched"],
                                               capture_output=True, text=True, timeout=5).stdout
    except Exception:
        pass
    items.append(("Mac wakes for it", wake,
                  "Open Terminal and run:  sudo pmset repeat wakeorpoweron MTWRFSU 02:07:00"))
    return [{"name": n, "ok": bool(o), "fix": f} for n, o, f in items]


def state():
    st = read_status()
    running = st.get("state") == "running" and pid_alive(st.get("pid"))
    slug, stage = infer_stage() if running else (None, None)
    cfg = read_config()
    pend, done = read_topics()
    voice = cfg.get("VOICE", "af_heart")
    return {
        "running": running,
        "failed": (not running) and (st.get("state") == "failed" or os.path.exists(ATTENTION)),
        "reason": st.get("reason", ""),
        "started_at": st.get("started_at", ""),
        "stage": stage, "slug": slug,
        "schedule_on": schedule_on(),
        "config": cfg,
        "voice_measured": voice in VOICE_WPM,
        "voices": [{"id": v, "name": n, "note": d, "measured": v in VOICE_WPM} for v, n, d in VOICES],
        "beats": read_beats(),
        "topics": pend, "topics_done": done,
        "exclusions": read_exclusions(),
        "ledger": read_ledger(),
        "health": health(),
        "attention": open(ATTENTION).read() if os.path.exists(ATTENTION) else "",
        "auth": {"ok": auth_state()[0], "checked_at": auth_state()[1]},
        "root": ROOT,
    }


# ---------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authed(self):
        q = urllib.parse.urlparse(self.path).query
        t = urllib.parse.parse_qs(q).get("t", [""])[0] or self.headers.get("X-Token", "")
        return secrets.compare_digest(t, TOKEN)

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/" :
            if not self._authed():
                return self._send(403, "<h1>Open this from the menu bar</h1>"
                                       "<p>The dashboard needs its one-time access link.</p>",
                                  "text/html; charset=utf-8")
            page = open(os.path.join(HERE, "dashboard.html")).read()
            page = page.replace("__TOKEN__", TOKEN)
            return self._send(200, page, "text/html; charset=utf-8")
        if not self._authed():
            return self._send(403, json.dumps({"error": "bad token"}))
        if path == "/api/state":
            return self._send(200, json.dumps(state()))
        if path == "/api/verification":
            slug = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("slug", [""])[0]
            f = os.path.join(ROOT, os.path.basename(slug), "verification.md")
            if not os.path.exists(f):
                return self._send(404, json.dumps({"error": "No fact-check record was kept for this one."}))
            return self._send(200, json.dumps({"text": open(f).read()}))
        if path == "/api/log":
            import glob
            fs = sorted(glob.glob(os.path.join(DAILY, "logs", "*.log")))
            txt = open(fs[-1]).read()[-20000:] if fs else "No log yet."
            return self._send(200, json.dumps({"text": txt}))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._authed():
            return self._send(403, json.dumps({"error": "bad token"}))
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, json.dumps({"error": "bad request"}))
        try:
            return self._send(200, json.dumps(self._act(path, data)))
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}))

    def _act(self, path, d):
        if path == "/api/topic/add":
            t = (d.get("text") or "").strip()
            if not t:
                raise ValueError("Type a topic first.")
            if not os.path.exists(TOPICS):
                open(TOPICS, "w").write("# Topic queue\n\n## Queue\n\n")
            with open(TOPICS, "a") as f:
                f.write(f"- [ ] {t}\n")
            return {"ok": True}
        if path == "/api/topic/remove":
            t = (d.get("text") or "").strip()
            lines = open(TOPICS).read().splitlines()
            out = [l for l in lines if not (l.strip().startswith("- [ ]") and l.strip()[5:].strip() == t)]
            open(TOPICS, "w").write("\n".join(out) + "\n")
            return {"ok": True}
        if path == "/api/exclude/add":
            t = (d.get("text") or "").strip()
            if not t:
                raise ValueError("Type a subject first.")
            if not os.path.exists(EXCLUDE):
                open(EXCLUDE, "w").write("# Do not cover these\n\n## Rules\n\n")
            with open(EXCLUDE, "a") as f:
                f.write(f"- {t}\n")
            return {"ok": True}
        if path == "/api/exclude/remove":
            t = (d.get("text") or "").strip()
            lines = open(EXCLUDE).read().splitlines()
            out = [l for l in lines if not (l.strip().startswith("- ") and l.strip()[2:].strip() == t)]
            open(EXCLUDE, "w").write("\n".join(out) + "\n")
            return {"ok": True}
        if path == "/api/config":
            key, val = d.get("key"), d.get("value")
            if key not in CONFIG_KEYS:
                raise ValueError("That setting cannot be changed here.")
            written = write_config(key, val)
            # Picking a voice sets the word budget too, so the operator never has to.
            if key == "VOICE" and written in VOICE_WPM:
                speed = float(read_config().get("SPEED", 1.0) or 1.0)
                write_config("WPM", int(round(VOICE_WPM[written] * speed)))
            if key == "SPEED":
                v = read_config().get("VOICE", "")
                if v in VOICE_WPM:
                    write_config("WPM", int(round(VOICE_WPM[v] * float(written))))
            return {"ok": True, "config": read_config()}
        if path == "/api/beat":
            f = os.path.basename(d.get("file", ""))
            if not f.endswith(".md"):
                raise ValueError("Not a beat file.")
            body = d.get("body", "")
            rt = int(d.get("runtime", 30))
            if not 5 <= rt <= 120:
                raise ValueError("Length must be between 5 and 120 minutes.")
            open(os.path.join(BEATS, f), "w").write(f"RUNTIME_MIN: {rt}\n---\n{body.strip()}\n")
            return {"ok": True}
        if path == "/api/run":
            st = read_status()
            if st.get("state") == "running" and pid_alive(st.get("pid")):
                raise ValueError("It is already working. Let it finish.")
            subprocess.Popen(["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"])
            return {"ok": True}
        if path == "/api/schedule":
            plist = os.path.join(HOME, "Library", "LaunchAgents", f"{LABEL}.plist")
            subprocess.run(["launchctl", "load" if d.get("on") else "unload", plist],
                           capture_output=True)
            return {"ok": True, "on": schedule_on()}
        if path == "/api/check-auth":
            return {"ok": auth_probe()}
        if path == "/api/connect-youtube":
            py = os.path.join(HOME, ".venv-ytapi", "bin", "python")
            script = os.path.join(SKILL, "yt_auth.py")
            if not os.path.exists(py) or not os.path.exists(script):
                raise ValueError("Run ./install.sh first.")
            subprocess.Popen([py, script])
            return {"ok": True}
        raise ValueError("Unknown action")


URL_FILE = os.path.join(DAILY, "dashboard.url")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"
    print(url, flush=True)
    # Written so the menu bar can reopen this same server rather than starting a
    # second one. Contains the access token, so it is owner-readable only.
    try:
        os.makedirs(DAILY, exist_ok=True)
        fd = os.open(URL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(url)
    except OSError:
        pass
    if "--open" in sys.argv:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(URL_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
