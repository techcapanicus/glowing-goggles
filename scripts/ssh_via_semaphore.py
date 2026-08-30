#!/usr/bin/env python3
"""Run a command on 64.23.139.247 using the working controller SSH key via Semaphore."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOK = "ansible/remote_ssh_exec.yml"
TEMPLATE_NAME = "Remote SSH Exec (working key)"
TARGET = "64.23.139.247"


def ensure_template(api, pid, repo_id):
    templates = api.get(f"/api/project/{pid}/templates")
    existing = find_by_name(templates, TEMPLATE_NAME)
    payload = {
        "project_id": pid,
        "name": TEMPLATE_NAME,
        "playbook": PLAYBOOK,
        "inventory_id": 15,
        "repository_id": repo_id,
        "environment_id": 172,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": "SSH to 64.23.139.247 from controller using /root/.ssh/id_ed25519",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{pid}/templates/{existing['id']}", payload)
        return existing["id"]
    created = api.post(f"/api/project/{pid}/templates", payload)
    return created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{pid}/templates"), TEMPLATE_NAME)["id"]


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description=f"Run command on {TARGET} via Semaphore controller SSH")
    p.add_argument("command", nargs="?", default="hostname && id && uptime")
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--poll-interval", type=int, default=8)
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    tpl_id = ensure_template(api, args.project_id, args.repository_id)
    task = api.post(f"/api/project/{args.project_id}/tasks", {
        "template_id": tpl_id,
        "environment": json.dumps({"remote_command": args.command}),
    })
    task_id = task["id"]
    ok(f"Task #{task_id} queued (controller -> {TARGET})")
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        status = api.get(f"/api/project/{args.project_id}/tasks/{task_id}").get("status")
        if status in terminal:
            break
        time.sleep(args.poll_interval)
    for entry in api.get(f"/api/project/{args.project_id}/tasks/{task_id}/output") or []:
        print(entry.get("output", ""))
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
