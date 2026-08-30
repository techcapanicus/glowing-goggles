#!/usr/bin/env python3
"""Register DO firewall SSH access templates in Semaphore project 6.

Creates:
  - Variable group: do-firewall-access (DO_TOKEN, TARGET_IP, SSH_KEY_PATH)
  - Ansible template: Open SSH Firewall Access
  - Bash template: SSH Firewall Whitelist (Bash)

Usage:
  ./scripts/setup_do_firewall_templates.py
  ./scripts/setup_do_firewall_templates.py --inventory-id 15 --repository-id 6

After running, paste your DigitalOcean API token into the do-firewall-access
variable group as DO_TOKEN (json for Ansible, env for Bash — both are set).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_ssh import (  # noqa: E402
    Semaphore,
    die,
    find_by_name,
    load_dotenv,
    ok,
    info,
)

DEFAULT_PROJECT_ID = 6
DEFAULT_SSH_KEY_ID = 303
DEFAULT_REPO_URL = "https://github.com/techcapanicus/glowing-goggles.git"
DEFAULT_REPO_BRANCH = "cursor/dev-ssh-key-provision-1218"
DEFAULT_INVENTORY_ID = 15  # localhost-audit
ENV_NAME = "do-firewall-access"
ANSIBLE_PLAYBOOK = "ansible/open_ssh_firewall.yml"
BASH_SCRIPT = "scripts/open_ssh_access.sh"
ANSIBLE_TEMPLATE = "Open SSH Firewall Access"
BASH_TEMPLATE = "SSH Firewall Whitelist (Bash)"

LOCALHOST_INVENTORY = """all:
  hosts:
    localhost:
      ansible_connection: local
      ansible_python_interpreter: /usr/bin/python3
