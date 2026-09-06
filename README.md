# auto-intern

Automation around Sergio's internship search: a live application tracker, an
email watcher that updates it from Gmail, a daily internship-matching
pipeline, and a weekly digest. Human stays in the loop for every actual
submission — nothing here auto-applies.

## Two backends, on purpose

This system's data is deliberately split across two different backends,
because no single one can be reached from every place that needs to touch
it:

- **Applications** (and their status) live in a **Claude Artifact**
  database. The tracker page itself is a published Claude Artifact:
  **https://claude.ai/code/artifact/d312f11f-5cf0-4cfe-8467-cca3d0847646**.
  The Email Watcher (a Claude Code routine) reads Gmail and writes status
  changes here via the Artifact tool.
- **Leads** (candidate internship postings, scored against the resume)
  live in **Supabase** (Postgres + REST). The Internship Match Finder is a
  **GitHub Actions workflow**, not a Claude routine — see below for why.

Why not put everything in one place: Claude Code routine sandboxes run
behind a restrictive network egress proxy that blocks arbitrary third-party
hosts (confirmed by testing: Supabase, and every job-posting site tried via
`WebFetch`, all returned `EGRESS_BLOCKED`) — so a routine can never read an
actual job description. GitHub Actions runners have normal, unrestricted
internet access, so they can — but there's no public API for external code
to read or write a Claude Artifact's database, so GitHub Actions can't touch
the tracker directly either. Each piece lives where it's actually reachable
from; the tracker page talks to both.

## Pieces

### 1. Tracker (`artifact/tracker.html`)
A published Claude Artifact — private by default, no login/password needed.
Reads/writes `applications` and `meta/watcher` via the Artifact `db`
capability (`window.claude.use('db')`); reads/writes `leads` and
`meta/leads_watcher` via a Supabase client (the anon key embedded in the
page is not a secret — see Security below).

- **`applications`** (Artifact db): `{ company, role, dateApplied, status,
  source, url, notes, sample, lastUpdated }`. `status` is one of `Applied,
  Assessment, HireVue, Interview, Offer, Rejected, Ghosted, Withdrawn`.
  Append-only by design — no delete affordance in the UI.
- **`leads`** (Supabase, snake_case columns): `{ id, company, role, url,
  category, locations, date_posted, match_score, match_reason, status,
  sample, last_updated }`. `status` is `new` (shown in "New matches"),
  `applied`, `dismissed`, or `stale` (auto-archived after 10 days
  unreviewed).
- **`meta/watcher`** (Artifact db) and **`meta.leads_watcher`** (Supabase):
  each holds the corresponding pipeline's last-run summary.

### 2. Email watcher (scheduled Claude Code routine)
Runs daily via `claude.ai/code/routines`, using a **persistent session**:
the first write in that session prompts for a one-time manual approval
(open the routine's session link, click approve) — every fire after that,
including real scheduled ones, reuses the same approval automatically.
Reads `applications` from the Artifact, searches Gmail per company for
genuine status-change emails, updates matched rows, writes a summary to
`meta/watcher`.

**Gmail account**: must be connected as `sergiogiraldo222@gmail.com` (where
applications actually go), switched at claude.ai's connector settings.

### 3. Internship matching pipeline (GitHub Actions, not a Claude routine)
`.github/workflows/internship-match.yml`, on the same twice-daily schedule
(7am/4pm America/New_York). Each run:

1. `scripts/fetch_internships.py` — pulls new postings from the public
   [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
   feed (unchanged from before).
2. `scripts/match_internships.py` — for each new candidate, fetches the
   **actual posting page** (real HTTP request, `requests` + `BeautifulSoup`)
   and scores it against `data/resume.md` by **literal keyword/phrase
   overlap**, not an LLM's semantic judgment. This is deliberate: real ATS
   platforms (Workday, Greenhouse, iCIMS, etc.) are keyword/exact-phrase
   parsers, not semantic AI, so a score meant to predict "would this
   posting's system flag my resume" should mirror that mechanism. It also
   means zero API cost — no model call in this pipeline at all. If a
   posting's page can't be fetched or returns too little content to be
   real (common on JS-rendered platforms like Workday), that candidate is
   **skipped entirely** rather than scored from title/category guesswork —
   a missing score is more honest than a fabricated one.
3. `scripts/supabase_client.py` — writes results to `leads`, archives
   `leads` still `new` after 10 days, updates `meta.leads_watcher`.

Required GitHub repository secrets (Settings → Secrets and variables →
Actions): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. The workflow can also
be run manually from the Actions tab (`workflow_dispatch`).

### 4. Weekly digest (scheduled Claude Code routine, read-only)
Runs Monday mornings, reads `applications` from the Artifact, sends one
push notification summarizing the week. Sends even on a quiet week, as a
liveness check.

### 5. Resume (`data/resume.md`)
Plain-text mirror of Sergio's resume — the fit-scoring reference for
`match_internships.py`'s keyword extraction (its Skills section is parsed
directly; see `SUPPLEMENTAL_KEYWORDS` in that script for domain terms drawn
from the experience/project bullets, maintained by hand). Not tailored per
posting — one resume, used everywhere.

## `scripts/supabase_client.py`
A stdlib-only CLI for the `leads`/`meta` Supabase tables: `select`,
`insert`, `update`, `upsert`, `delete`, each taking `--eq field=value`
and/or `--filter field=op.value` (e.g. `--filter
"date_posted=lt.2026-08-27T00:00:00Z"`); `insert`/`upsert` also take
`--file path.json` for payloads too large for a shell argument. Falls back
to a built-in anon key if `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` aren't
set in the environment (useful for local testing) — GitHub Actions sets the
real service_role key as a secret.

## Security notes

- **The Supabase anon key is not a secret.** It's embedded directly in
  `artifact/tracker.html` and `docs/index.html` (a historical snapshot —
  see below), both effectively public. RLS policies in
  `scripts/schema.sql` are what actually govern access: anon can
  read/update `leads` (no insert/delete), and read `meta` only.
- **The GitHub Actions workflow uses the service_role key** (bypasses RLS
  entirely) — safe here specifically because `match_internships.py` and
  `supabase_client.py` are deterministic code, not an LLM agent processing
  untrusted content. There's no prompt-injection surface for a malicious
  job posting to exploit; the worst a bad page can do is fail to parse.
  This is the opposite of the Claude-routine case, where holding a
  powerful credential *while also* letting an LLM read untrusted content
  (emails, web pages) would be a real exfiltration risk — which is part of
  why the routines only ever hold Artifact/Gmail access, never Supabase
  credentials.

## Design notes / boundaries

- No auto-apply, no browser automation. Every application is submitted by
  a human click; clicking "Add to tracker" on a match only logs it.
- Job sourcing is scoped to legitimate open data (public ATS feeds, the
  SimplifyJobs open-source list, and directly fetching a posting's own
  public page) rather than scraping LinkedIn/Handshake.
- `docs/index.html` and the Supabase-backed `applications`/Artifact
  concepts from an earlier iteration are superseded by the split described
  above; `docs/index.html` is kept only as a historical snapshot and is not
  the live tracker.
