#!/usr/bin/env python3
"""Test SSH connections for all Semaphore inventories via controller SSH audit.

Runs ansible/audit_ssh_connections.yml (audit_mode=test) per inventory that has
hosts and an ssh_key_id. Parses GOOD/BAD/UNREACHABLE from task output.

Usage:
  SEMAPHORE_URL=https://devops.nextere.com \\
  SEMAPHORE_USERNAME=user SEMAPHORE_PASSWORD=pass \\
  python3 scripts/test_semaphore_ssh_all.py --all-projects

  python3 scripts/test_semaphore_ssh_all.py --url https://devops.nextere.com \\
      --token 'TOKEN' --all-projects --ensure-template
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import find_by_name  # noqa: E402
from scripts.list_semaphore_connections import parse_inventory_hosts  # noqa: E402
from scripts.semaphore_session import SemaphoreSession, from_env_or_login  # noqa: E402

AUDIT_REPO = os.environ.get(
    "AUDIT_REPO_URL", "https://github.com/techcapanicus/glowing-goggles.git"
)
AUDIT_BRANCH = os.environ.get("AUDIT_REPO_BRANCH", "cursor/dev-ssh-key-provision-1218")
AUDIT_PLAYBOOK = "ansible/audit_ssh_connections.yml"
TEMPLATE_PREFIX = "Playwright SSH Test"
REPO_NAME = "glowing-goggles-audit"

ANSI = re.compile(r"\u001b\[[0-9;]*m")
GOOD = re.compile(r"GOOD\s+key=(\S+)\s+fp=(\S+)\s+->\s*(.+)", re.I)
BAD = re.compile(r"BAD\s+key=(\S+)\s+fp=(\S+)\s+->\s*(.+)", re.I)
PORT_UNREACH = re.compile(r"PORT:\s*UNREACHABLE", re.I)
PORT_OPEN = re.compile(r"PORT:\s*tcp/22 reachable", re.I)
TARGET = re.compile(r"--- target (\S+@\S+:\d+) ---")


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def parse_ssh_test_output(text: str) -> list[dict]:
    clean = strip_ansi(text)
    results = []
    current = None
    for line in clean.splitlines():
        line = line.strip()
        tm = TARGET.search(line)
        if tm:
            current = {"target": tm.group(1), "status": "unknown", "good": [], "bad": []}
            results.append(current)
            continue
        if not current:
            continue
        if PORT_UNREACH.search(line):
            current["status"] = "unreachable"
        elif PORT_OPEN.search(line):
            current["status"] = "port_open"
        gm = GOOD.search(line)
        if gm:
            current["good"].append({
                "key": gm.group(1), "fingerprint": gm.group(2), "output": gm.group(3).strip()
            })
            current["status"] = "good"
            continue
        bm = BAD.search(line)
        if bm:
            current["bad"].append({
                "key": bm.group(1), "fingerprint": bm.group(2), "error": bm.group(3).strip()
            })
            if current["status"] != "good":
                current["status"] = "bad"
    return results


class Api:
    def __init__(self, session: SemaphoreSession):
        self.s = session

    def get(self, path):
        return self.s.get(path)

    def post(self, path, payload):
        return self.s.post(path, payload)

    def put(self, path, payload):
        return self.s.request("PUT", path, payload)


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
        "git_url": AUDIT_REPO,
        "git_branch": AUDIT_BRANCH,
        "ssh_key_id": 1,
    })
    repos = api.get(f"/api/project/{pid}/repositories") or []
    repo = find_by_name(repos, REPO_NAME)
    if not repo:
        raise RuntimeError(f"Could not create repository in project {pid}")
    return repo["id"]


def ensure_template(api: Api, pid: int, inv: dict, repo_id: int) -> int:
    templates = api.get(f"/api/project/{pid}/templates") or []
    name = f"{TEMPLATE_PREFIX} — {inv['name']}"
    existing = find_by_name(templates, name) or next(
        (t for t in templates
         if "audit_ssh_connections" in (t.get("playbook") or "")
         and t.get("inventory_id") == inv["id"]),
        None,
    )
    envs = api.get(f"/api/project/{pid}/environment") or []
    env_id = envs[0]["id"] if envs else 1
    payload = {
        "project_id": pid,
        "name": name,
        "playbook": AUDIT_PLAYBOOK,
        "inventory_id": inv["id"],
        "repository_id": repo_id,
        "environment_id": env_id,
        "app": "ansible",
        "type": "",
        "arguments": "[]",
        "description": "Test SSH from Semaphore controller to inventory hosts",
    }
    if existing:
        api.put(f"/api/project/{pid}/templates/{existing['id']}", {**payload, "id": existing["id"]})
        return existing["id"]
    created = api.post(f"/api/project/{pid}/templates", payload)
    return created["id"]


def run_task(api: Api, pid: int, template_id: int, poll: int) -> dict:
    task = api.post(f"/api/project/{pid}/tasks", {
        "template_id": template_id,
        "environment": json.dumps({"audit_mode": "test"}),
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


def test_project(api: Api, pid: int, pname: str, args) -> dict:
    print(f"\n{'=' * 70}\nPROJECT [{pid}] {pname}\n{'=' * 70}")
    keys = {k["id"]: k.get("name", "") for k in (api.get(f"/api/project/{pid}/keys") or [])}
    inventories = api.get(f"/api/project/{pid}/inventory") or []
    report = {
        "project_id": pid,
        "project_name": pname,
        "inventories": [],
    }
    repo_id = None

    for inv in inventories:
        full = api.get(f"/api/project/{pid}/inventory/{inv['id']}")
        hosts = parse_inventory_hosts(full.get("inventory") or "")
        ssh_key_id = full.get("ssh_key_id")
        entry = {
            "inventory_id": inv["id"],
            "inventory_name": inv.get("name", ""),
            "ssh_key_id": ssh_key_id,
            "ssh_key_name": keys.get(ssh_key_id, ""),
            "hosts": hosts,
            "tests": [],
            "task_id": None,
            "task_status": None,
            "status": "skipped",
            "error": None,
        }
        print(f"\n  [{inv['id']}] {inv.get('name')} key={entry['ssh_key_name']} hosts={len(hosts)}")

        if not hosts:
            entry["error"] = "no hosts"
            report["inventories"].append(entry)
            continue
        if not ssh_key_id:
            entry["error"] = "no ssh_key_id"
            report["inventories"].append(entry)
            continue

        for h in hosts:
            print(f"    {h.get('ansible_user', 'root')}@{h.get('ansible_host', h.get('name'))}")

        if args.dry_run:
            entry["status"] = "dry_run"
            report["inventories"].append(entry)
            continue

        try:
            templates = api.get(f"/api/project/{pid}/templates") or []
            tpl = find_by_name(templates, f"{TEMPLATE_PREFIX} — {inv.get('name')}") or next(
                (t for t in templates
                 if "audit_ssh_connections" in (t.get("playbook") or "")
                 and t.get("inventory_id") == inv["id"]),
                None,
            )
            if not tpl and args.ensure_template:
                if not repo_id:
                    repo_id = ensure_repo(api, pid)
                tpl_id = ensure_template(api, pid, {"id": inv["id"], "name": inv.get("name")}, repo_id)
            elif tpl:
                tpl_id = tpl["id"]
            else:
                entry["error"] = "no template; use --ensure-template"
                report["inventories"].append(entry)
                continue

            print(f"  running test task (template {tpl_id})...")
            result = run_task(api, pid, tpl_id, args.poll)
            entry["task_id"] = result["task_id"]
            entry["task_status"] = result["status"]
            entry["tests"] = parse_ssh_test_output(result["output"])

            # Ansible reachability: task success means Semaphore SSH to inventory worked
            entry["ansible_ssh"] = result["status"] == "success"
            good = [t for t in entry["tests"] if t["status"] == "good"]
            bad = [t for t in entry["tests"] if t["status"] in ("bad", "port_open")]
            unreach = [t for t in entry["tests"] if t["status"] == "unreachable"]

            if entry["ansible_ssh"]:
                entry["status"] = "ansible_ok"
            elif good:
                entry["status"] = "good"
            elif unreach:
                entry["status"] = "unreachable"
            else:
                entry["status"] = "failed"

            print(f"  task #{result['task_id']} {result['status']} — "
                  f"ansible_ssh={'OK' if entry['ansible_ssh'] else 'FAIL'} "
                  f"controller_good={len(good)} bad={len(bad)} unreachable={len(unreach)}")
            if entry["ansible_ssh"]:
                print(f"    ANSIBLE OK  Semaphore SSH to inventory hosts works")
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)
            print(f"  ERROR: {exc}")

        report["inventories"].append(entry)
    return report


def print_summary(reports: list[dict]):
    print(f"\n{'=' * 70}\nSSH TEST SUMMARY\n{'=' * 70}")
    ansible_ok, ansible_fail, skipped = [], [], []
    ctrl_good, ctrl_bad, ctrl_down = [], [], []

    for rep in reports:
        for inv in rep["inventories"]:
            row = {
                "project": rep["project_name"],
                "inventory": inv["inventory_name"],
                "hosts": inv.get("hosts", []),
            }
            if inv.get("error") or inv.get("status") == "skipped":
                skipped.append({**row, "reason": inv.get("error", "skipped")})
                continue
            if inv.get("ansible_ssh"):
                ansible_ok.append(row)
            elif inv.get("task_status"):
                ansible_fail.append({**row, "task_status": inv.get("task_status")})
            for t in inv.get("tests", []):
                tr = {**t, "project": rep["project_name"], "inventory": inv["inventory_name"]}
                if t["status"] == "good":
                    ctrl_good.append(tr)
                elif t["status"] == "unreachable":
                    ctrl_down.append(tr)
                else:
                    ctrl_bad.append(tr)

    print(f"\nANSIBLE SSH OK — Semaphore reached inventory ({len(ansible_ok)}):")
    for r in ansible_ok:
        hosts = ", ".join(
            f"{h.get('ansible_user','root')}@{h.get('ansible_host')}" for h in r["hosts"]
        )
        print(f"  [{r['project']}/{r['inventory']}] {hosts}")

    print(f"\nANSIBLE SSH FAILED ({len(ansible_fail)}):")
    for r in ansible_fail:
        hosts = ", ".join(
            f"{h.get('ansible_user','root')}@{h.get('ansible_host')}" for h in r["hosts"]
        )
        print(f"  [{r['project']}/{r['inventory']}] {hosts} — {r.get('task_status')}")

    print(f"\nSKIPPED ({len(skipped)}):")
    for r in skipped:
        print(f"  [{r['project']}/{r['inventory']}] {r.get('reason')}")

    print(f"\nController key tests — GOOD ({len(ctrl_good)}):")
    for r in ctrl_good:
        k = r["good"][0] if r["good"] else {}
        print(f"  {r['target']} [{r['project']}/{r['inventory']}] key={k.get('key', '?')}")

    if ctrl_bad:
        print(f"\nController key tests — BAD ({len(ctrl_bad)}):")
        for r in ctrl_bad:
            print(f"  {r['target']} [{r['project']}/{r['inventory']}]")

    if ctrl_down:
        print(f"\nController port 22 unreachable ({len(ctrl_down)}):")
        for r in ctrl_down:
            print(f"  {r['target']} [{r['project']}/{r['inventory']}]")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL", "https://devops.nextere.com"))
    p.add_argument("--token", default="")
    p.add_argument("--username", default=os.environ.get("SEMAPHORE_USERNAME"))
    p.add_argument("--password", default=os.environ.get("SEMAPHORE_PASSWORD"))
    p.add_argument("--project-id", type=int, action="append", dest="project_ids")
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--ensure-template", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--poll", type=int, default=8)
    p.add_argument("--out-dir", default="reports/ssh-tests")
    args = p.parse_args()

    session = from_env_or_login(
        args.url,
        args.token or None,
        args.username,
        args.password,
        url_explicit=True,
    )
    api = Api(session)
    me = session.user()
    print(f"Authenticated: {me.get('username')} @ {session.base_url}")

    projects = api.get("/api/projects") or []
    if args.project_ids:
        wanted = set(args.project_ids)
        projects = [pr for pr in projects if pr["id"] in wanted]
    elif not args.all_projects:
        print("Use --all-projects or --project-id", file=sys.stderr)
        return 2

    os.makedirs(args.out_dir, exist_ok=True)
    reports = []
    for pr in sorted(projects, key=lambda x: (x.get("name") or "").lower()):
        reports.append(test_project(api, pr["id"], pr.get("name", ""), args))
        out = os.path.join(args.out_dir, f"project-{pr['id']}.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(reports[-1], fh, indent=2)

    summary_path = os.path.join(args.out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(reports, fh, indent=2)
    print_summary(reports)
    print(f"\nReports: {args.out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
