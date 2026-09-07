#!/usr/bin/env python3
"""Score internship postings against Sergio's resume using literal keyword/
phrase overlap -- deliberately NOT semantic/LLM judgment. Real ATS platforms
(Workday, Greenhouse, iCIMS, etc.) are keyword/exact-phrase parsers, not
semantic AI, so a score meant to predict "would this posting's system flag my
resume" should mirror that mechanism, not a model's sense of conceptual
similarity. See README.md for the reasoning.

Scores ONLY from the posting's actual description text -- if the page can't
be fetched or returns unusably little content (common on JS-rendered ATS
platforms, e.g. Workday), the candidate is skipped entirely rather than
falling back to title/category guessing. A missing score is more honest than
a fabricated one.

Requires: requests, beautifulsoup4 (pip install -r scripts/requirements.txt)

Usage:
    python match_internships.py --candidates candidates.json --resume ../data/resume.md --out scored_leads.json
"""
import argparse
import datetime
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

# Domain/soft-skill terms that appear throughout the resume's experience and
# project bullets but aren't cleanly listed in the Skills section itself.
# Edit this list by hand when the resume's actual work changes.
SUPPLEMENTAL_KEYWORDS = [
    "Machine Learning", "Data Science", "Data Analytics", "Data Pipeline",
    "ETL", "NLP", "Natural Language Processing", "Sentiment Analysis",
    "Classification Model", "Dashboard", "Business Analytics",
    "Data Visualization", "Statistics", "Data Modeling",
]

SKILLS_LINE_RE = re.compile(r"^-\s*\*\*(.+?):\*\*\s*(.+)$")

USER_AGENT = "Mozilla/5.0 (compatible; auto-intern-matcher/1.0; +https://github.com/sergiogiraldo10/auto-intern)"
MIN_DESCRIPTION_CHARS = 300


def extract_resume_keywords(resume_md: str) -> list:
    keywords = []
    in_skills = False
    for line in resume_md.splitlines():
        if line.strip() == "## Skills":
            in_skills = True
            continue
        if in_skills and line.startswith("## "):
            break
        if in_skills:
            m = SKILLS_LINE_RE.match(line.strip())
            if m:
                keywords.extend(part.strip() for part in m.group(2).split(","))
    keywords.extend(SUPPLEMENTAL_KEYWORDS)
    # De-dupe case-insensitively, keep first-seen casing for display.
    seen = set()
    unique = []
    for kw in keywords:
        key = kw.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(kw)
    return unique


def fetch_description_text(url: str) -> str:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  fetch failed for {url}: {e}", file=sys.stderr)
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) >= MIN_DESCRIPTION_CHARS:
        return text

    # Many JS-rendered ATS platforms (confirmed on Workday) load the real
    # description client-side, leaving an empty page shell here -- but still
    # embed a real, full-length description in an og:description meta tag
    # for social-link previews. Real content the visible-text pass above
    # just can't see; falling back to it recovers postings that would
    # otherwise be skipped entirely despite being genuinely fetchable.
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            meta_text = re.sub(r"\s+", " ", tag["content"]).strip()
            if len(meta_text) > len(text):
                text = meta_text
    return text


def score_against_keywords(description: str, keywords: list) -> dict:
    desc_lower = description.lower()
    matched = [kw for kw in keywords if kw.lower() in desc_lower]
    # 6+ matched keywords maps to a full 100 -- a deliberately low ceiling,
    # since a real posting rarely name-checks more than a handful of a
    # candidate's specific tools verbatim even for a strong match.
    score = min(100, round(100 * len(matched) / 6))
    return {"score": score, "matched": matched}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", required=True, help="Path to candidates.json from fetch_internships.py")
    parser.add_argument("--resume", required=True, help="Path to resume.md")
    parser.add_argument("--out", required=True, help="Where to write scored leads JSON")
    parser.add_argument("--max-candidates", type=int, default=40)
    args = parser.parse_args()

    with open(args.resume, encoding="utf-8") as f:
        resume_md = f.read()
    keywords = extract_resume_keywords(resume_md)
    print(f"Resume keywords ({len(keywords)}): {', '.join(keywords)}", file=sys.stderr)

    with open(args.candidates, encoding="utf-8") as f:
        candidates = json.load(f)
    candidates = candidates[: args.max_candidates]

    leads = []
    skipped_unfetchable = 0
    for c in candidates:
        print(f"Fetching {c['company']} - {c['title']} ({c['url']})", file=sys.stderr)
        text = fetch_description_text(c["url"])
        if len(text) < MIN_DESCRIPTION_CHARS:
            print(f"  skipped -- description unavailable ({len(text)} chars)", file=sys.stderr)
            skipped_unfetchable += 1
            time.sleep(0.5)
            continue
        result = score_against_keywords(text, keywords)
        if result["score"] <= 0:
            time.sleep(0.5)
            continue
        matched = result["matched"]
        reason = (
            f"Posting mentions {len(matched)} of your resume keywords: {', '.join(matched)}."
            if matched else "No resume keywords found in the posting text."
        )
        leads.append({
            "id": c["id"],
            "company": c["company"],
            "role": c["title"],
            "url": c["url"],
            "category": c["category"],
            "locations": c["locations"],
            "date_posted": datetime.datetime.fromtimestamp(c["date_posted"], tz=datetime.timezone.utc).isoformat(),
            "match_score": result["score"],
            "match_reason": reason,
        })
        time.sleep(0.5)  # be polite to ATS servers

    leads.sort(key=lambda l: l["match_score"], reverse=True)
    leads = leads[:15]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2)
    print(f"Scored {len(candidates)} candidates: {len(leads)} kept, {skipped_unfetchable} skipped (description unavailable)", file=sys.stderr)


if __name__ == "__main__":
    main()
