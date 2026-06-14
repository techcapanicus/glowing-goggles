#!/usr/bin/env python3
"""Generate VM SSH key and provision authorized_keys on Semaphore-managed servers.

Uses inventories that passed ansible_ssh tests, runs provision_ssh.yml per host
via Semaphore, then tests SSH from this machine.

Usage:
  SEMAPHORE_URL=https://devops.nextere.com \\
  SEMAPHORE_USERNAME=user SEMAPHORE_PASSWORD=pass \\
  python3 scripts/provision_vm_ssh.py --from-ssh-tests

  python3 scripts/provision_vm_ssh.py --host 34.74.45.172 --user emir_ \\
      --project-id 10 --inventory-id 1 --ssh-key-id 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import Semaphore, find_by_name, load_or_generate_keypair, ok, info, warn  # noqa: E402
from scripts.semaphore_session import SemaphoreSession, from_env_or_login  # noqa: E402

REPO_URL = os.environ.get(
    "AUDIT_REPO_URL", "https://github.com/techcapanicus/glowing-goggles.git"
)
REPO_BRANCH = os.environ.get("AUDIT_REPO_BRANCH", "cursor/dev-ssh-key-provision-1218")
PLAYBOOK = "ansible/provision_ssh.yml"
REPO_NAME = "glowing-goggles-audit"
TEMPLATE_NAME = "VM SSH Provision"
KEY_DIR = os.environ.get("VM_KEY_DIR", "keys/vm-access")
KEY_COMMENT = "cursor-vm-access"


class Api:
    def __init__(self, session: SemaphoreSession):
        self.s = session

    def get(self, p):
        return self.s.get(p)

    def post(self, p, payload):
        return self.s.post(p, payload)

    def put(self, p, payload):
        return self.s.request("PUT", p, payload)


def is_real_host(host: dict) -> bool:
    addr = (host.get("ansible_host") or "").strip()
    if not addr:
        return False
    if addr in ("localhost", "127.0.0.1", "::1"):
        return False
    return True


def load_targets_from_ssh_tests(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        reports = json.load(fh)
    targets = []
    seen = set()
    for rep in reports:
        pid = rep["project_id"]
        pname = rep["project_name"]
        for inv in rep.get("inventories", []):
            if not inv.get("ansible_ssh"):
                continue
            for h in inv.get("hosts", []):
                if not is_real_host(h):
                    continue
                user = h.get("ansible_user") or "root"
                addr = h["ansible_host"]
                sig = (pid, addr, user)
                if sig in seen:
                    continue
                seen.add(sig)
                targets.append({
                    "project_id": pid,
                    "project_name": pname,
                    "inventory_id": inv["inventory_id"],
                    "inventory_name": inv["inventory_name"],
                    "ssh_key_id": inv.get("ssh_key_id"),
                    "host_name": h.get("name", addr),
                    "ansible_host": addr,
                    "ansible_user": user,
                })
    return targets


def ensure_repo(api: Api, pid: int) -> int:
    repos = api.get(f"/api/project/{pid}/repositories") or []
    repo = find_by_name(repos, REPO_NAME) or next(
        (r for r in repos if "glowing-goggles" in (r.get("git_url") or "")), None
    )
    if repo:
        return repo["id"]
    api.post(f"/api/project/{pid}/repositories", {
        "name": REPO_NAME,
        "project_id": pid,
        "git_url": REPO_URL,
        "git_branch": REPO_BRANCH,
        "ssh_key_id": 1,
    })
    repos = api.get(f"/api/project/{pid}/repositories") or []
    return find_by_name(repos, REPO_NAME)["id"]


def ensure_provision_template(api: Api, pid: int, inventory_id: int, repo_id: int) -> int:
    templates = api.get(f"/api/project/{pid}/templates") or []
    tpl = find_by_name(templates, TEMPLATE_NAME) or next(
        (t for t in templates
         if t.get("playbook") == PLAYBOOK and t.get("inventory_id") == inventory_id),
        None,
    )
    envs = api.get(f"/api/project/{pid}/environment") or []
    env_id = envs[0]["id"] if envs else 1
    payload = {
        "project_id": pid,
        "name": TEMPLATE_NAME,
        "playbook": PLAYBOOK,
        "inventory_id": inventory_id,
        "repository_id": repo_id,
        "environment_id": env_id,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": "Add VM access public key to authorized_keys",
    }
    if tpl:
        api.put(f"/api/project/{pid}/templates/{tpl['id']}", {**payload, "id": tpl["id"]})
        return tpl["id"]
    created = api.post(f"/api/project/{pid}/templates", payload)
    return created["id"]


def run_provision(api: Api, pid: int, template_id: int, host_name: str,
                  target_user: str, public_key: str, private_key: str,
                  poll: int, dry_run: bool) -> dict:
    extra = {
        "target_user": target_user,
        "new_public_key": public_key,
        "new_private_key": private_key,
    }
    task = api.post(f"/api/project/{pid}/tasks", {
        "template_id": template_id,
        "dry_run": dry_run,
        "limit": host_name,
        "environment": json.dumps(extra),
    })
    tid = task["id"]
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        time.sleep(poll)
        cur = api.get(f"/api/project/{pid}/tasks/{tid}")
        if cur.get("status") in terminal:
            break
    output = api.get(f"/api/project/{pid}/tasks/{tid}/output") or []
    text = "\n".join(e.get("output", "") for e in output)
    return {"task_id": tid, "status": cur.get("status"), "output": text}


def test_ssh(key_path: str, user: str, host: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["ssh", "-i", key_path, "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=no", "-o", f"ConnectTimeout={timeout}",
             "-o", "IdentitiesOnly=yes", f"{user}@{host}", "hostname && echo SSH_OK"],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)


def write_ssh_config(entries: list[dict], path: str):
    lines = ["# Generated by provision_vm_ssh.py", ""]
    for e in entries:
        alias = re.sub(r"[^a-zA-Z0-9_-]", "-", e["alias"])
        lines += [
            f"Host {alias}",
            f"  HostName {e['host']}",
            f"  User {e['user']}",
            f"  IdentityFile {e['key']}",
            "  StrictHostKeyChecking no",
            "",
        ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL", "https://devops.nextere.com"))
    p.add_argument("--token", default="")
    p.add_argument("--username", default=os.environ.get("SEMAPHORE_USERNAME"))
    p.add_argument("--password", default=os.environ.get("SEMAPHORE_PASSWORD"))
    p.add_argument("--from-ssh-tests", default="reports/ssh-tests/summary.json")
    p.add_argument("--project-id", type=int)
    p.add_argument("--inventory-id", type=int)
    p.add_argument("--ssh-key-id", type=int)
    p.add_argument("--host")
    p.add_argument("--user", default="root")
    p.add_argument("--host-name", help="inventory hostname for --limit")
    p.add_argument("--key-dir", default=KEY_DIR)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--poll", type=int, default=8)
    p.add_argument("--ssh-config", default=os.path.expanduser("~/.ssh/config.d/nextere-vm"))
    args = p.parse_args()

    session = from_env_or_login(
        args.url, args.token or None, args.username, args.password, url_explicit=True
    )
    api = Api(session)
    me = session.user()
    print(f"Authenticated: {me.get('username')} @ {session.base_url}")

    key_dir = os.path.expanduser(args.key_dir)
    os.makedirs(key_dir, mode=0o700, exist_ok=True)
    priv, pub, _ = load_or_generate_keypair("/tmp", key_dir)
    # Re-tag comment
    pub_line = pub.split()
    if len(pub_line) >= 2:
        pub = f"{pub_line[0]} {pub_line[1]} {KEY_COMMENT}"
    with open(os.path.join(key_dir, "id_ed25519.pub"), "w", encoding="utf-8") as fh:
        fh.write(pub + "\n")
    priv_path = os.path.abspath(os.path.join(key_dir, "id_ed25519"))
    print(f"VM key: {priv_path}")
    print(f"Public: {pub[:72]}...")

    if args.host:
        if not args.project_id or not args.inventory_id:
            print("Manual host requires --project-id and --inventory-id", file=sys.stderr)
            return 2
        targets = [{
            "project_id": args.project_id,
            "project_name": "manual",
            "inventory_id": args.inventory_id,
            "inventory_name": "manual",
            "ssh_key_id": args.ssh_key_id,
            "host_name": args.host_name or args.host,
            "ansible_host": args.host,
            "ansible_user": args.user,
        }]
    else:
        if not os.path.isfile(args.from_ssh_tests):
            print(f"Missing {args.from_ssh_tests} — run test_semaphore_ssh_all.py first",
                  file=sys.stderr)
            return 2
        targets = load_targets_from_ssh_tests(args.from_ssh_tests)
        print(f"Targets from ssh-tests: {len(targets)}")

    results = []
    repo_cache: dict[int, int] = {}
    tpl_cache: dict[tuple[int, int], int] = {}

    for t in targets:
        pid = t["project_id"]
        iid = t["inventory_id"]
        host = t["ansible_host"]
        user = t["ansible_user"]
        hname = t["host_name"]
        label = f"{user}@{host} [{t['project_name']}/{t['inventory_name']}]"
        print(f"\n{'=' * 60}\nProvision {label}")

        if not repo_cache.get(pid):
            repo_cache[pid] = ensure_repo(api, pid)
        cache_key = (pid, iid)
        if cache_key not in tpl_cache:
            tpl_cache[cache_key] = ensure_provision_template(
                api, pid, iid, repo_cache[pid])
        tpl_id = tpl_cache[cache_key]

        try:
            res = run_provision(
                api, pid, tpl_id, hname, user, pub, priv,
                args.poll, args.dry_run,
            )
            ok_flag = res["status"] == "success"
            print(f"  task #{res['task_id']} {res['status']}")
            if not ok_flag:
                print(res["output"][-1500:])
        except Exception as exc:
            ok_flag = False
            res = {"task_id": None, "status": "error", "output": str(exc)}
            print(f"  ERROR: {exc}")

        ssh_ok, ssh_msg = False, "skipped (dry-run)" if args.dry_run else ""
        if ok_flag and not args.dry_run:
            ssh_ok, ssh_msg = test_ssh(priv_path, user, host)
            print(f"  VM SSH: {'OK' if ssh_ok else 'FAIL'} — {ssh_msg[:120]}")

        results.append({
            **t,
            "provision_status": res["status"],
            "task_id": res["task_id"],
            "vm_ssh_ok": ssh_ok,
            "vm_ssh_msg": ssh_msg,
        })

    ssh_entries = [
        {
            "alias": f"{r['project_name']}-{r['host_name']}",
            "host": r["ansible_host"],
            "user": r["ansible_user"],
            "key": priv_path,
        }
        for r in results if r["provision_status"] == "success"
    ]
    if ssh_entries and not args.dry_run:
        write_ssh_config(ssh_entries, args.ssh_config)
        print(f"\nSSH config: {args.ssh_config}")

    out = os.path.join("reports", "vm-provision.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print(f"\n{'=' * 60}\nSUMMARY")
    prov_ok = [r for r in results if r["provision_status"] == "success"]
    ssh_ok = [r for r in results if r.get("vm_ssh_ok")]
    print(f"  Provisioned: {len(prov_ok)}/{len(results)}")
    print(f"  VM SSH OK:   {len(ssh_ok)}/{len(results)}")
    for r in prov_ok:
        vm = "SSH_OK" if r.get("vm_ssh_ok") else "SSH_BLOCKED"
        print(f"    {r['ansible_user']}@{r['ansible_host']} — {vm}")
    for r in results:
        if r["provision_status"] != "success":
            print(f"    FAIL {r['ansible_user']}@{r['ansible_host']} — {r['provision_status']}")
    print(f"\nReport: {out}")
    return 0 if prov_ok else 2


if __name__ == "__main__":
    sys.exit(main())
