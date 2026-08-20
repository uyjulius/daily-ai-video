#!/usr/bin/env python3
"""One-time OAuth consent for the YouTube Data API.

Usage: ~/.venv-ytapi/bin/python yt_auth.py [client_secret.json]

Picks the newest Desktop-type client secret in ~/Downloads if no path is given
(Desktop clients have a client_secret field; Android/iOS exports do not and
cannot do the localhost flow). Opens the browser for consent — the account
owner approves, choosing the intended channel identity if prompted.
Token is cached at ~/.config/topic-to-youtube/token.json and auto-refreshes.
"""
import glob
import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube"]
TOKEN = os.path.expanduser("~/.config/topic-to-youtube/token.json")


def pick_client():
    if len(sys.argv) > 1:
        return sys.argv[1]
    cands = []
    for f in glob.glob(os.path.expanduser("~/Downloads/client_secret*.json")):
        try:
            k = json.load(open(f)).get("installed") or {}
            if k.get("client_secret"):
                cands.append((os.path.getmtime(f), f))
        except Exception:
            pass
    if not cands:
        raise SystemExit("No Desktop-type client_secret*.json (with a client_secret field) in ~/Downloads")
    return max(cands)[1]


client = pick_client()
print("Using client:", client, flush=True)
flow = InstalledAppFlow.from_client_secrets_file(client, SCOPES)
creds = flow.run_local_server(port=0, open_browser=True,
                              authorization_prompt_message="CONSENT_URL: {url}")
os.makedirs(os.path.dirname(TOKEN), exist_ok=True)
with open(TOKEN, "w") as f:
    f.write(creds.to_json())
# remember which client the token belongs to, for refresh
with open(TOKEN + ".client", "w") as f:
    f.write(client)
print("TOKEN SAVED", TOKEN)
