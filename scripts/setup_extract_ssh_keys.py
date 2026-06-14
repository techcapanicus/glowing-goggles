#!/usr/bin/env python3
"""Register and run Extract SSH Keys template on 64.23.139.247 via Semaphore."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOK = "ansible/extract_ssh_keys.yml"
TEMPLATE_NAME = "Extract SSH Keys"
DEFAULT_INVENTORY_ID = 21
DEFAULT_REPOSITORY_ID = 6
DEFAULT_ENV_ID = 172


def env(key, default=None):
    return os.environ.get(key, default)


def ensure_template(api, pid, inventory_id, repository_id, environment_id):
    templates = api.get(f"/api/project/{pid}/templates")
    existing = find_by_name(templates, TEMPLATE_NAME)
    payload = {
        "project_id": pid,
        "name": TEMPLATE_NAME,
        "playbook": PLAYBOOK,
        "inventory_id": inventory_id,
        "repository_id": repository_id,
        "environment_id": environment_id,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": (
            "Extract SSH keys from DO metadata, authorized_keys, ssh-agent, "
            "and on-disk key files on 64.23.139.247 via Semaphore SSH"
        ),
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{pid}/templates/{existing['id']}", payload)
        ok(f"Updated template '{TEMPLATE_NAME}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{pid}/templates", payload)
    tpl_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{pid}/templates"), TEMPLATE_NAME)["id"]
    ok(f"Created template '{TEMPLATE_NAME}' (id {tpl_id})")
    return tpl_id


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
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--inventory-id", type=int, default=DEFAULT_INVENTORY_ID)
    p.add_argument("--repository-id", type=int, default=DEFAULT_REPOSITORY_ID)
    p.add_argument("--environment-id", type=int, default=DEFAULT_ENV_ID)
    p.add_argument("--run", action="store_true")
    p.add_argument("--poll-interval", type=int, default=10)
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    tpl_id = ensure_template(
        api, args.project_id, args.inventory_id,
        args.repository_id, args.environment_id)
    print(f"    template_id = {tpl_id}")
    if not args.run:
        info("Pass --run to execute on 64.23.139.247")
        return 0
    status, _ = run_task(api, args.project_id, tpl_id, args.poll_interval)
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
