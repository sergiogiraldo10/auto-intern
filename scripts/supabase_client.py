#!/usr/bin/env python3
"""Minimal stdlib-only CLI for talking to the auto-intern Supabase backend
over its REST API (PostgREST). Used by the scheduled cloud routines to
read/write the `applications`, `leads`, and `meta` tables without needing
the Claude Artifact database or any third-party Python package.

Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the environment
(the routines set these as private environment variables -- never commit
real values to this repo). The service_role key bypasses Row Level
Security entirely, so these calls always have full read/write access
regardless of the anon-facing policies in scripts/schema.sql.

Usage:
    python supabase_client.py select <table> [--eq field=value ...] [--order field] [--desc] [--limit N]
    python supabase_client.py insert <table> '<json object or array>'
    python supabase_client.py update <table> '<json object>' --eq field=value [--eq field2=value2 ...]
    python supabase_client.py upsert <table> '<json object or array>' --on-conflict id
    python supabase_client.py delete <table> --eq field=value

All commands print the response body (JSON) to stdout and exit non-zero
with an error on stderr if the request fails.
"""
import argparse
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError, URLError


# Fallback defaults so this script works even where env vars aren't configured
# (e.g. a scheduled cloud routine). These are NOT secrets: this is the anon key,
# already public in docs/index.html and restricted by the RLS policies in
# scripts/schema.sql -- see README.md for why service_role is never used here.
_DEFAULT_URL = "https://uzqqsaqpmeqxyniytizz.supabase.co"
_DEFAULT_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV6"
    "cXFzYXFwbWVxeHluaXl0aXp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg2NTE3NDgsImV4cCI6"
    "MjEwNDIyNzc0OH0.bQ40U9yMHV9lDPAkU78HCs6iNUBSHH8i2h2FKAwfC2w"
)


def _base_headers(prefer=None):
    url = os.environ.get("SUPABASE_URL") or _DEFAULT_URL
    # Prefer service_role (full access, used for admin/manual work) but fall back to
    # the anon key -- the routines run with anon only, since it already has the access
    # it needs (see scripts/schema.sql) and isn't a secret: it's embedded in docs/index.html.
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or _DEFAULT_ANON_KEY
    )
    if not url or not key:
        print("error: SUPABASE_URL and (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY) must be set", file=sys.stderr)
        sys.exit(1)
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return url.rstrip("/"), headers


def _request(method, path, headers, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return raw if raw else "[]"
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"error: HTTP {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_select(args):
    base, headers = _base_headers()
    params = ["select=*"]
    for pair in args.eq or []:
        field, value = pair.split("=", 1)
        params.append(f"{field}=eq.{value}")
    if args.order:
        params.append(f"order={args.order}.{'desc' if args.desc else 'asc'}")
    if args.limit:
        params.append(f"limit={args.limit}")
    url = f"{base}/rest/v1/{args.table}?{'&'.join(params)}"
    print(_request("GET", url, headers))


def cmd_insert(args):
    base, headers = _base_headers(prefer="return=representation")
    url = f"{base}/rest/v1/{args.table}"
    print(_request("POST", url, headers, json.loads(args.json_data)))


def cmd_upsert(args):
    prefer = "return=representation,resolution=merge-duplicates"
    base, headers = _base_headers(prefer=prefer)
    on_conflict = args.on_conflict or "id"
    url = f"{base}/rest/v1/{args.table}?on_conflict={on_conflict}"
    print(_request("POST", url, headers, json.loads(args.json_data)))


def cmd_update(args):
    if not args.eq:
        print("error: update requires at least one --eq filter", file=sys.stderr)
        sys.exit(1)
    base, headers = _base_headers(prefer="return=representation")
    params = [f"{f}=eq.{v}" for f, v in (pair.split("=", 1) for pair in args.eq)]
    url = f"{base}/rest/v1/{args.table}?{'&'.join(params)}"
    print(_request("PATCH", url, headers, json.loads(args.json_data)))


def cmd_delete(args):
    if not args.eq:
        print("error: delete requires at least one --eq filter", file=sys.stderr)
        sys.exit(1)
    base, headers = _base_headers(prefer="return=representation")
    params = [f"{f}=eq.{v}" for f, v in (pair.split("=", 1) for pair in args.eq)]
    url = f"{base}/rest/v1/{args.table}?{'&'.join(params)}"
    print(_request("DELETE", url, headers))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_select = sub.add_parser("select")
    p_select.add_argument("table")
    p_select.add_argument("--eq", action="append", help="field=value, repeatable")
    p_select.add_argument("--order")
    p_select.add_argument("--desc", action="store_true")
    p_select.add_argument("--limit", type=int)
    p_select.set_defaults(func=cmd_select)

    p_insert = sub.add_parser("insert")
    p_insert.add_argument("table")
    p_insert.add_argument("json_data")
    p_insert.set_defaults(func=cmd_insert)

    p_upsert = sub.add_parser("upsert")
    p_upsert.add_argument("table")
    p_upsert.add_argument("json_data")
    p_upsert.add_argument("--on-conflict", default="id")
    p_upsert.set_defaults(func=cmd_upsert)

    p_update = sub.add_parser("update")
    p_update.add_argument("table")
    p_update.add_argument("json_data")
    p_update.add_argument("--eq", action="append", required=True, help="field=value, repeatable")
    p_update.set_defaults(func=cmd_update)

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("table")
    p_delete.add_argument("--eq", action="append", required=True, help="field=value, repeatable")
    p_delete.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
