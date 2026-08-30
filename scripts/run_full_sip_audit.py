#!/usr/bin/env python3
"""Full SIP/DID audit pipeline for Nextere Semaphore.

Steps:
  1. Fix ENV-DUMP / SHELL-DUMP templates
  2. Test all API keys from Semaphore environments
  3. Test SSH on all inventories
  4. Provision SSH key on reachable hosts (ASR / Semaphore runner)
  5. Run SIP intel playbooks on provisioned hosts
  6. Report blocked hosts (Azure NSG — port 22 closed)

Usage:
  SEMAPHORE_URL=https://devops.nextere.com \\
  SEMAPHORE_USERNAME=user SEMAPHORE_PASSWORD=pass \\
  python3 scripts/run_full_sip_audit.py [--skip-ssh-test]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.semaphore_session import from_env_or_login  # noqa: E402


def run_script(name: str) -> int:
    path = os.path.join(os.path.dirname(__file__), name)
    print(f"\n{'='*60}\n>>> {name}\n{'='*60}")
    return subprocess.call([sys.executable, path], env=os.environ.copy())


def provision_reachable(session, pub: str, priv: str) -> list[dict]:
    """Provision SSH on hosts that respond to port 22 from Semaphore runner."""
    results = []
    # ASR is in multiple inventories — template 22 on project 1
    extra = {
        "target_user": "root",
        "new_public_key": pub,
        "new_private_key": priv,
        "run_enumeration": True,
    }
    for pid, tpl, host in [(1, 22, "asr"), (11, 22, "asr")]:
        try:
            tpls = session.get(f"/api/project/{pid}/templates") or []
            vm = next((t for t in tpls if t.get("playbook") == "ansible/provision_ssh.yml"), None)
            if not vm:
                continue
            task = session.post(f"/api/project/{pid}/tasks", {
                "template_id": vm["id"],
                "limit": host,
                "environment": json.dumps(extra),
            })
            tid = task["id"]
            for _ in range(60):
                time.sleep(4)
                cur = session.get(f"/api/project/{pid}/tasks/{tid}")
                if cur["status"] in ("success", "error", "stopped"):
                    results.append({"project": pid, "host": host, "status": cur["status"], "task": tid})
                    break
        except Exception as exc:
            results.append({"project": pid, "host": host, "status": f"exception: {exc}"})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ssh-test", action="store_true")
    parser.add_argument("--key-dir", default="/tmp", help="Directory with semaphore-provision[.pub]")
    args = parser.parse_args()

    key_path = os.path.join(args.key_dir, "semaphore-provision")
    pub_path = key_path + ".pub"
    if not os.path.exists(pub_path):
        subprocess.check_call([
            "ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "semaphore-provision"
        ])

    run_script("setup_dump_templates.py")
    run_script("test_all_api_keys.py")
    if not args.skip_ssh_test:
        run_script("test_semaphore_ssh_all.py")

    session = from_env_or_login()
    pub = open(pub_path).read().strip()
    priv = open(key_path).read()
    prov = provision_reachable(session, pub, priv)
    print("\n=== SSH Provision Results ===")
    print(json.dumps(prov, indent=2))

    blocked = [
        "172.178.82.217 (sipcore2)", "48.217.232.252 (sipmedia2)",
        "172.203.226.201 (sipproxy2/web2)", "149.130.210.6 (probe)",
        "20.163.30.193 (phone-crm-dev)", "172.203.249.36 (phone-crm-live)",
        "4.236.165.103 (ringtere-qa/prod)",
    ]
    print("\n=== BLOCKED HOSTS (Azure NSG — port 22 closed from Semaphore runner) ===")
    for h in blocked:
        print(f"  - {h}")
    print("\nTo unblock: run 'Whitelist Semaphore SSH — dev' (template 32) with Azure SP creds:")
    print("  AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID")
    print("Or add NSG inbound rule: allow tcp/22 from 64.23.158.213/32 (Semaphore ASR runner)")


if __name__ == "__main__":
    main()
