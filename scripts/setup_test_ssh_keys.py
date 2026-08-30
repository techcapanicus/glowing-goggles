#!/usr/bin/env python3
"""Register and run Test SSH Keys template via Semaphore."""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok  # noqa: E402

PLAYBOOK = "ansible/test_ssh_keys.yml"
TEMPLATE_NAME = "Test SSH Keys"


def run_task(api, pid, template_id, poll_interval):
    task = api.post(f"/api/project/{pid}/tasks", {"template_id": template_id})
    task_id = task["id"]
    ok(f"Task #{task_id} queued")
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        current = api.get(f"/api/project/{pid}/tasks/{task_id}")
        status = current.get("status")
        if status in terminal:
            break
        time.sleep(poll_interval)
    output = api.get(f"/api/project/{pid}/tasks/{task_id}/output")
    text = "\n".join(entry.get("output", "") for entry in (output or []))
    print("\n----- task output -----\n")
    print(text)
    print("\n----- end output -----\n")
    return status, text


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--inventory-id", type=int, default=21)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--environment-id", type=int, default=172)
    p.add_argument("--run", action="store_true")
    p.add_argument("--poll-interval", type=int, default=10)
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    templates = api.get(f"/api/project/{args.project_id}/templates")
    existing = find_by_name(templates, TEMPLATE_NAME)
    payload = {
        "project_id": args.project_id,
        "name": TEMPLATE_NAME,
        "playbook": PLAYBOOK,
        "inventory_id": args.inventory_id,
        "repository_id": args.repository_id,
        "environment_id": args.environment_id,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": "Test SSH auth to 64.23.139.247 with each private key on droplet and controller",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{args.project_id}/templates/{existing['id']}", payload)
        tpl_id = existing["id"]
        ok(f"Updated template '{TEMPLATE_NAME}' (id {tpl_id})")
    else:
        created = api.post(f"/api/project/{args.project_id}/templates", payload)
        tpl_id = created["id"] if isinstance(created, dict) else \
            find_by_name(api.get(f"/api/project/{args.project_id}/templates"), TEMPLATE_NAME)["id"]
        ok(f"Created template '{TEMPLATE_NAME}' (id {tpl_id})")

    if not args.run:
        return 0
    status, _ = run_task(api, args.project_id, tpl_id, args.poll_interval)
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
