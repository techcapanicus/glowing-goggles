#!/usr/bin/env python3
"""Register and run SSH alternative access playbooks via Semaphore."""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOKS = {
    "diagnose": ("ansible/diagnose_controller_ports.yml", "Diagnose Controller Ports", 21),
    "443": ("ansible/setup_ssh_on_443.yml", "Setup SSH on Port 443", 15),
    "tunnel": ("ansible/reverse_tunnel.yml", "Reverse SSH Tunnel", 21),
    "socat": ("ansible/setup_nc_relay.yml", "Setup Socat Relay", 15),
    "recover": ("ansible/recover_nginx_semaphore.yml", "Recover Nginx Semaphore", 15),
}
ENV_ID = 172
REPO_ID = 6


def ensure_template(api, pid, key):
    playbook, name, inv_id = PLAYBOOKS[key]
    templates = api.get(f"/api/project/{pid}/templates")
    existing = find_by_name(templates, name)
    payload = {
        "project_id": pid,
        "name": name,
        "playbook": playbook,
        "inventory_id": inv_id,
        "repository_id": REPO_ID,
        "environment_id": ENV_ID,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": f"SSH alternative access: {key}",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{pid}/templates/{existing['id']}", payload)
        return existing["id"]
    created = api.post(f"/api/project/{pid}/templates", payload)
    return created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{pid}/templates"), name)["id"]


def run_task(api, pid, tpl_id, poll=10):
    task = api.post(f"/api/project/{pid}/tasks", {"template_id": tpl_id})
    task_id = task["id"]
    ok(f"Task #{task_id} queued")
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        status = api.get(f"/api/project/{pid}/tasks/{task_id}").get("status")
        if status in terminal:
            break
        time.sleep(poll)
    output = api.get(f"/api/project/{pid}/tasks/{task_id}/output")
    text = "\n".join(e.get("output", "") for e in (output or []))
    print("\n----- task output -----\n")
    print(text)
    print("\n----- end output -----\n")
    return status, text


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=list(PLAYBOOKS.keys()) + ["all"],
                   help="diagnose | 443 | tunnel | socat | all")
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    actions = list(PLAYBOOKS.keys()) if args.action == "all" else [args.action]
    rc = 0
    for action in actions:
        info(f"Running: {action}")
        tpl_id = ensure_template(api, args.project_id, action)
        ok(f"Template {PLAYBOOKS[action][1]} (id {tpl_id})")
        status, _ = run_task(api, args.project_id, tpl_id)
        if status != "success":
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
