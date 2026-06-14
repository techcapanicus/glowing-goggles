#!/usr/bin/env python3
"""Verify a Semaphore API token and print the authenticated user."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.semaphore_session import from_env_or_login  # noqa: E402


def main():
    p = argparse.ArgumentParser(
        description=(
            "Check that a Semaphore API token works. "
            "Copy the token from DevTools → Network → any /api/* request → "
            "Request Headers → Authorization: Bearer <token>"
        )
    )
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"), required=not os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"))
    args = p.parse_args()

    session = from_env_or_login(args.url, args.token, url_explicit=bool(args.url))
    me = session.user()
    pong = session.ping()
    print(f"url:      {session.base_url}")
    print(f"user:     {me.get('username')} ({me.get('name')})")
    print(f"admin:    {me.get('admin')}")
    print(f"ping:     {'pong' if pong else 'FAILED'}")

    projects = session.get("/api/projects") or []
    print(f"projects: {len(projects)}")
    for pr in projects[:10]:
        print(f"  [{pr['id']}] {pr.get('name')}")
    if len(projects) > 10:
        print(f"  … and {len(projects) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
