#!/usr/bin/env python3
"""Register and optionally run Get DO Token + Whitelist SSH (One Shot) template.

Usage:
  ./scripts/setup_get_do_token_template.py
  ./scripts/setup_get_do_token_template.py --run --target-ip 203.0.113.10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

DEFAULT_PROJECT_ID = 6
DEFAULT_INVENTORY_ID = 21
DEFAULT_REPOSITORY_ID = 6
DEFAULT_ENV_ID = 173
PLAYBOOK = "ansible/get_do_token_and_whitelist.yml"
TEMPLATE_NAME = "Get DO Token + Whitelist SSH (One Shot)"
TOKEN_RE = re.compile(r"dop_v1_[a-f0-9]+")


def env(key, default=None):
    return os.environ.get(key, default)


def detect_public_ip():
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                ip = resp.read().decode().strip()
                if ip:
                    return ip
        except OSError:
            continue
    return ""


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
        "description": (
            "One-shot: extract DO token from droplet metadata/agent on "
            "64.23.139.247 and whitelist TARGET_IP on attached firewalls"
        ),
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


def update_do_token_in_env(api, project_id, env_id, do_token, target_ip=""):
    envs = api.get(f"/api/project/{project_id}/environment")
    match = next((e for e in envs if e["id"] == env_id), None)
    if not match:
        return
    json_vars = json.loads(match.get("json") or "{}")
    env_vars = json.loads(match.get("env") or "{}")
    json_vars["DO_TOKEN"] = do_token
    env_vars["DO_TOKEN"] = do_token
    if target_ip:
        json_vars["TARGET_IP"] = target_ip
        env_vars["TARGET_IP"] = target_ip
    payload = {
        "id": env_id,
        "name": match["name"],
        "project_id": project_id,
        "json": json.dumps(json_vars),
        "env": json.dumps(env_vars),
    }
    api._request("PUT", f"/api/project/{project_id}/environment/{env_id}", payload)
    ok(f"Stored DO_TOKEN in '{match['name']}' variable group")


def run_task(api, project_id, template_id, extra_vars, poll_interval):
    task = api.post(f"/api/project/{project_id}/tasks", {
        "template_id": template_id,
        "environment": json.dumps(extra_vars),
    })
    task_id = task["id"]
    ok(f"Task #{task_id} queued")
    terminal = {"success", "error", "failed", "stopped"}
    status = None
    while True:
        current = api.get(f"/api/project/{project_id}/tasks/{task_id}")
        status = current.get("status")
        if status in terminal:
            break
        time.sleep(poll_interval)
    output = api.get(f"/api/project/{project_id}/tasks/{task_id}/output")
    text = "\n".join(entry.get("output", "") for entry in (output or []))
    print("\n----- task output -----\n")
    print(text)
    print("\n----- end output -----\n")
    return status, text


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=int(env("SEMAPHORE_PROJECT_ID", "6")))
    p.add_argument("--inventory-id", type=int, default=DEFAULT_INVENTORY_ID)
    p.add_argument("--repository-id", type=int, default=DEFAULT_REPOSITORY_ID)
    p.add_argument("--environment-id", type=int, default=DEFAULT_ENV_ID)
    p.add_argument("--target-ip", default=env("TARGET_IP", ""))
    p.add_argument("--run", action="store_true")
    p.add_argument("--poll-interval", type=int, default=10)
    args = p.parse_args(argv)

    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    tpl_id = ensure_template(
        api, args.project_id, TEMPLATE_NAME, PLAYBOOK,
        args.inventory_id, args.repository_id, args.environment_id)

    print()
    ok("Template registered:")
    print(f"    template_id    = {tpl_id}")
    print(f"    inventory_id   = {args.inventory_id}")
    print(f"    environment_id = {args.environment_id}")
    print(f"    playbook       = {PLAYBOOK}")

    if not args.run:
        return 0

    target_ip = args.target_ip or detect_public_ip()
    extra_vars = {"TARGET_IP": target_ip} if target_ip else {}
    if target_ip:
        info(f"TARGET_IP={target_ip}")

    status, text = run_task(api, args.project_id, tpl_id, extra_vars, args.poll_interval)

    found = TOKEN_RE.search(text)
    if found:
        update_do_token_in_env(api, args.project_id, args.environment_id,
                               found.group(0), target_ip)

    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