"""


def env(key, default=None):
    return os.environ.get(key, default)


def ensure_environment(api, project_id, name, json_vars, env_vars):
    envs = api.get(f"/api/project/{project_id}/environment")
    existing = find_by_name(envs, name)
    payload = {
        "name": name,
        "project_id": project_id,
        "json": json.dumps(json_vars),
        "env": json.dumps(env_vars),
    }
    if existing:
        # Preserve user-supplied secrets when re-running setup.
        old_json = json.loads(existing.get("json") or "{}")
        old_env = json.loads(existing.get("env") or "{}")
        merged_json = dict(json_vars)
        merged_env = dict(env_vars)
        for key in ("DO_TOKEN", "TARGET_IP", "SSH_KEY_PATH"):
            if old_json.get(key):
                merged_json[key] = old_json[key]
            if old_env.get(key):
                merged_env[key] = old_env[key]
        payload["json"] = json.dumps(merged_json)
        payload["env"] = json.dumps(merged_env)
        payload["id"] = existing["id"]
        api._request(
            "PUT",
            f"/api/project/{project_id}/environment/{existing['id']}",
            payload,
        )
        ok(f"Updated environment '{name}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/environment", payload)
    env_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/environment"), name)["id"]
    ok(f"Created environment '{name}' (id {env_id})")
    return env_id


def ensure_inventory(api, project_id, name, content, ssh_key_id, inventory_id=None):
    if inventory_id:
        inventories = api.get(f"/api/project/{project_id}/inventory")
        match = next((i for i in inventories if i["id"] == inventory_id), None)
        if match:
            ok(f"Using inventory id {inventory_id} ({match.get('name', '?')})")
            return inventory_id

    inventories = api.get(f"/api/project/{project_id}/inventory")
    existing = find_by_name(inventories, name)
    payload = {
        "name": name,
        "project_id": project_id,
        "inventory": content,
        "ssh_key_id": ssh_key_id,
        "type": "static-yaml",
    }
    if existing:
        payload["id"] = existing["id"]
        api._request(
            "PUT",
            f"/api/project/{project_id}/inventory/{existing['id']}",
            payload,
        )
        ok(f"Updated inventory '{name}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/inventory", payload)
    inv_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/inventory"), name)["id"]
    ok(f"Created inventory '{name}' (id {inv_id})")
    return inv_id


def ensure_repository(api, project_id, name, git_url, branch, ssh_key_id, repository_id=None):
    if repository_id:
        repos = api.get(f"/api/project/{project_id}/repositories")
        match = next((r for r in repos if r["id"] == repository_id), None)
        if match:
            payload = dict(match)
            payload.update({
                "git_url": git_url,
                "git_branch": branch,
                "ssh_key_id": ssh_key_id,
            })
            api._request(
                "PUT",
                f"/api/project/{project_id}/repositories/{repository_id}",
                payload,
            )
            ok(f"Using repository id {repository_id} (branch {branch})")
            return repository_id

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
        api._request(
            "PUT",
            f"/api/project/{project_id}/repositories/{existing['id']}",
            payload,
        )
        ok(f"Updated repository '{name}' (id {existing['id']}, branch {branch})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/repositories", payload)
    repo_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/repositories"), name)["id"]
    ok(f"Created repository '{name}' (id {repo_id})")
    return repo_id


def ensure_template(
    api,
    project_id,
    name,
    script_path,
    inventory_id,
    repository_id,
    environment_id,
    app,
    description,
):
    templates = api.get(f"/api/project/{project_id}/templates")
    existing = find_by_name(templates, name)
    payload = {
        "project_id": project_id,
        "name": name,
        "playbook": script_path,
        "inventory_id": inventory_id,
        "repository_id": repository_id,
        "environment_id": environment_id,
        "app": app,
        "type": "",
        "arguments": "[]",
        "description": description,
    }
    if existing:
        payload["id"] = existing["id"]
        api._request(
            "PUT",
            f"/api/project/{project_id}/templates/{existing['id']}",
            payload,
        )
        ok(f"Updated template '{name}' (id {existing['id']})")
        return existing["id"]
    created = api.post(f"/api/project/{project_id}/templates", payload)
    tpl_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/templates"), name)["id"]
    ok(f"Created template '{name}' (id {tpl_id})")
    return tpl_id


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser(description="Register DO firewall SSH Semaphore templates")
    p.add_argument("--url", default=env("SEMAPHORE_URL"))
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"))
    p.add_argument("--project-id", type=int, default=int(env("SEMAPHORE_PROJECT_ID", "6")))
    p.add_argument("--ssh-key-id", type=int, default=int(env("SSH_KEY_ID", str(DEFAULT_SSH_KEY_ID))))
    p.add_argument("--inventory-id", type=int, default=int(env("DO_FIREWALL_INVENTORY_ID", str(DEFAULT_INVENTORY_ID))))
    p.add_argument("--repository-id", type=int, default=int(env("DO_FIREWALL_REPOSITORY_ID", "6")))
    p.add_argument("--repo-git-url", default=env("REPO_GIT_URL", DEFAULT_REPO_URL))
    p.add_argument("--repo-branch", default=env("REPO_BRANCH", DEFAULT_REPO_BRANCH))
    args = p.parse_args(argv)

    if not args.url or not args.token:
        die("Set SEMAPHORE_URL and SEMAPHORE_TOKEN")

    api = Semaphore(args.url.rstrip("/"), args.token)
    pid = args.project_id

    info(f"Project {pid}: registering DO firewall SSH access templates")

    json_vars = {
        "DO_TOKEN": "",
        "TARGET_IP": "",
        "SSH_KEY_PATH": "/root/.ssh/id_ed25519",
    }
    env_vars = {
        "DO_TOKEN": "",
        "TARGET_IP": "",
        "SSH_KEY_PATH": "/root/.ssh/id_ed25519",
    }
    env_id = ensure_environment(api, pid, ENV_NAME, json_vars, env_vars)

    inventory_id = ensure_inventory(
        api, pid, "open-ssh-firewall-localhost", LOCALHOST_INVENTORY,
        args.ssh_key_id, inventory_id=args.inventory_id)

    repo_id = ensure_repository(
        api, pid, "do-firewall-access-repo", args.repo_git_url,
        args.repo_branch, args.ssh_key_id, repository_id=args.repository_id)

    ansible_tpl_id = ensure_template(
        api, pid, ANSIBLE_TEMPLATE, ANSIBLE_PLAYBOOK,
        inventory_id, repo_id, env_id, "ansible",
        "Whitelist caller IP on all DO Cloud Firewalls and verify SSH to 64.23.139.247")

    bash_tpl_id = ensure_template(
        api, pid, BASH_TEMPLATE, BASH_SCRIPT,
        inventory_id, repo_id, env_id, "bash",
        "Bash script to whitelist caller IP on DO firewalls and test SSH (run first)")

    print()
    ok("DO firewall SSH access resources:")
    print(f"    environment_id   = {env_id}  ({ENV_NAME})")
    print(f"    inventory_id     = {inventory_id}")
    print(f"    repository_id    = {repo_id}")
    print(f"    ansible_template = {ansible_tpl_id}  ({ANSIBLE_TEMPLATE})")
    print(f"    bash_template    = {bash_tpl_id}  ({BASH_TEMPLATE})")
    print()
    info("Next steps:")
    print("  1. Add DO_TOKEN to variable group 'do-firewall-access' in Semaphore UI")
    print("     (https://cloud.digitalocean.com/account/api/tokens — Read+Write)")
    print("  2. Run 'SSH Firewall Whitelist (Bash)' first for verbose output")
    print("  3. Use 'Open SSH Firewall Access' for production deployments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
