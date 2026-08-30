#!/usr/bin/env python3
"""Run SSH Firewall Whitelist (Bash) template on Semaphore controller."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

TEMPLATE_NAME = "SSH Firewall Whitelist (Bash)"


def env(key, default=None):
    return os.environ.get(key, default)


def detect_public_ip():
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode().strip()
        except OSError:
            continue
    return ""


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--target-ip", default=env("TARGET_IP", ""))
    p.add_argument("--poll-interval", type=int, default=10)
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    target_ip = args.target_ip or detect_public_ip()
    api = Semaphore(args.url.rstrip("/"), args.token)
    templates = api.get(f"/api/project/{args.project_id}/templates")
    tpl = find_by_name(templates, TEMPLATE_NAME)
    if not tpl:
        die(f"Template '{TEMPLATE_NAME}' not found")

    extra = {"TARGET_IP": target_ip} if target_ip else {}
    if target_ip:
        info(f"TARGET_IP={target_ip} (whitelist this IP on all DO firewalls)")

    task = api.post(f"/api/project/{args.project_id}/tasks", {
        "template_id": tpl["id"],
        "environment": json.dumps(extra),
    })
    task_id = task["id"]
    ok(f"Task #{task_id} queued on Semaphore controller (localhost)")

    terminal = {"success", "error", "failed", "stopped"}
    while True:
        current = api.get(f"/api/project/{args.project_id}/tasks/{task_id}")
        status = current.get("status")
        if status in terminal:
            break
        time.sleep(args.poll_interval)

    output = api.get(f"/api/project/{args.project_id}/tasks/{task_id}/output")
    print("\n----- task output -----\n")
    print("\n".join(entry.get("output", "") for entry in (output or [])))
    print("\n----- end output -----\n")
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
