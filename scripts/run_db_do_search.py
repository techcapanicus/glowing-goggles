#!/usr/bin/env python3
"""Run database DO-config search on Semaphore inventory via search_db_do_config.yml."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOK = "ansible/search_db_do_config.yml"


def env(key, default=None):
    return os.environ.get(key, default)


def ensure_template(api, project_id, name, playbook, inventory_id, repository_id, environment_id):
    templates = api.get(f"/api/project/{project_id}/templates")
    existing = find_by_name(templates, name)
    payload = {
        "project_id": project_id,
        "name": name,
        "playbook": playbook,
        "inventory_id": inventory_id,
        "repository_id": repository_id,
        "environment_id": environment_id,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": "Search MySQL/Mongo for DigitalOcean firewall API config",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{project_id}/templates/{existing['id']}", payload)
        ok(f"Updated template '{name}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/templates", payload)
    tpl_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/templates"), name)["id"]
    ok(f"Created template '{name}' (id {tpl_id})")
    return tpl_id


def run_task(api, project_id, template_id, poll_interval):
    task = api.post(f"/api/project/{project_id}/tasks", {"template_id": template_id})
    task_id = task["id"]
    ok(f"Task #{task_id} queued")
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        current = api.get(f"/api/project/{project_id}/tasks/{task_id}")
        status = current.get("status")
        if status in terminal:
            break
        time.sleep(poll_interval)
    output = api.get(f"/api/project/{project_id}/tasks/{task_id}/output")
    print("\n----- task output -----")
    for entry in output or []:
        print(entry.get("output", ""))
    print("----- end output -----\n")
    return 0 if status == "success" else 2


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=int(env("SEMAPHORE_PROJECT_ID", "6")))
    p.add_argument("--inventory-id", type=int, default=21)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--environment-id", type=int, default=172)
    p.add_argument("--poll-interval", type=int, default=10)
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    tpl_id = ensure_template(
        api, args.project_id, "db-do-config-search", PLAYBOOK,
        args.inventory_id, args.repository_id, args.environment_id)
    return run_task(api, args.project_id, tpl_id, args.poll_interval)


if __name__ == "__main__":
    sys.exit(main())
