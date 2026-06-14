#!/usr/bin/env python3
"""Parse Semaphore task output for SSH provisioning diagnostics.

Fetches task log lines via the Semaphore REST API and summarizes permission,
sshd, and SSH self-test findings.

Usage:
  ./scripts/parse_ssh_task_output.py --project-id 6 --task-id 3881
  ./scripts/parse_ssh_task_output.py --project-id 6 --latest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

PATTERNS = [
    ("FAILED", re.compile(r"\bFAILED\b|fatal:", re.I)),
    ("WARNING", re.compile(r"\bWARNING\b|\[WARNING\]", re.I)),
    ("mode/owner", re.compile(r"mode:|owner:|\.ssh dir owner:|authorized_keys owner:", re.I)),
    ("DEBUG SSH", re.compile(r"debug1:|debug2:|debug3:", re.I)),
    ("auth refused", re.compile(r"Authentication refused|Permission denied|bad ownership|refused connect", re.I)),
    ("SSH self-test", re.compile(r"SSH self-test from controller|SSH_AUTH_OK|kex_exchange|Connection reset", re.I)),
    ("sshd_config", re.compile(r"PubkeyAuthentication|AuthorizedKeysFile|PermitRootLogin|StrictModes|AllowUsers", re.I)),
    ("journal", re.compile(r"sshd\[|Failed publickey|Accepted publickey|Connection closed|Disconnected", re.I)),
]


def load_dotenv(path=".env"):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_get(base_url, token, path):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    }
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def fetch_output(base_url, token, project_id, task_id):
    entries = api_get(base_url, token, f"/api/project/{project_id}/tasks/{task_id}/output")
    lines = []
    for entry in entries or []:
        for raw in entry.get("output", "").splitlines():
            lines.append(strip_ansi(raw.rstrip()))
    return lines


def latest_task_id(base_url, token, project_id, template_id=None):
    tasks = api_get(base_url, token, f"/api/project/{project_id}/tasks?limit=25")
    if template_id is not None:
        tasks = [t for t in tasks if t.get("template_id") == template_id]
    if not tasks:
        return None
    return tasks[0]["id"]


def summarize(lines):
    findings = {label: [] for label, _ in PATTERNS}
    for line in lines:
        if not line.strip():
            continue
        for label, pattern in PATTERNS:
            if pattern.search(line):
                findings[label].append(line)
    return findings


def print_summary(task_id, status, findings):
    print(f"Task #{task_id}  status={status}")
    print("=" * 60)
    any_hit = False
    for label, hits in findings.items():
        if not hits:
            continue
        any_hit = True
        print(f"\n## {label} ({len(hits)} lines)")
        for line in hits[:40]:
            print(f"  {line}")
        if len(hits) > 40:
            print(f"  ... ({len(hits) - 40} more)")
    if not any_hit:
        print("No diagnostic pattern matches found in task output.")
    print()
    if findings["SSH self-test"]:
        ok = any("SSH_AUTH_OK" in x for x in findings["SSH self-test"])
        reset = any("reset" in x.lower() or "kex_exchange" in x.lower()
                    for x in findings["SSH self-test"])
        if ok:
            print("Verdict: Controller SSH self-test succeeded.")
        elif reset:
            print("Verdict: Controller SSH self-test hit connection reset during "
                  "handshake — likely firewall/network, not authorized_keys content.")
        else:
            print("Verdict: Controller SSH self-test did not succeed — see DEBUG SSH "
                  "and auth refused sections.")


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser(description="Parse Semaphore SSH provision task logs")
    env = os.environ.get
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=env("SEMAPHORE_PROJECT_ID"))
    p.add_argument("--task-id", type=int, help="Semaphore task id to parse")
    p.add_argument("--latest", action="store_true", help="Use most recent project task")
    p.add_argument("--template-id", type=int, help="Filter --latest by template id")
    args = p.parse_args(argv)

    if not args.url or not args.token or not args.project_id:
        print("Need --url, --token, and --project-id (or .env)", file=sys.stderr)
        return 1
    project_id = int(args.project_id)

    if args.latest:
        task_id = latest_task_id(args.url, args.token, project_id, args.template_id)
        if not task_id:
            print("No tasks found.", file=sys.stderr)
            return 1
    elif args.task_id:
        task_id = args.task_id
    else:
        print("Pass --task-id or --latest", file=sys.stderr)
        return 1

    try:
        task = api_get(args.url, args.token, f"/api/project/{project_id}/tasks/{task_id}")
        lines = fetch_output(args.url, args.token, project_id, task_id)
    except urllib.error.HTTPError as exc:
        print(f"API error: HTTP {exc.code}: {exc.read().decode()}", file=sys.stderr)
        return 1

    print_summary(task_id, task.get("status"), summarize(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
