#!/usr/bin/env python3
"""Checks Gmail for status-change emails on non-terminal applications and
updates their status in Supabase -- the GitHub Actions replacement for the
old Claude-routine Email Watcher (which read the Artifact db and searched
Gmail via the Claude connector). Deliberately keyword-based, not an LLM's
reading of the email: same "mirror what a real ATS parser does" reasoning as
scripts/match_internships.py, and it means a bare Google API credential
(no LLM in the loop) never has to sit next to untrusted email content --
see README.md for why that split matters.

Requires: google-auth-oauthlib, google-api-python-client, beautifulsoup4
(pip install -r scripts/requirements.txt). Reads SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY (via scripts/supabase_client.py) and GMAIL_CLIENT_ID
/ GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN (see scripts/gmail_oauth_setup.py
for how the refresh token is produced) from the environment.

Usage:
    python scripts/gmail_status_watcher.py
"""
import base64
import datetime
import json
import os
import sys

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import supabase_client as sb

# Statuses with nothing left to detect from email -- Rejected/Ghosted/
# Withdrawn are dead ends, Offer is the top of the forward chain (anything
# past it, e.g. a rescinded offer, is rare enough to handle manually).
TERMINAL_STATUSES = {"Rejected", "Ghosted", "Withdrawn", "Offer"}

STAGE_ORDER = {"Applied": 0, "Assessment": 1, "Video Interview": 2, "Interview": 3, "Offer": 4}

# Checked in this order per email; first match wins for THAT email. Rejection
# is handled separately (as an override), not as a forward stage.
REJECTED_KEYWORDS = [
    "will not be moving forward with your application",
    "will not be moving forward with your candidacy",
    "not be moving forward with your application",
    "your application will not be moving forward",
    "have decided to move forward with other candidates",
    "decided to pursue other candidates",
    "have decided not to move forward with your candidacy",
    "have decided not to move forward with your application",
    "not been selected for this position",
    "not been selected for this role",
    "we regret to inform you",
    "unable to offer you a position at this time",
    "will not be extending an offer to you",
]
OFFER_KEYWORDS = [
    "pleased to offer", "extend an offer", "offer of employment",
    "official offer", "excited to offer you",
]
INTERVIEW_KEYWORDS = [
    "schedule your interview", "phone interview", "technical interview",
    "interview invitation", "like to interview", "next round", "final round",
    "onsite interview", "virtual interview", "schedule an interview",
]
# One-way/async recorded video screens -- distinct from a live "Interview"
# above, regardless of vendor (HireVue, Spark Hire, Modern Hire, VidCruiter,
# ...). Checked before the generic Interview keywords so e.g. a Spark Hire
# "interview invitation" lands here, not in the live-interview bucket.
VIDEO_INTERVIEW_KEYWORDS = [
    "hirevue", "hire vue", "spark hire", "sparkhire", "modern hire",
    "vidcruiter", "pre-recorded video interview", "pre-recorded interview",
    "one-way interview", "one-way video interview", "recorded video interview",
    "asynchronous interview",
]
ASSESSMENT_KEYWORDS = [
    "online assessment", "coding assessment", "coding challenge",
    "hackerrank", "codesignal", "coderpad", "complete your assessment",
    "assessment invitation", "complete the following assessment",
]

# Precedence for classifying ONE email when more than one category's keywords
# appear in it -- e.g. a Spark Hire email's boilerplate also says "interview
# invitation" somewhere, but "spark hire" is the unambiguous signal and must
# win over that generic phrase. This is deliberately NOT stage-order: Video
# Interview sits below Interview in STAGE_ORDER (for comparing across
# different emails), but a vendor-specific match always outranks a generic
# one within a single email.
MESSAGE_PRECEDENCE = [
    ("Offer", OFFER_KEYWORDS),
    ("Video Interview", VIDEO_INTERVIEW_KEYWORDS),
    ("Assessment", ASSESSMENT_KEYWORDS),
    ("Interview", INTERVIEW_KEYWORDS),
]


