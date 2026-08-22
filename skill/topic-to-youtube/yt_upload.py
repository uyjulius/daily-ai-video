#!/usr/bin/env python3
"""Upload videos to YouTube via the Data API (resumable, chunked).

Usage:
  ~/.venv-ytapi/bin/python yt_upload.py <video.mp4> --title "..." [--description-file f]
      [--tags "a, b"] [--playlist "Name"] [--privacy public|unlisted|private]
      [--category 27] [--check-lock]

Requires a token from yt_auth.py at ~/.config/topic-to-youtube/token.json.

IMPORTANT: uploads from an API project that has not passed YouTube's compliance
audit are FORCED PRIVATE ("Video locked") regardless of the requested privacy.
Run the first upload with --check-lock: it polls the final privacyStatus and
prints LOCKED_PRIVATE if YouTube overrode it — in that case use the browser
chunk-relay path for public publishing and request an audit at
https://support.google.com/youtube/contact/yt_api_form
"""
import argparse
import os
import socket
import ssl
import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# A multi-GB upload will hit at least one transient network fault. next_chunk()
# raises instead of resuming, which loses the whole transfer, so every chunk is
# retried against the same request object (it holds the resumable session URI,
# so the server resumes from its own recorded offset rather than from zero).
RETRYABLE = (BrokenPipeError, ConnectionError, socket.timeout, ssl.SSLError,
             OSError, HttpError)

TOKEN = os.path.expanduser("~/.config/topic-to-youtube/token.json")


def service():
    creds = Credentials.from_authorized_user_file(TOKEN)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def ensure_playlist(yt, title):
    resp = yt.playlists().list(part="id,snippet", mine=True, maxResults=50).execute()
    for p in resp.get("items", []):
        if p["snippet"]["title"] == title:
            return p["id"]
    created = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title}, "status": {"privacyStatus": "public"}}).execute()
    return created["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description-file")
    ap.add_argument("--tags", default="")
    ap.add_argument("--playlist")
    ap.add_argument("--privacy", default="public")
    ap.add_argument("--category", default="27")
    ap.add_argument("--check-lock", action="store_true")
    ap.add_argument("--thumbnail", help="PNG/JPG to set as the custom thumbnail")
    a = ap.parse_args()

    yt = service()
    desc = open(a.description_file).read() if a.description_file else ""
    body = {
        "snippet": {"title": a.title, "description": desc,
                     "tags": [t.strip() for t in a.tags.split(",") if t.strip()],
                     "categoryId": a.category, "defaultLanguage": "en",
                     "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": a.privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(a.video, mimetype="video/mp4",
                            chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    print(f"uploading {os.path.getsize(a.video)/1e6:.0f} MB ...", flush=True)
    last, resp, fails = -1, None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk(num_retries=5)
            fails = 0
        except RETRYABLE as e:
            if isinstance(e, HttpError) and e.resp.status not in (500, 502, 503, 504, 408, 429):
                raise
            fails += 1
            if fails > 8:
                raise
            wait = min(60, 2 ** fails)
            print(f"  {type(e).__name__} — retry {fails}/8 in {wait}s", flush=True)
            time.sleep(wait)
            continue
        if status:
            pct = int(status.progress() * 100)
            if pct // 10 != last:
                last = pct // 10
                print(f"  {pct}%", flush=True)
    vid = resp["id"]
    print(f"uploaded: https://youtu.be/{vid}", flush=True)

    # Custom thumbnail. Without one YouTube picks a frame, which for this format is a
    # chapter slate whose text is unreadable at feed size. Never fatal: the video is
    # already public by this point, so a thumbnail failure must not fail the upload.
    if a.thumbnail and os.path.exists(a.thumbnail):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(a.thumbnail)).execute()
            print("thumbnail set", flush=True)
        except HttpError as e:
            # Unverified accounts cannot set thumbnails; say so rather than dying.
            print(f"thumbnail NOT set ({e.resp.status}) — the channel may need phone "
                  f"verification at youtube.com/verify", flush=True)

    if a.playlist:
        pid = ensure_playlist(yt, a.playlist)
        yt.playlistItems().insert(part="snippet", body={
            "snippet": {"playlistId": pid,
                         "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
        print(f"added to playlist: {a.playlist}", flush=True)

    st = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
    print(f"status: privacy={st['privacyStatus']} upload={st['uploadStatus']}", flush=True)

    if a.check_lock and a.privacy == "public":
        print("polling for privacy lock (up to 5 min)...", flush=True)
        for _ in range(10):
            time.sleep(30)
            st = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
            print(f"  privacy={st['privacyStatus']} upload={st['uploadStatus']}", flush=True)
            if st["uploadStatus"] == "processed":
                break
        if st["privacyStatus"] != "public":
            print("LOCKED_PRIVATE — project not audited; use browser upload for public "
                  "and request an audit: https://support.google.com/youtube/contact/yt_api_form")
            sys.exit(2)
        print("PUBLIC_OK")


if __name__ == "__main__":
    main()
