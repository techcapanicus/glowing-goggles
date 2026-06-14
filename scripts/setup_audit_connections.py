#!/usr/bin/env python3
"""Register and run Audit SSH Connections template via Semaphore."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOK = "ansible/audit_ssh_connections.yml"
TEMPLATE_NAME = "Audit SSH Connections"


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
            "Collect authorized_keys on inventory hosts and test SSH auth "
            "from the Semaphore controller to all targets"
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


def run_task(api, pid, template_id, extra_vars, poll_interval):
    payload = {"template_id": template_id}
    if extra_vars:
        payload["environment"] = json.dumps(extra_vars)
    task = api.post(f"/api/project/{pid}/tasks", payload)
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
    p.add_argument("--project-id", type=int, default=int(os.environ.get("SEMAPHORE_PROJECT_ID", "6")))
    p.add_argument("--inventory-id", type=int, required=True)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--environment-id", type=int, default=172)
    p.add_argument("--audit-targets", help="Comma-separated hosts for controller SSH tests")
    p.add_argument("--target-user", default="root")
    p.add_argument("--audit-mode", choices=["collect", "test", "full"], default="full")
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

    extra = {"audit_mode": args.audit_mode, "target_user": args.target_user}
    if args.audit_targets:
        extra["audit_targets"] = args.audit_targets

    if not args.run:
        info("Pass --run to execute the audit playbook")
        return 0
    status, _ = run_task(api, args.project_id, tpl_id, extra, args.poll_interval)
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
