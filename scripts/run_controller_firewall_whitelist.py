#!/usr/bin/env python3
"""Run controller-side DO token scan then firewall whitelist via Semaphore."""
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

SCAN_PLAYBOOK = "ansible/find_doctl_on_controller.yml"
BASH_TEMPLATE = "SSH Firewall Whitelist (Bash)"
LOCALHOST_INV = 15
ENV_ID = 173
TOKEN_RE = re.compile(r"dop_v1_[a-f0-9]+")
ACCESS_RE = re.compile(r"access-token:\s*(\S+)")


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


def ensure_scan_template(api, pid, repo_id):
    templates = api.get(f"/api/project/{pid}/templates")
    name = "Find doctl on Controller"
    existing = find_by_name(templates, name)
    payload = {
        "project_id": pid,
        "name": name,
        "playbook": SCAN_PLAYBOOK,
        "inventory_id": LOCALHOST_INV,
        "repository_id": repo_id,
        "environment_id": ENV_ID,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": "Scan Semaphore controller for doctl/DO API credentials",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{pid}/templates/{existing['id']}", payload)
        return existing["id"]
    created = api.post(f"/api/project/{pid}/templates", payload)
    return created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{pid}/templates"), name)["id"]


def run_task(api, pid, template_id, extra_vars=None):
    body = {"template_id": template_id}
    if extra_vars:
        body["environment"] = json.dumps(extra_vars)
    task = api.post(f"/api/project/{pid}/tasks", body)
    task_id = task["id"]
    ok(f"Task #{task_id} queued")
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        current = api.get(f"/api/project/{pid}/tasks/{task_id}")
        status = current.get("status")
        if status in terminal:
            break
        time.sleep(10)
    output = api.get(f"/api/project/{pid}/tasks/{task_id}/output")
    text = "\n".join(entry.get("output", "") for entry in (output or []))
    print(text)
    return status, text


def extract_token(text):
    m = TOKEN_RE.search(text)
    if m:
        return m.group(0)
    m = ACCESS_RE.search(text)
    if m:
        return m.group(1).strip("'\"")
    return ""


def update_env_token(api, pid, env_id, do_token, target_ip=""):
    envs = api.get(f"/api/project/{pid}/environment")
    match = next((e for e in envs if e["id"] == env_id), None)
    if not match:
        return
    j = json.loads(match.get("json") or "{}")
    e = json.loads(match.get("env") or "{}")
    j["DO_TOKEN"] = do_token
    e["DO_TOKEN"] = do_token
    if target_ip:
        j["TARGET_IP"] = target_ip
        e["TARGET_IP"] = target_ip
    api._request("PUT", f"/api/project/{pid}/environment/{env_id}", {
        "id": env_id,
        "name": match["name"],
        "project_id": pid,
        "json": json.dumps(j),
        "env": json.dumps(e),
    })
    ok("Updated do-firewall-access with DO_TOKEN from controller")


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--target-ip", default=env("TARGET_IP", ""))
    args = p.parse_args()
    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    target_ip = args.target_ip or detect_public_ip()
    info(f"TARGET_IP={target_ip or '(auto on controller)'}")

    scan_tpl = ensure_scan_template(api, args.project_id, args.repository_id)
    status, text = run_task(api, args.project_id, scan_tpl)
    do_token = extract_token(text)
    if not do_token:
        die("No DO token found on Semaphore controller (check doctl config)")

    update_env_token(api, args.project_id, ENV_ID, do_token, target_ip)

    templates = api.get(f"/api/project/{args.project_id}/templates")
    bash = find_by_name(templates, BASH_TEMPLATE)
    if not bash:
        die(f"Template '{BASH_TEMPLATE}' not found")
    extra = {"TARGET_IP": target_ip, "DO_TOKEN": do_token} if target_ip else {"DO_TOKEN": do_token}
    status, text = run_task(api, args.project_id, bash["id"], extra)
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
