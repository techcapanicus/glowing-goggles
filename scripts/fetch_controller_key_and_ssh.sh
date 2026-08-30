#!/usr/bin/env python3
"""Fetch working controller SSH key via Semaphore and save locally for jump SSH."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, die, find_by_name, load_dotenv, ok, info  # noqa: E402

PLAYBOOK = "ansible/export_working_ssh_key.yml"
TEMPLATE_NAME = "Export Working SSH Key"
KEY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keys", "mcm-controller")
PRIV = os.path.join(KEY_DIR, "id_ed25519")
PUB = os.path.join(KEY_DIR, "id_ed25519.pub")
JUMP = "209.38.146.146"
TARGET = "64.23.139.247"


def run_export(api, pid, repo_id, poll=10):
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
        "description": "Export /root/.ssh/id_ed25519 from Semaphore controller (works for 64.23.139.247)",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{pid}/templates/{existing['id']}", payload)
        tpl_id = existing["id"]
    else:
        created = api.post(f"/api/project/{pid}/templates", payload)
        tpl_id = created["id"] if isinstance(created, dict) else \
            find_by_name(api.get(f"/api/project/{pid}/templates"), TEMPLATE_NAME)["id"]

    task = api.post(f"/api/project/{pid}/tasks", {"template_id": tpl_id})
    task_id = task["id"]
    ok(f"Export task #{task_id} queued")
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        status = api.get(f"/api/project/{pid}/tasks/{task_id}").get("status")
        if status in terminal:
            break
        time.sleep(poll)
    output = api.get(f"/api/project/{pid}/tasks/{task_id}/output")
    return "\n".join(e.get("output", "") for e in (output or []))


def parse_b64(text, label):
    m = re.search(rf"{label}=([A-Za-z0-9+/=]+)", text)
    if not m:
        die(f"Could not find {label} in task output")
    return base64.b64decode(m.group(1))


def save_keys(priv_pem: bytes, pub_pem: bytes):
    os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
    with open(PRIV, "wb") as f:
        f.write(priv_pem if priv_pem.endswith(b"\n") else priv_pem + b"\n")
    os.chmod(PRIV, 0o600)
    with open(PUB, "wb") as f:
        f.write(pub_pem if pub_pem.endswith(b"\n") else pub_pem + b"\n")
    ok(f"Saved {PRIV}")


def ssh_test(cmd: str):
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        "-i", PRIV,
        "-J", f"root@{JUMP}",
        f"root@{TARGET}",
        cmd,
    ]
    info(f"Running: ssh -J root@{JUMP} -i keys/mcm-controller/id_ed25519 root@{TARGET}")
    return subprocess.run(argv, capture_output=True, text=True)


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=6)
    p.add_argument("--repository-id", type=int, default=6)
    p.add_argument("--cmd", default="echo SSH_OK; hostname; id")
    p.add_argument("--skip-export", action="store_true", help="Use existing keys/mcm-controller/")
    args = p.parse_args()

    if not args.skip_export:
        if not args.url or not args.token:
            die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")
        text = run_export(Semaphore(args.url.rstrip("/"), args.token), args.project_id, args.repository_id)
        priv = parse_b64(text, "KEY_B64")
        pub = parse_b64(text, "PUB_B64")
        save_keys(priv, pub)

    if not os.path.isfile(PRIV):
        die(f"Missing {PRIV}; run without --skip-export first")

    result = ssh_test(args.cmd)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode == 0:
        ok("SSH via jump host succeeded")
    else:
        info("Direct jump failed from this host (firewall?). Use Semaphore remote-exec instead.")
        return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