def classify_message(text: str):
    """Classifies ONE email's text. Returns (status, matched_keyword) or
    (None, None). Rejection is checked first since it overrides everything."""
    for kw in REJECTED_KEYWORDS:
        if kw in text:
            return "Rejected", kw
    for name, keywords in MESSAGE_PRECEDENCE:
        for kw in keywords:
            if kw in text:
                return name, kw
    return None, None


def gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode(data: str) -> str:
    pad = -len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * pad).decode("utf-8", errors="replace")


def extract_body(payload: dict) -> str:
    plain, html = None, None

    def walk(part):
        nonlocal plain, html
        data = part.get("body", {}).get("data")
        mime = part.get("mimeType", "")
        if data and mime == "text/plain" and plain is None:
            plain = _decode(data)
        elif data and mime == "text/html" and html is None:
            html = _decode(data)
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if plain:
        return plain
    if html:
        return BeautifulSoup(html, "html.parser").get_text(separator=" ")
    return ""


def get_message_text(service, msg_id: str) -> str:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    return headers.get("Subject", "") + "\n" + extract_body(msg["payload"])


def classify_status(service, company: str, date_applied: str):
    """Returns (new_status, matched_keyword) or (None, None) if no
    forward/terminal signal was found in any matching email."""
    query = f'"{company}" after:{date_applied.replace("-", "/")}'
    try:
        resp = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
    except HttpError as e:
        print(f"  Gmail search failed for {company}: {e}", file=sys.stderr)
        return None, None

    best_status, best_order, best_kw = None, -1, None
    for m in resp.get("messages", []):
        try:
            text = get_message_text(service, m["id"]).lower()
        except HttpError as e:
            print(f"  Gmail fetch failed for {company} message {m['id']}: {e}", file=sys.stderr)
            continue

        name, kw = classify_message(text)
        if name == "Rejected":
            return "Rejected", kw  # terminal -- no need to keep scanning
        if name and STAGE_ORDER[name] > best_order:
            best_status, best_order, best_kw = name, STAGE_ORDER[name], kw

    return best_status, best_kw


def write_job_summary(text: str):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def main():
    base, headers = sb._base_headers()
    apps = json.loads(sb._request("GET", f"{base}/rest/v1/applications?select=*", headers))

    checked = 0
    updates = []
    service = gmail_service()

    for app in apps:
        if app["status"] in TERMINAL_STATUSES:
            continue
        checked += 1
        current_order = STAGE_ORDER.get(app["status"], 0)
        print(f"Checking {app['company']} ({app['status']})...", file=sys.stderr)
        new_status, keyword = classify_status(service, app["company"], app["date_applied"])

        if new_status is None:
            continue
        if new_status != "Rejected" and STAGE_ORDER[new_status] <= current_order:
            continue  # never downgrade a forward stage
        if new_status == app["status"]:
            continue

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        note_addition = f'Auto-detected via Gmail on {now[:10]}: matched "{keyword}"'
        new_notes = f"{app['notes']} | {note_addition}" if app.get("notes") else note_addition

        patch_base, patch_headers = sb._base_headers(prefer="return=representation")
        sb._request(
            "PATCH",
            f"{patch_base}/rest/v1/applications?id=eq.{app['id']}",
            patch_headers,
            {"status": new_status, "notes": new_notes, "last_updated": now},
        )
        updates.append({"company": app["company"], "from": app["status"], "to": new_status})
        print(f"  -> {app['status']} to {new_status} (matched \"{keyword}\")", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta_base, meta_headers = sb._base_headers(prefer="return=representation,resolution=merge-duplicates")
    sb._request(
        "POST",
        f"{meta_base}/rest/v1/meta?on_conflict=key",
        meta_headers,
        {"key": "status_watcher", "value": {
            "lastRunAt": now, "appsChecked": checked, "newUpdatesCount": len(updates),
            "summary": "; ".join(f"{u['company']}: {u['from']} -> {u['to']}" for u in updates) or "no changes",
        }},
    )

    write_job_summary(
        "### Email Status Watcher\n"
        f"- Applications checked: {checked}\n"
        f"- Status updates found: {len(updates)}\n"
        + "".join(f"  - {u['company']}: {u['from']} → {u['to']}\n" for u in updates)
    )
    print(f"Checked {checked} applications, {len(updates)} status update(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
