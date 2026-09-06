# auto-intern

Automation around Sergio's internship search: a live application tracker, an
email watcher that updates it from Gmail, and a daily internship-matching
pipeline. Human stays in the loop for every actual submission — nothing here
auto-applies.

## Pieces

### 1. Tracker (`artifact/tracker.html`)
Published as a Claude Artifact: **https://claude.ai/code/artifact/d312f11f-5cf0-4cfe-8467-cca3d0847646**

A versioned snapshot of the published page lives at `artifact/tracker.html` in
this repo. The live version is the source of truth — republish that file
path (or pass its URL from any conversation) to ship changes; keep this copy
in sync by hand after doing so.

Data lives in the artifact's own database (not this repo), in two collections:

- **`applications`** — one doc per application you've submitted.
  `{ company, role, dateApplied, status, source, url, notes, lastUpdated }`.
  `status` is one of `Applied, Assessment, HireVue, Interview, Offer,
  Rejected, Ghosted, Withdrawn`.
- **`leads`** — postings the matching pipeline found and scored, not yet
  acted on. `{ company, role, url, category, locations, datePosted,
  matchScore, matchReason, status }`. `status` is `new` (shown on the
  tracker), `applied` (you clicked "Add to tracker"), or `dismissed`.
- **`meta/watcher`** — one doc holding the email watcher's last run:
  `{ lastRunAt, newUpdatesCount, summary }`.

### 2. Email watcher (scheduled cloud routine, no committed code)
Runs daily via a Claude Code routine (`claude.ai/code/routines`) — not a
script in this repo. Each run reads `applications`, searches Gmail per
company for genuine status-change emails (assessment invites, interview
scheduling, HireVue invites, offers, rejections), updates matched docs, and
writes a summary to `meta/watcher`.

### 3. Internship matching pipeline
- `scripts/fetch_internships.py` — the deterministic, versioned part. Pulls
  the public [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
  listings feed (community-maintained, updated many times a day), filters to
  active postings matching `TARGET_TERMS` / `TARGET_CATEGORIES` in the
  script, excludes postings that require only a graduate degree, and can
  skip ids already seen. Pure stdlib, no dependencies.

  ```
  python scripts/fetch_internships.py --since-days 2
  ```

- The fuzzy part — reading each candidate's actual job description and
  judging fit against `data/resume.md` — is deliberately left to whatever
  calls this script (the daily routine), since that's a prose-to-prose
  judgment call a fixed script can't make well. The routine writes its top
  matches into the `leads` collection above.

### 4. Resume (`data/resume.md`)
Plain-text mirror of Sergio's resume, used as the fit-scoring reference. Not
tailored per posting — one resume, used everywhere. Keep it up to date by
hand when the actual resume changes.

## Design notes / boundaries

- No auto-apply, no browser automation. Every application is submitted by a
  human click. This is intentional — most job platforms' ToS prohibit
  automated submission, and it's detectable (behavioral/fingerprint checks).
- Job sourcing is scoped to legitimate open data (public ATS feeds, the
  SimplifyJobs open-source list) rather than scraping LinkedIn/Handshake,
  for the same reason.
- `leads` documents older than a few weeks and still `status: new` are just
  noise — no automatic cleanup exists yet; dismiss stale ones from the
  tracker UI.
