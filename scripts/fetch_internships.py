#!/usr/bin/env python3
"""Fetch new internship postings from the SimplifyJobs open-source listing feed.

Data source: https://github.com/SimplifyJobs/Summer2027-Internships (community-maintained,
updated many times a day, public JSON meant for machine consumption). Pure filtering/dedup
logic lives here; judging resume fit against each posting's full description is left to
whatever calls this script, since that needs to read prose, not just structured fields.

Usage:
    python fetch_internships.py [--since-days N] [--seen-ids-file PATH] [--out PATH]

Prints a JSON array of candidate postings to stdout (or writes to --out).
"""
import argparse
import json
import sys
import time
import urllib.request
from urllib.error import URLError

LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships"
    "/dev/.github/scripts/listings.json"
)

# Edit these to widen/narrow what counts as a candidate.
TARGET_TERMS = ["Summer 2027"]
TARGET_CATEGORIES = [
    "AI/ML/Data",
    "Data Science, AI & Machine Learning",
    "Software",
    "Software Engineering",
]
EXCLUDED_DEGREES = {"Master's", "MBA", "PhD"}  # postings requiring ONLY these are skipped


def fetch_listings(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "auto-intern-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def degree_ok(degrees: list) -> bool:
    if not degrees:
        return True
    return any(d not in EXCLUDED_DEGREES for d in degrees)


def filter_listings(listings: list, since_days: float, seen_ids: set) -> list:
    cutoff = time.time() - since_days * 86400
    out = []
    for item in listings:
        if not item.get("active"):
            continue
        if item.get("id") in seen_ids:
            continue
        if not any(t in TARGET_TERMS for t in item.get("terms", [])):
            continue
        if item.get("category") not in TARGET_CATEGORIES:
            continue
        if not degree_ok(item.get("degrees", [])):
            continue
        if item.get("date_posted", 0) < cutoff:
            continue
        out.append(
            {
                "id": item["id"],
                "company": item.get("company_name"),
                "title": item.get("title"),
                "url": item.get("url"),
                "locations": item.get("locations", []),
                "category": item.get("category"),
                "terms": item.get("terms", []),
                "degrees": item.get("degrees", []),
                "date_posted": item.get("date_posted"),
            }
        )
    out.sort(key=lambda x: x["date_posted"] or 0, reverse=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since-days", type=float, default=2,
        help="Only include postings first seen in the last N days (default: 2)",
    )
    parser.add_argument(
        "--seen-ids-file", default=None,
        help="Path to a JSON file containing a list of posting ids to skip (already surfaced)",
    )
    parser.add_argument("--out", default=None, help="Write JSON to this path instead of stdout")
    args = parser.parse_args()

    seen_ids = set()
    if args.seen_ids_file:
        try:
            with open(args.seen_ids_file, "r", encoding="utf-8") as f:
                seen_ids = set(json.load(f))
        except FileNotFoundError:
            pass

    try:
        listings = fetch_listings(LISTINGS_URL)
    except URLError as e:
        print(f"error: could not fetch listings feed: {e}", file=sys.stderr)
        sys.exit(1)

    candidates = filter_listings(listings, args.since_days, seen_ids)
    payload = json.dumps(candidates, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"wrote {len(candidates)} candidates to {args.out}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
