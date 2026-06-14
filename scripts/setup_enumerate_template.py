#!/usr/bin/env python3
"""Register Server Enumeration template in Semaphore project 6.

Also updates ssh-provisioning template to use provision_ssh_with_enum.yml
so enumeration runs automatically after a successful SSH self-test.

Usage:
  ./scripts/setup_enumerate_template.py
  ./scripts/setup_enumerate_template.py --inventory-id 21 --no-update-provision
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Reuse Semaphore helpers from provision_ssh.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import (  # noqa: E402
    Semaphore,
    die,
    env,
    find_by_name,
    load_dotenv,
    ok,
    info,
)

DEFAULT_PROJECT_ID = 6
DEFAULT_SSH_KEY_ID = 303
DEFAULT_REPO_URL = "https://github.com/techcapanicus/glowing-goggles.git"
DEFAULT_REPO_BRANCH = "cursor/dev-ssh-key-provision-1218"
ENUM_PLAYBOOK = "ansible/enumerate_server.yml"
PROVISION_WITH_ENUM = "ansible/provision_ssh_with_enum.yml"


def ensure_environment(api, project_id, name, extra_vars):
    envs = api.get(f"/api/project/{project_id}/environment")
    existing = find_by_name(envs, name)
    payload = {
        "name": name,
        "project_id": project_id,
        "json": json.dumps(extra_vars),
        "env": "{}",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{project_id}/environment/{existing['id']}",
                     payload)
        ok(f"Updated environment '{name}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/environment", payload)
    env_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/environment"), name)["id"]
    ok(f"Created environment '{name}' (id {env_id})")
    return env_id


def ensure_repository(api, project_id, name, git_url, branch, ssh_key_id):
    repos = api.get(f"/api/project/{project_id}/repositories")
    existing = find_by_name(repos, name)
    payload = {
        "name": name,
        "project_id": project_id,
        "git_url": git_url,
        "git_branch": branch,
        "ssh_key_id": ssh_key_id,
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{project_id}/repositories/{existing['id']}",
                     payload)
        ok(f"Updated repository '{name}' (id {existing['id']}, branch {branch})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/repositories", payload)
    repo_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/repositories"), name)["id"]
    ok(f"Created repository '{name}' (id {repo_id})")
    return repo_id


def ensure_template(api, project_id, name, playbook, inventory_id, repository_id,
                    environment_id, description):
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
        "description": description,
    }
    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{project_id}/templates/{existing['id']}",
                     payload)
        ok(f"Updated template '{name}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/templates", payload)
    tpl_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/templates"), name)["id"]
    ok(f"Created template '{name}' (id {tpl_id})")
    return tpl_id


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser(description="Register Server Enumeration Semaphore template")
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=int(env("SEMAPHORE_PROJECT_ID", "6")))
    p.add_argument("--ssh-key-id", type=int, default=int(env("SSH_KEY_ID", str(DEFAULT_SSH_KEY_ID))))
    p.add_argument("--inventory-id", type=int,
                   default=int(env("ENUM_INVENTORY_ID", env("SEMAPHORE_INVENTORY_ID", "21"))),
                   help="Inventory for the enumeration template (default: ssh-provisioning)")
    p.add_argument("--repo-git-url", default=env("REPO_GIT_URL", DEFAULT_REPO_URL))
    p.add_argument("--repo-branch", default=env("REPO_BRANCH", DEFAULT_REPO_BRANCH))
    p.add_argument("--no-update-provision", action="store_true",
                   help="Do not point ssh-provisioning-template at provision_ssh_with_enum.yml")
    args = p.parse_args(argv)

    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    pid = args.project_id

    info(f"Project {pid}: registering Server Enumeration template")
    repo_id = ensure_repository(
        api, pid, "server-enumeration-repo", args.repo_git_url,
        args.repo_branch, args.ssh_key_id)
    env_id = ensure_environment(api, pid, "server-enumeration-env", {})
    tpl_id = ensure_template(
        api, pid, "Server Enumeration", ENUM_PLAYBOOK,
        args.inventory_id, repo_id, env_id,
        "Enumerate credentials, network, Docker, and auth config on target hosts")

    if not args.no_update_provision:
        templates = api.get(f"/api/project/{pid}/templates")
        prov = find_by_name(templates, "ssh-provisioning-template")
        if prov:
            payload = dict(prov)
            payload["playbook"] = PROVISION_WITH_ENUM
            api._request("PUT", f"/api/project/{pid}/templates/{prov['id']}", payload)
            ok(f"Updated ssh-provisioning-template (id {prov['id']}) "
               f"playbook -> {PROVISION_WITH_ENUM}")
        else:
            info("ssh-provisioning-template not found; skipped provision hook update")

    print()
    ok("Server Enumeration resources:")
    print(f"    repository_id  = {repo_id}")
    print(f"    environment_id = {env_id}")
    print(f"    template_id    = {tpl_id}")
    print(f"    inventory_id   = {args.inventory_id}")
    print(f"    playbook       = {ENUM_PLAYBOOK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
