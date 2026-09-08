# auto-intern

Automation around Sergio's internship search: a live application tracker, an
email-status watcher, a twice-daily internship-matching pipeline, and a
weekly digest. Human stays in the loop for every actual submission --
nothing here auto-applies.

## One backend, on purpose

Everything lives in **Supabase** (Postgres + REST), written entirely by
**GitHub Actions** -- no Claude routine holds a database credential, and no
Claude Artifact is part of the live system anymore. That's a deliberate
change from an earlier iteration that split data across a Claude Artifact
(applications) and Supabase (leads), because Claude Artifact pages can't
`fetch()` a third-party API like Supabase (CSP-blocked, silently) -- so
that split's "New matches" section never actually worked. Moving
applications into Supabase too, and reading Gmail directly via a Google
OAuth credential instead of the Claude connector, means one plain webpage
can read and write all of it directly, with no capability wall in the way.

## Pieces

### 1. Tracker (`docs/index.html`, served via GitHub Pages)
A single static page, soft password-gated (client-side check -- a deterrent
against a guessed URL, not real security; see Security below), that reads
and writes Supabase directly with the embedded anon key.

- **`applications`**: `{ id, company, role, date_applied, status, source,
  url, notes, sample, last_updated }`. `status` is one of `Applied,
  Assessment, Video Interview, Interview, Offer, Rejected, Ghosted,
  Withdrawn`. ("Video Interview" covers one-way/async platforms -- HireVue,
  Spark Hire, Modern Hire, etc. -- kept distinct from a live "Interview".)
  Append-only by design -- no delete affordance in the UI.
- **`leads`**: `{ id, company, role, url, category, locations, date_posted,
  match_score, match_reason, status, sample, last_updated }`. `status` is
  `new` (shown in "New matches"), `applied`, `dismissed`, or `stale`
  (auto-archived after 10 days unreviewed).
- **`meta`**: `status_watcher`, `leads_watcher`, and `weekly_digest` keys,
  each holding that pipeline's last-run summary.

A "Refresh" button re-pulls everything on demand, since the page loads data
once rather than subscribing live.

