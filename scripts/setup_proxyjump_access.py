#!/usr/bin/env python3
"""Register, run setup_proxyjump_access.yml, and save jump key locally."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOK = "ansible/setup_proxyjump_access.yml"
TEMPLATE_NAME = "Setup ProxyJump Access"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    return status, "\n".join(e.get("output", "") for e in (output or []))


def extract_private_key(text: str) -> str:
    m = re.search(
        r"(-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]*?-----END OPENSSH PRIVATE KEY-----)",
        text,
    )
    if not m:
        die("Private key not found in task output")
    key = m.group(1)
    # Ansible debug may escape newlines as literal \n
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    return key.strip() + "\n"


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--inventory-id", type=int, default=21)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--environment-id", type=int, default=172)
    p.add_argument("--skip-run", action="store_true")
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
        "description": "Setup ProxyJump: authorize media key on controller and target",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{args.project_id}/templates/{existing['id']}", payload)
        tpl_id = existing["id"]
        ok(f"Updated template (id {tpl_id})")
    else:
        created = api.post(f"/api/project/{args.project_id}/templates", payload)
        tpl_id = created["id"] if isinstance(created, dict) else \
            find_by_name(api.get(f"/api/project/{args.project_id}/templates"), TEMPLATE_NAME)["id"]
        ok(f"Created template (id {tpl_id})")

    if args.skip_run:
        return 0

    status, text = run_task(api, args.project_id, tpl_id)
    print(text)
    if status != "success":
        return 2

    key_pem = extract_private_key(text)
    tmp_key = os.path.join(REPO_ROOT, "keys", "media_id_ed25519")
    os.makedirs(os.path.dirname(tmp_key), mode=0o700, exist_ok=True)
    with open(tmp_key, "w", encoding="utf-8") as f:
        f.write(key_pem)
    os.chmod(tmp_key, 0o600)
    ok(f"Wrote {tmp_key}")

    save_sh = os.path.join(REPO_ROOT, "scripts", "save_jump_key.sh")
    subprocess.run(
        [save_sh, "--from-file", tmp_key],
        check=False,
        env={**os.environ, "HOME": os.environ.get("HOME", "/home/ubuntu")},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
