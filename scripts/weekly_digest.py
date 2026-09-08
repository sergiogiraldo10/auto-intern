#!/usr/bin/env python3
"""Sends a weekly summary email to yourself, replacing the old Claude-routine
Weekly Digest (which used a push notification and read the Artifact db --
both gone now that applications live in Supabase and the routines don't hold
Supabase credentials). Uses the same Gmail OAuth credential as
gmail_status_watcher.py, just the send scope instead of readonly.

Requires: google-auth-oauthlib, google-api-python-client
(pip install -r scripts/requirements.txt). Reads SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY and GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET /
GMAIL_REFRESH_TOKEN from the environment.

Usage:
    python scripts/weekly_digest.py
"""
import datetime
import json

import supabase_client as sb
from gmail_client import gmail_service, send_email

DIGEST_TO = "sergiogiraldo222@gmail.com"
TERMINAL_STATUSES = {"Rejected", "Ghosted", "Withdrawn"}


def build_digest_text(apps: list) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    week_ago = now - datetime.timedelta(days=7)

    active = [a for a in apps if a["status"] not in TERMINAL_STATUSES]
    added_this_week = [a for a in apps if a.get("date_applied") and
                        datetime.datetime.fromisoformat(a["date_applied"]).replace(tzinfo=datetime.timezone.utc) >= week_ago]
    changed_this_week = [a for a in apps if a.get("last_updated") and
                         datetime.datetime.fromisoformat(a["last_updated"].replace("Z", "+00:00")) >= week_ago]

    by_status = {}
    for a in apps:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1

    lines = [
        f"Weekly application digest -- {now.strftime('%B %d, %Y')}",
        "",
        f"Total applications: {len(apps)} ({len(active)} active, {len(apps) - len(active)} closed out)",
        "",
        "By status:",
    ]
    for status, count in sorted(by_status.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {status}: {count}")

    lines.append("")
    lines.append(f"New applications logged this week: {len(added_this_week)}")
    for a in added_this_week:
        lines.append(f"  - {a['company']} ({a['role']})")

    lines.append("")
    lines.append(f"Status changes this week: {len(changed_this_week)}")
    for a in changed_this_week:
        lines.append(f"  - {a['company']}: now {a['status']}")

    if not added_this_week and not changed_this_week:
        lines.append("")
        lines.append("Quiet week -- no new applications or status changes.")

    return "\n".join(lines)


def main():
    base, headers = sb._base_headers()
    apps = json.loads(sb._request("GET", f"{base}/rest/v1/applications?select=*", headers))

    digest_text = build_digest_text(apps)
    service = gmail_service()
    send_email(service, DIGEST_TO, "Weekly application digest", digest_text)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta_base, meta_headers = sb._base_headers(prefer="return=representation,resolution=merge-duplicates")
    sb._request(
        "POST", f"{meta_base}/rest/v1/meta?on_conflict=key", meta_headers,
        {"key": "weekly_digest", "value": {"lastRunAt": now, "appsTotal": len(apps)}},
    )
    print(f"Sent weekly digest for {len(apps)} applications")


if __name__ == "__main__":
    main()
