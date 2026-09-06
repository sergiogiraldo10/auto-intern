# auto-intern

Automation around Sergio's internship search: a live application tracker, an
email watcher that updates it from Gmail, a daily internship-matching
pipeline, and a weekly digest. Human stays in the loop for every actual
submission — nothing here auto-applies.

## Pieces

### 1. Tracker (`docs/index.html`)
A static, password-gated page hosted via GitHub Pages:
**https://sergiogiraldo10.github.io/auto-intern/**

Backed by Supabase (Postgres + a REST API), not the Claude Artifact database —
see "Why Supabase, not a Claude Artifact" below. The password gate is a
plain client-side check (not real security, just a soft deterrent — see
`scripts/schema.sql` and the design notes below for the actual access model).

Data lives in three Supabase tables (schema + RLS policies in
`scripts/schema.sql`, run once via the Supabase SQL Editor):

- **`applications`** — one row per application submitted. `{ id, company,
  role, date_applied, status, source, url, notes, sample, last_updated }`.
  `status` is one of `Applied, Assessment, HireVue, Interview, Offer,
  Rejected, Ghosted, Withdrawn`. Append-only by design — there is no delete
  policy and no delete control in the UI; a mistaken row gets its status
  corrected, not removed.
- **`leads`** — postings the matching pipeline found and scored, not yet
  acted on. `{ id, company, role, url, category, locations, date_posted,
  match_score, match_reason, status, sample, last_updated }`. `status` is
  `new` (shown in "New matches"), `applied` (clicked "Add to tracker"),
  `dismissed` (clicked "Dismiss"), or `stale` (auto-archived once the
  posting is more than 10 days old and still unreviewed — see the
  Internship Match Finder routine).
- **`meta`** — small key/value table for operational status: `watcher` (the
  email watcher's last run) and `leads_watcher` (the matcher's last run),
  each `{ lastRunAt, ... }`.

### 2. Email watcher (scheduled cloud routine, no committed code)
Runs daily via a Claude Code routine (`claude.ai/code/routines`) — not a
script in this repo, since matching an email to "is this really about this
application" is a prose judgment call, not a fixed procedure. Each run reads
`applications` (via `scripts/supabase_client.py`), searches Gmail per company
for genuine status-change emails (assessment invites, interview scheduling,
HireVue invites, offers, rejections), updates matched rows, and writes a
summary to `meta.watcher`.

**Gmail account**: the connector must be signed in as
`sergiogiraldo222@gmail.com` (where applications actually go), not any
school email — only one Google account can be connected at a time, swapped
at claude.ai's connector settings.

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
  judging fit against `data/resume.md` — is left to the daily routine
  ("Internship Match Finder"), which also archives any `leads` row still
  `status: new` after 10 days so "New matches" always reflects genuinely
  recent postings, not an ever-growing backlog.

### 4. Weekly digest (scheduled cloud routine, read-only)
Runs Monday mornings, reads `applications` and `leads`, and sends one push
notification summarizing the week — applications submitted, status changes,
interviews in progress, new matches surfaced. Sends even on a quiet week
(zero everything), as a live-check that the automation is still running.

### 5. Resume (`data/resume.md`)
Plain-text mirror of Sergio's resume, used as the fit-scoring reference. Not
tailored per posting — one resume, used everywhere. Keep it up to date by
hand when the actual resume changes.

## `scripts/supabase_client.py`
A stdlib-only CLI the routines (and you, locally) use to read/write Supabase
without any third-party package: `select`, `insert`, `update`, `upsert`,
`delete`, each taking `--eq field=value` and/or `--filter field=op.value`
(e.g. `--filter "date_posted=lt.2026-08-27T00:00:00Z"` for date-range bulk
updates). Falls back to a built-in anon key if `SUPABASE_URL`/
`SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` aren't set in the
environment — see the section below for why that's fine.

## Why Supabase, not a Claude Artifact (and why anon, not service_role)

The tracker started as a Claude Artifact (a hosted page + database, no extra
service needed). It moved to GitHub Pages + Supabase so the whole system —
frontend and data schema both — lives as ordinary files in this repo, not
tied to Claude's hosting.

Two things worth understanding about the resulting security model:

- **The anon key is not a secret.** It's embedded directly in
  `docs/index.html`, a public file in a public repo — anyone can read it.
  The RLS policies in `scripts/schema.sql` are what actually govern access
  (anon can read/write `applications`/`leads`, but never delete
  `applications`; anon can read/write `meta`, which only ever holds
  trivial status text). This is why the routines use the anon key too,
  rather than the far more powerful `service_role` key: `service_role`
  bypasses RLS entirely, and giving that to a routine that also processes
  untrusted content (Gmail messages, fetched job-posting pages) would be a
  real prompt-injection exfiltration risk for no actual gain, since anon
  already has all the access these routines need.
- **The password gate is a soft deterrent, not access control.** It's a
  plain string compare against a base64-obfuscated constant in
  `docs/index.html` — trivially bypassable by anyone who reads the page
  source. It exists to stop casual/accidental visitors, not a motivated one.

## Design notes / boundaries

- No auto-apply, no browser automation. Every application is submitted by a
  human click. This is intentional — most job platforms' ToS prohibit
  automated submission, and it's detectable (behavioral/fingerprint checks).
  Clicking "Add to tracker" on a match only logs it — it does not submit
  anything.
- Job sourcing is scoped to legitimate open data (public ATS feeds, the
  SimplifyJobs open-source list) rather than scraping LinkedIn/Handshake,
  for the same reason.
