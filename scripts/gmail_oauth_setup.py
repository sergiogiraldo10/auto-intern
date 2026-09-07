#!/usr/bin/env python3
"""One-time LOCAL script: turns a Gmail OAuth Desktop-app client id/secret into
a refresh token for the auto-intern email pipeline. Run this once, on your own
machine only -- never in GitHub Actions or a Claude routine, since it opens a
real browser window for you to approve access on sergiogiraldo222@gmail.com.
It prints the refresh token to your terminal; nothing is written to disk.

That printed token is the only one of the three Gmail values that also needs
to become a GitHub Actions secret (GMAIL_REFRESH_TOKEN) -- the client id and
secret stay as repository secrets too, but this script itself never touches
GitHub; it only talks to Google's OAuth endpoints.

Requires: google-auth-oauthlib, google-api-python-client
    pip install -r scripts/requirements.txt

Usage (client id/secret via env -- never hardcode them here or paste them
into chat):
    set -a; source .env; set +a   # must define GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET
    python scripts/gmail_oauth_setup.py
"""
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

# readonly: search/read status-update emails for the watcher workflow.
# send: let the weekly-digest workflow email a summary to yourself, since a
# GitHub Actions script can't fire the Claude push notification the old
# routine used.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def main():
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("error: set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in the environment first", file=sys.stderr)
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("Opening a browser -- sign in as sergiogiraldo222@gmail.com and approve access.")
    # access_type=offline + prompt=consent force a refresh token every run;
    # without prompt=consent, Google silently omits it on a second+ approval
    # of the same client (only the very first consent gets one otherwise).
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print(
            "error: no refresh token returned. Go to "
            "https://myaccount.google.com/permissions, remove this app's access, "
            "then run this script again.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nSuccess. Save this as the GMAIL_REFRESH_TOKEN GitHub Actions secret:\n")
    print(creds.refresh_token)


if __name__ == "__main__":
    main()
