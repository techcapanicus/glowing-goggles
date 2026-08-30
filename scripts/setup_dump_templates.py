#!/usr/bin/env python3
"""Fix ENV-DUMP/SHELL-DUMP templates and run SIP audit pipeline on Nextere Semaphore."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import find_by_name  # noqa: E402
from scripts.semaphore_session import from_env_or_login  # noqa: E402

REPO_BRANCH = os.environ.get("AUDIT_REPO_BRANCH", "cursor/dev-ssh-key-provision-1218")
GLOWING_REPO = "glowing-goggles-audit"

# Broken templates to fix: project_id -> [(template_id, name, playbook, inventory_id, env_id)]
TEMPLATE_FIXES = {
    11: [
        (44, "ENV-DUMP-ALL", "ansible/env_dump.yml", 4, None),
        (37, "SHELL-DUMP", "ansible/shell_dump.yml", 1, 2),
        (35, "ENV-DUMP-BACKUP", "ansible/env_dump.yml", 4, None),
    ],
    1: [
        (16, "BACKUP-KEY-DUMP", "ansible/env_dump.yml", 4, 1),
    ],
    7: [
        (62, "BACKUP-KEY-DUMP", "ansible/env_dump.yml", 8, 2),
    ],
}

NEW_TEMPLATES = [
    (1, "SIP Intel — dev", "ansible/sip_intel.yml", 2, 1),
    (1, "SIP Intel — live", "ansible/sip_intel.yml", 4, 1),
    (7, "SIP Intel — dev", "ansible/sip_intel.yml", 1, 2),
    (7, "SIP Intel — live", "ansible/sip_intel.yml", 2, 2),
    (11, "SIP Intel — dev", "ansible/sip_intel.yml", 1, 2),
]


class Api:
    def __init__(self, session):
        self.s = session

    def get(self, path):
        return self.s.get(path)

    def post(self, path, payload):
        return self.s.post(path, payload)

    def put(self, path, payload):
        return self.s.request("PUT", path, payload)


def repo_id_for(api: Api, pid: int) -> int:
    repos = api.get(f"/api/project/{pid}/repositories") or []
    repo = find_by_name(repos, GLOWING_REPO) or next(
        (r for r in repos if "glowing-goggles" in (r.get("git_url") or "")), None
    )
    if not repo:
        raise RuntimeError(f"No glowing-goggles repo in project {pid}")
    return repo["id"]


def fix_templates(api: Api) -> None:
    for pid, fixes in TEMPLATE_FIXES.items():
        rid = repo_id_for(api, pid)
        for tpl_id, name, playbook, inv_id, env_id in fixes:
            existing = api.get(f"/api/project/{pid}/templates/{tpl_id}")
            payload = dict(existing)
            payload.update({
                "repository_id": rid,
                "playbook": playbook,
                "inventory_id": inv_id,
                "app": "ansible",
                "type": "build" if "DUMP" in name else "",
            })
            if env_id is not None:
                payload["environment_id"] = env_id
            api.put(f"/api/project/{pid}/templates/{tpl_id}", payload)
            print(f"Fixed template {pid}/{tpl_id} {name} -> {playbook} repo={rid}")


def ensure_new_templates(api: Api) -> dict:
    created = {}
    for pid, name, playbook, inv_id, env_id in NEW_TEMPLATES:
        rid = repo_id_for(api, pid)
        templates = api.get(f"/api/project/{pid}/templates") or []
        existing = find_by_name(templates, name)
        payload = {
            "project_id": pid,
            "name": name,
            "playbook": playbook,
            "inventory_id": inv_id,
            "repository_id": rid,
            "environment_id": env_id,
            "app": "ansible",
            "type": "",
            "arguments": "[]",
            "description": name,
        }
        if existing:
            payload["id"] = existing["id"]
            api.put(f"/api/project/{pid}/templates/{existing['id']}", payload)
            tid = existing["id"]
        else:
            result = api.post(f"/api/project/{pid}/templates", payload)
            tid = result["id"] if isinstance(result, dict) else \
                find_by_name(api.get(f"/api/project/{pid}/templates"), name)["id"]
        created[(pid, name)] = tid
        print(f"Ensured template {pid}/{tid} {name}")
    return created


def run_task(api: Api, pid: int, tpl_id: int, limit: str = "",
             extra: dict | None = None, poll: int = 5) -> dict:
    body = {"template_id": tpl_id}
    if limit:
        body["limit"] = limit
    if extra:
        body["environment"] = json.dumps(extra)
    task = api.post(f"/api/project/{pid}/tasks", body)
    tid = task["id"]
    terminal = {"success", "error", "failed", "stopped"}
    while True:
        time.sleep(poll)
        cur = api.get(f"/api/project/{pid}/tasks/{tid}")
        st = cur.get("status")
        print(f"  task {tid}: {st}")
        if st in terminal:
            break
    output = api.get(f"/api/project/{pid}/tasks/{tid}/output") or []
    text = "\n".join(e.get("output", "") for e in output)
    return {"task_id": tid, "status": cur.get("status"), "output": text}


def main():
    session = from_env_or_login()
    api = Api(session)
    fix_templates(api)
    templates = ensure_new_templates(api)
    print("\n=== Templates fixed. Push branch before running tasks. ===")
    print(json.dumps({f"p{k[0]}-{k[1]}": v for k, v in templates.items()}, indent=2))


if __name__ == "__main__":
    main()