### 2. Email status watcher (GitHub Actions, `scripts/gmail_status_watcher.py`)
`.github/workflows/email-status-watcher.yml`, twice daily. Reads Gmail
directly via a Google OAuth refresh token (see `scripts/gmail_oauth_setup.py`
for the one-time local authorization step that produces it) -- not the
Claude Gmail connector, so there's no LLM anywhere near untrusted email
content while holding that credential. For each non-terminal application, it
searches Gmail scoped to the company and applied-date, and classifies any
matching email by **literal keyword/phrase match**, the same "mirror what a
real ATS does" reasoning as the match pipeline below: specific phrases only
(no bare words like "unfortunately", which show up in unrelated sentences
too easily -- caught in testing on a real false positive), vendor-specific
signals (e.g. "spark hire") take precedence over generic ones ("interview
invitation") within one email, and a detected stage never downgrades an
existing one. Rejection is checked first and short-circuits everything else.

### 3. Internship matching pipeline (GitHub Actions)
`.github/workflows/internship-match.yml`, same twice-daily schedule. Each run:

1. `scripts/fetch_internships.py` -- pulls new postings from the public
   [SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
   feed.
2. `scripts/match_internships.py` -- for each new candidate, fetches the
   **actual posting page** (real HTTP request, `requests` + `BeautifulSoup`)
   and scores it against `data/resume.md` by **literal keyword/phrase
   overlap**, not an LLM's semantic judgment -- real ATS platforms (Workday,
   Greenhouse, iCIMS, etc.) are keyword/exact-phrase parsers, not semantic
   AI, so a score meant to predict "would this posting's system flag my
   resume" should mirror that mechanism. Zero API/model cost. If the visible
   page text comes up short, it falls back to the page's `og:description`
   meta tag (confirmed real, full-length descriptions there on several
   Workday-hosted postings that otherwise render their content client-side
   and would return an empty shell) before giving up; a posting is only
   **skipped entirely** if neither source clears `MIN_DESCRIPTION_CHARS`,
   rather than scored from title/category guesswork.
3. `scripts/supabase_client.py` -- writes results to `leads`, archives
   `leads` still `new` after 10 days, updates `meta.leads_watcher`.
4. `scripts/notify_new_matches.py` -- if that run actually added any leads,
   emails a ranked summary (company, role, score, matched keywords, link) to
   `sergiogiraldo222@gmail.com` right away. Sends nothing on a run that finds
   no new matches -- unlike the weekly digest, "nothing new" twice a day
   isn't worth an email.

### 4. Weekly digest (GitHub Actions, `scripts/weekly_digest.py`)
`.github/workflows/weekly-digest.yml`, Monday mornings. Reads `applications`
from Supabase and emails a plain-text summary to
`sergiogiraldo222@gmail.com` -- sends even on a quiet week, as a liveness
check (unlike the new-matches notification above, which is deliberately
silent when there's nothing to report).

`scripts/gmail_client.py` holds the shared Gmail API helpers (`gmail_service`,
`send_email`) used by this, `gmail_status_watcher.py`, and
`notify_new_matches.py`.

### 5. Resume (`data/resume.md`)
Plain-text mirror of Sergio's resume -- the fit-scoring reference for
`match_internships.py`'s keyword extraction. Not tailored per posting -- one
resume, used everywhere.

## `scripts/supabase_client.py`
A stdlib-only CLI for the Supabase tables: `select`, `insert`, `update`,
`upsert`, `delete`, each taking `--eq field=value` and/or `--filter
field=op.value`; `insert`/`upsert` also take `--file path.json` for
payloads too large for a shell argument. Falls back to a built-in anon key
if `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` aren't set (useful for local
testing) -- GitHub Actions sets the real service_role key as a secret.
`gmail_status_watcher.py` and `weekly_digest.py` both import it directly
(`import supabase_client as sb`) for its request helpers rather than
duplicating HTTP boilerplate.

## Gmail OAuth setup (one-time, local)
`scripts/gmail_oauth_setup.py` turns a Google Cloud "Desktop app" OAuth
client id/secret into a refresh token: run it locally (never in CI), it
opens a browser for you to approve access on `sergiogiraldo222@gmail.com`
with `gmail.readonly` + `gmail.send` scopes, and prints the refresh token to
save as a GitHub secret. See the script's docstring for exact steps. The
OAuth consent screen stays in Testing mode with that account added as a
test user -- this is a personal-use credential, never submitted for Google's
verification review.

Required GitHub repository secrets (Settings -> Secrets and variables ->
Actions): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GMAIL_CLIENT_ID`,
`GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`. Every workflow can also be run
manually from the Actions tab (`workflow_dispatch`).

## Security notes

- **The Supabase anon key is not a secret.** It's embedded directly in
  `docs/index.html`, a public page. RLS policies in `scripts/schema.sql`
  are what actually govern access: anon can read/insert/update
  `applications` and read/update `leads` (no delete on either), and read
  `meta` only.
- **GitHub Actions uses the service_role key** (bypasses RLS entirely) and
  the Gmail OAuth credential -- safe here specifically because every script
  that touches them (`match_internships.py`, `gmail_status_watcher.py`,
  `weekly_digest.py`, `supabase_client.py`) is deterministic code, not an
  LLM agent processing untrusted content. There's no prompt-injection
  surface for a malicious job posting or email to exploit; the worst a bad
  page or message can do is fail to parse or (as tested) trigger an
  overly-loose keyword match, which is a correctness bug to fix, not a
  security hole. This is exactly why no Claude routine holds either
  credential: an LLM reading untrusted emails/web pages *while also*
  holding a real database or mail-send credential would be a genuine
  exfiltration risk.
- The tracker's password gate is a plain client-side string comparison
  (base64-obfuscated, not encrypted) -- a soft deterrent against a guessed
  URL, not a real access control. Don't rely on it for anything sensitive
  beyond "don't want randoms browsing this if they find the link."

## Design notes / boundaries

- No auto-apply, no browser automation. Every application is submitted by
  a human click; clicking "Add to tracker" on a match only logs it.
- Job sourcing is scoped to legitimate open data (public ATS feeds, the
  SimplifyJobs open-source list, and directly fetching a posting's own
  public page) rather than scraping LinkedIn/Handshake.
- Status detection (both the email watcher and the match scorer) is
  deliberately keyword-based rather than an LLM's semantic read, for the
  same reason in both places: it mirrors what the real automated systems on
  the other end (ATS parsers, an inbox search) actually do, it's free, and
  it's auditable -- every status change and match score traces back to an
  exact matched phrase, not a model's impression.
- Retired: the Claude Artifact tracker and the Claude-routine Email
  Watcher / Weekly Digest (both disabled, kept only for reference/rollback
  -- routines can't be deleted via the API). Their Artifact/Gmail-connector
  based approach is superseded by the GitHub Actions pipelines above.
