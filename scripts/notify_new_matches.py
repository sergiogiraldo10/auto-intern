#!/usr/bin/env python3
"""Emails a summary of newly-added leads right after a match-finder run, so a
new match doesn't just sit unnoticed on the tracker until you happen to check
it or the weekly digest comes around. Unlike the weekly digest, sends
NOTHING when there's nothing new -- a "no new matches" email every twice-
daily run isn't worth your inbox space the way a weekly liveness check is.

Usage:
    python scripts/notify_new_matches.py --leads-file scored_leads.json
"""
import argparse
import json

from gmail_client import gmail_service, send_email

DIGEST_TO = "sergiogiraldo222@gmail.com"
TRACKER_URL = "https://sergiogiraldo10.github.io/auto-intern/"


def build_email_text(leads: list) -> str:
    ranked = sorted(leads, key=lambda l: -(l.get("match_score") or 0))
    lines = [f"{len(leads)} new internship match{'es' if len(leads) != 1 else ''} found:", ""]
    for l in ranked:
        lines.append(f"{l['match_score']}% -- {l['company']} | {l['role']}")
        if l.get("match_reason"):
            lines.append(f"  {l['match_reason']}")
        if l.get("url"):
            lines.append(f"  {l['url']}")
        lines.append("")
    lines.append(f"Review and log applications at {TRACKER_URL}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leads-file", required=True, help="Path to scored_leads.json from match_internships.py")
    args = parser.parse_args()

    with open(args.leads_file, encoding="utf-8") as f:
        leads = json.load(f)

    if not leads:
        print("no new leads -- nothing to email")
        return

    service = gmail_service()
    send_email(service, DIGEST_TO, f"{len(leads)} new internship match(es)", build_email_text(leads))
    print(f"emailed summary of {len(leads)} new lead(s)")


if __name__ == "__main__":
    main()
