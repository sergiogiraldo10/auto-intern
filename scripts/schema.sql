-- Run this once in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query -> Run).
-- Creates the two data tables + a small key/value meta table, with RLS enabled
-- and narrow anon policies (the routines use the service_role key, which
-- bypasses RLS entirely, so these policies only govern the public tracker page).

create table if not exists applications (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  role text not null,
  date_applied date not null,
  status text not null default 'Applied',
  source text,
  url text,
  notes text,
  sample boolean not null default false,
  last_updated timestamptz not null default now()
);

create table if not exists leads (
  id text primary key,
  company text not null,
  role text not null,
  url text,
  category text,
  locations jsonb,
  date_posted timestamptz,
  match_score int,
  match_reason text,
  status text not null default 'new',
  sample boolean not null default false,
  last_updated timestamptz not null default now()
);

create table if not exists meta (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

alter table applications enable row level security;
alter table leads enable row level security;
alter table meta enable row level security;

-- Anon (public tracker page) policies: read/write the two data tables freely.
-- No anon policy on `meta` at all -- only the routines (service_role) touch it,
-- and service_role bypasses RLS, so it doesn't need a policy either.

create policy "anon select applications" on applications for select to anon using (true);
create policy "anon insert applications" on applications for insert to anon with check (true);
create policy "anon update applications" on applications for update to anon using (true) with check (true);
create policy "anon delete applications" on applications for delete to anon using (true);

create policy "anon select leads" on leads for select to anon using (true);
create policy "anon update leads" on leads for update to anon using (true) with check (true);
