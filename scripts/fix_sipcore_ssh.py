#!/usr/bin/env python3
"""Update Voice dev inventory on Nextere Semaphore and test sipcore SSH.

Steps:
  1. PUT inventory/nextere-voice-dev.yml to project 1 / inventory 2 (Azure hosts).
  2. Optionally set ssh_key_id (default: 4 = ansible key).
  3. Run SIP probe or SSH audit limited to sipcore2.

Usage:
  SEMAPHORE_URL=https://devops.nextere.com \\
  SEMAPHORE_USERNAME=user SEMAPHORE_PASSWORD=pass \\
  python3 scripts/fix_sipcore_ssh.py --update-inventory --test-sipcore

  python3 scripts/fix_sipcore_ssh.py --whitelist-template --ensure-template
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import find_by_name  # noqa: E402
from scripts.semaphore_session import from_env_or_login  # noqa: E402

REPO = os.environ.get(
    "AUDIT_REPO_URL", "https://github.com/techcapanicus/glowing-goggles.git"
)
BRANCH = os.environ.get("AUDIT_REPO_BRANCH", "cursor/dev-ssh-key-provision-1218")
PROJECT_ID = int(os.environ.get("SEMAPHORE_PROJECT_ID", "1"))
DEV_INVENTORY_ID = int(os.environ.get("VOICE_DEV_INVENTORY_ID", "2"))
INV_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "inventory", "nextere-voice-dev.yml")
WHITELIST_PLAYBOOK = "ansible/whitelist_semaphore_ssh.yml"
PROBE_PLAYBOOK = "ansible/probe_sip_cmd.yml"
AUDIT_PLAYBOOK = "ansible/audit_ssh_connections.yml"
REPO_NAME = "glowing-goggles-audit"


class Api:
    def __init__(self, session):
        self.s = session

    def get(self, path):
        return self.s.get(path)

    def post(self, path, payload):
        return self.s.post(path, payload)

    def put(self, path, payload):
        return self.s.request("PUT", path, payload)


def ensure_repo(api: Api) -> int:
    repos = api.get(f"/api/project/{PROJECT_ID}/repositories") or []
    repo = find_by_name(repos, REPO_NAME) or next(
        (r for r in repos if "glowing-goggles" in (r.get("git_url") or "")), None
    )
    if repo:
        return repo["id"]
    api.post(f"/api/project/{PROJECT_ID}/repositories", {
        "name": REPO_NAME,
        "project_id": PROJECT_ID,
        "git_url": REPO,
        "git_branch": BRANCH,
        "ssh_key_id": 1,
    })
    repos = api.get(f"/api/project/{PROJECT_ID}/repositories") or []
    return find_by_name(repos, REPO_NAME)["id"]


def ensure_template(api: Api, name: str, playbook: str, repo_id: int,
                    env_id: int, extra: dict | None = None) -> int:
    templates = api.get(f"/api/project/{PROJECT_ID}/templates") or []
    existing = find_by_name(templates, name)
    payload = {
        "project_id": PROJECT_ID,
        "name": name,
        "playbook": playbook,
        "inventory_id": DEV_INVENTORY_ID,
        "repository_id": repo_id,
        "environment_id": env_id,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": name,
    }
    if existing:
        payload["id"] = existing["id"]
        api.put(f"/api/project/{PROJECT_ID}/templates/{existing['id']}", payload)
        return existing["id"]
    created = api.post(f"/api/project/{PROJECT_ID}/templates", payload)
    return created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{PROJECT_ID}/templates"), name)["id"]


def run_task(api: Api, template_id: int, arguments: str = "",
             extra_vars: dict | None = None, poll: int = 8) -> dict:
    body = {"template_id": template_id}
    if extra_vars:
        body["environment"] = json.dumps(extra_vars)
    if arguments:
        body["arguments"] = arguments
    task = api.post(f"/api/project/{PROJECT_ID}/tasks", body)
    tid = task["id"]
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        time.sleep(poll)
        cur = api.get(f"/api/project/{PROJECT_ID}/tasks/{tid}")
        if cur.get("status") in terminal:
            break
    output = api.get(f"/api/project/{PROJECT_ID}/tasks/{tid}/output") or []
    text = "\n".join(e.get("output", "") for e in output)
    return {"task_id": tid, "status": cur.get("status"), "output": text}


def update_inventory(api: Api, ssh_key_id: int | None) -> None:
    with open(INV_FILE, encoding="utf-8") as fh:
        inventory_yaml = fh.read()
    inv = api.get(f"/api/project/{PROJECT_ID}/inventory/{DEV_INVENTORY_ID}")
    payload = {
        "id": DEV_INVENTORY_ID,
        "project_id": PROJECT_ID,
        "name": inv.get("name") or "dev",
        "inventory": inventory_yaml,
        "ssh_key_id": ssh_key_id or inv.get("ssh_key_id") or 4,
        "type": inv.get("type", ""),
    }
    api.put(f"/api/project/{PROJECT_ID}/inventory/{DEV_INVENTORY_ID}", payload)
    print(f"Updated inventory {DEV_INVENTORY_ID} ({len(inventory_yaml)} bytes), "
          f"ssh_key_id={payload['ssh_key_id']}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL", "https://devops.nextere.com"))
    p.add_argument("--token", default="")
    p.add_argument("--username", default=os.environ.get("SEMAPHORE_USERNAME"))
    p.add_argument("--password", default=os.environ.get("SEMAPHORE_PASSWORD"))
    p.add_argument("--update-inventory", action="store_true")
    p.add_argument("--ssh-key-id", type=int, default=4, help="Semaphore key (4=ansible)")
    p.add_argument("--ensure-template", action="store_true")
    p.add_argument("--whitelist-template", action="store_true")
    p.add_argument("--test-sipcore", action="store_true")
    p.add_argument("--audit-ssh", action="store_true")
    p.add_argument("--poll", type=int, default=8)
    args = p.parse_args()

    session = from_env_or_login(
        args.url, args.token or None, args.username, args.password, url_explicit=True
    )
    api = Api(session)
    me = session.user()
    print(f"Authenticated: {me.get('username')} @ {session.base_url}")

    if args.update_inventory:
        update_inventory(api, args.ssh_key_id)

    envs = api.get(f"/api/project/{PROJECT_ID}/environment") or []
    env_id = envs[0]["id"] if envs else 1
    repo_id = ensure_repo(api) if (args.ensure_template or args.whitelist_template
                                   or args.test_sipcore or args.audit_ssh) else None

    if args.whitelist_template or args.ensure_template:
        tpl = ensure_template(api, "Whitelist Semaphore SSH — dev",
                              WHITELIST_PLAYBOOK, repo_id, env_id)
        print(f"Template Whitelist Semaphore SSH — dev: {tpl}")
        if args.whitelist_template:
            result = run_task(api, tpl, extra_vars={"TARGET_IP": "64.23.158.213"}, poll=args.poll)
            print(f"Whitelist task #{result['task_id']} {result['status']}")
            print(result["output"][-4000:])

    if args.test_sipcore:
        tpl = ensure_template(api, "SIP probe sipcore2 — dev", PROBE_PLAYBOOK, repo_id, env_id)
        result = run_task(api, tpl, arguments='["--limit","sipcore2"]', poll=args.poll)
        print(f"Probe task #{result['task_id']} {result['status']}")
        print(result["output"][-4000:])

    if args.audit_ssh:
        tpl = ensure_template(api, "SSH test sipcore2 — dev", AUDIT_PLAYBOOK, repo_id, env_id)
        result = run_task(api, tpl,
                          arguments='["--limit","sipcore2"]',
                          extra_vars={"audit_mode": "test"},
                          poll=args.poll)
        print(f"Audit task #{result['task_id']} {result['status']}")
        print(result["output"][-4000:])

    return 0


if __name__ == "__main__":
    sys.exit(main())
