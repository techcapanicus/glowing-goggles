#!/usr/bin/env python3
"""Provision SSH key access to target servers via the Semaphore REST API.

This single-file script drives a Semaphore (https://semaphoreui.com) instance
entirely through its REST API to:

  1. Generate (or accept) an SSH keypair and store the private key in the
     Semaphore Key Store (type: ``ssh``).
  2. Create or reuse a Semaphore project.
  3. Create a static inventory from a list of target hosts.
  4. Provide the ``provision_ssh.yml`` playbook through a Semaphore repository
     (an existing Git repo, or a local git repo created on the fly).
  5. Create an environment (extra vars) and a task template wired to the
     inventory + repository + key.
  6. Run the template as a task, poll until it finishes, and print the log.

The playbook itself is embedded below as a heredoc and written to a temporary
git repository when no external repository is supplied.

Only the Semaphore REST API is used -- no direct database access. Every request
sends ``Authorization: Bearer <token>`` and ``Content-Type: application/json``.

Usage example:

    ./provision_ssh.py \
        --url https://semaphore.example.com \
        --token "$SEMAPHORE_TOKEN" \
        --project-name ssh-provisioning \
        --target-hosts 10.0.0.5,10.0.0.6 \
        --bootstrap-user ubuntu \
        --bootstrap-ssh-key ~/.ssh/id_ed25519 \
        --target-user deploy

Run ``./provision_ssh.py --help`` for the full list of options.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

DEFAULT_PROJECT_NAME = "ssh-provisioning"
DEFAULT_PLAYBOOK = "provision_ssh.yml"
DEFAULT_BRANCH = "master"

# --------------------------------------------------------------------------- #
# Embedded playbook lives in ansible/provision_ssh.yml (copied for local repos).
# --------------------------------------------------------------------------- #
PLAYBOOK_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ansible")


class ApiError(Exception):
    """Raised when the Semaphore API returns a non-2xx response."""

    def __init__(self, method, path, status, body):
        self.status = status
        self.body = body
        super().__init__(f"{method} {path} -> HTTP {status}: {body}")


class Semaphore:
    """Tiny REST client for the Semaphore API."""

    def __init__(self, base_url, token, verbose=False):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verbose = verbose

    def _request(self, method, path, payload=None):
        url = f"{self.base_url}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            # Some deployments sit behind Cloudflare, which bans default
            # library user-agents (error 1010). Present a browser-like UA.
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if self.verbose:
            shown = "" if payload is None else f" body={json.dumps(payload)[:500]}"
            print(f"  -> {method} {path}{shown}", file=sys.stderr)

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise ApiError(method, path, exc.code, body) from None
        except urllib.error.URLError as exc:
            raise ApiError(method, path, 0, f"network error: {exc.reason}") from None

        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, payload):
        return self._request("POST", path, payload)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def info(msg):
    print(f"[*] {msg}")


def ok(msg):
    print(f"[+] {msg}")


def warn(msg):
    print(f"[!] {msg}", file=sys.stderr)


def die(msg, code=1):
    print(f"[x] {msg}", file=sys.stderr)
    sys.exit(code)


def save_keypair_locally(private_key, public_key, save_dir):
    """Write private/public key files under save_dir; return their paths."""
    save_dir = os.path.expanduser(save_dir)
    os.makedirs(save_dir, mode=0o700, exist_ok=True)
    priv_path = os.path.join(save_dir, "id_ed25519")
    pub_path = os.path.join(save_dir, "id_ed25519.pub")
    with open(priv_path, "w", encoding="utf-8") as handle:
        handle.write(private_key if private_key.endswith("\n")
                     else private_key + "\n")
    os.chmod(priv_path, 0o600)
    with open(pub_path, "w", encoding="utf-8") as handle:
        handle.write(public_key if public_key.endswith("\n")
                     else public_key + "\n")
    os.chmod(pub_path, 0o644)
    return priv_path, pub_path


def load_or_generate_keypair(workdir, save_dir=None):
    """Reuse a saved keypair when present, otherwise generate (and optionally save)."""
    if save_dir:
        save_dir = os.path.expanduser(save_dir)
        priv_path = os.path.join(save_dir, "id_ed25519")
        pub_path = os.path.join(save_dir, "id_ed25519.pub")
        if os.path.isfile(priv_path) and os.path.isfile(pub_path):
            with open(priv_path, encoding="utf-8") as handle:
                private_key = handle.read()
            with open(pub_path, encoding="utf-8") as handle:
                public_key = handle.read().strip()
            ok(f"Reusing saved keypair from {save_dir}")
            return private_key, public_key, save_dir

    info("Generating a new ed25519 keypair")
    private_key, public_key = generate_keypair(workdir)
    saved_to = None
    if save_dir:
        priv_path, pub_path = save_keypair_locally(private_key, public_key, save_dir)
        ok(f"Saved keypair to {priv_path} and {pub_path}")
        saved_to = save_dir
    return private_key, public_key, saved_to


def load_dotenv(path=".env"):
    """Populate os.environ from a simple KEY=VALUE .env file (no override)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def parse_hosts(raw):
    """Accept a comma-separated list or a path to a file of hosts."""
    if not raw:
        return []
    if os.path.isfile(raw):
        with open(raw, encoding="utf-8") as handle:
            tokens = handle.read().replace(",", "\n").split()
    else:
        tokens = [t.strip() for t in raw.split(",")]
    return [t for t in tokens if t and not t.startswith("#")]


def generate_keypair(workdir):
    """Generate an ed25519 keypair; return (private_key_text, public_key_text)."""
    key_path = os.path.join(workdir, "id_ed25519")
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", key_path,
         "-C", "semaphore-provisioned"],
        check=True,
    )
    with open(key_path, encoding="utf-8") as handle:
        private_key = handle.read()
    with open(key_path + ".pub", encoding="utf-8") as handle:
        public_key = handle.read().strip()
    return private_key, public_key


def public_key_from_private(private_key_text, workdir):
    """Derive the public key from a private key file/text using ssh-keygen."""
    key_path = os.path.join(workdir, "imported_key")
    with open(key_path, "w", encoding="utf-8") as handle:
        handle.write(private_key_text if private_key_text.endswith("\n")
                     else private_key_text + "\n")
    os.chmod(key_path, 0o600)
    result = subprocess.run(
        ["ssh-keygen", "-y", "-f", key_path],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def find_by_name(items, name):
    for item in items or []:
        if item.get("name") == name:
            return item
    return None


def build_local_repo(workdir):
    """Copy ansible/ and scripts/ into a fresh local git repo; return its path."""
    repo_dir = os.path.join(workdir, "playbook-repo")
    if not os.path.isdir(PLAYBOOK_SOURCE_DIR):
        die(f"Missing playbook source directory: {PLAYBOOK_SOURCE_DIR}")
    shutil.copytree(PLAYBOOK_SOURCE_DIR, os.path.join(repo_dir, "ansible"),
                    dirs_exist_ok=True)
    scripts_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
    if os.path.isdir(scripts_src):
        shutil.copytree(scripts_src, os.path.join(repo_dir, "scripts"),
                        dirs_exist_ok=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "provisioner",
           "GIT_AUTHOR_EMAIL": "provisioner@local",
           "GIT_COMMITTER_NAME": "provisioner",
           "GIT_COMMITTER_EMAIL": "provisioner@local"}
    run = lambda *a: subprocess.run(a, cwd=repo_dir, check=True,  # noqa: E731
                                    capture_output=True, env=env)
    run("git", "init", "-q", "-b", DEFAULT_BRANCH)
    run("git", "add", ".")
    run("git", "commit", "-q", "-m", "Add provision_ssh playbook")
    return repo_dir


# --------------------------------------------------------------------------- #
# Workflow steps
# --------------------------------------------------------------------------- #
def ensure_project(api, args):
    if args.project_id:
        info(f"Using provided project id {args.project_id}")
        return int(args.project_id)

    projects = api.get("/api/projects")
    existing = find_by_name(projects, args.project_name)
    if existing:
        ok(f"Reusing existing project '{args.project_name}' (id {existing['id']})")
        return existing["id"]

    info(f"Creating project '{args.project_name}'")
    try:
        created = api.post("/api/projects", {
            "name": args.project_name,
            "alert": False,
            "max_parallel_tasks": 0,
        })
    except ApiError as exc:
        if exc.status in (400, 403):
            die(f"Could not create project '{args.project_name}' (HTTP {exc.status}). "
                f"Your token may lack project-creation rights -- pass "
                f"--project-id of an existing project instead.\n    {exc.body}")
        raise
    ok(f"Created project '{args.project_name}' (id {created['id']})")
    return created["id"]


def ensure_key(api, project_id, name, key_type="ssh", login="", private_key="",
               password=""):
    """Create or reuse a Key Store entry; return its id."""
    keys = api.get(f"/api/project/{project_id}/keys")
    existing = find_by_name(keys, name)
    if existing:
        ok(f"Reusing key '{name}' (id {existing['id']})")
        return existing["id"]

    payload = {"name": name, "type": key_type, "project_id": project_id}
    if key_type == "ssh":
        payload["ssh"] = {"login": login, "passphrase": "", "private_key": private_key}
    elif key_type == "login_password":
        payload["login_password"] = {"login": login, "password": password}

    created = api.post(f"/api/project/{project_id}/keys", payload)
    # Some Semaphore versions return 204 (no body) on key creation.
    if created and isinstance(created, dict) and "id" in created:
        key_id = created["id"]
    else:
        refreshed = api.get(f"/api/project/{project_id}/keys")
        match = find_by_name(refreshed, name)
        if not match:
            die(f"Key '{name}' was not created")
        key_id = match["id"]
    ok(f"Created {key_type} key '{name}' (id {key_id})")
    return key_id


def ensure_inventory(api, project_id, name, content, ssh_key_id, become_key_id=None):
    inventories = api.get(f"/api/project/{project_id}/inventory")
    existing = find_by_name(inventories, name)
    payload = {
        "name": name,
        "project_id": project_id,
        "inventory": content,
        "ssh_key_id": ssh_key_id,
        "type": "static-yaml",
    }
    if become_key_id:
        payload["become_key_id"] = become_key_id

    if existing:
        payload["id"] = existing["id"]
        api._request("PUT", f"/api/project/{project_id}/inventory/{existing['id']}",
                     payload)
        ok(f"Updated inventory '{name}' (id {existing['id']})")
        return existing["id"]

    created = api.post(f"/api/project/{project_id}/inventory", payload)
    inv_id = created["id"] if isinstance(created, dict) else \
        find_by_name(api.get(f"/api/project/{project_id}/inventory"), name)["id"]
    ok(f"Created inventory '{name}' (id {inv_id})")
    return inv_id


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


def ensure_template(api, project_id, name, playbook, inventory_id, repository_id,
                    environment_id):
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
        "description": "Provision SSH key access to target servers",
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


def run_and_poll(api, project_id, template_id, extra_vars, dry_run, poll_interval):
    info("Starting task" + (" (dry-run / --check mode)" if dry_run else ""))
    task = api.post(f"/api/project/{project_id}/tasks", {
        "template_id": template_id,
        "dry_run": dry_run,
        "environment": json.dumps(extra_vars),
    })
    task_id = task["id"]
    ok(f"Task #{task_id} queued")

    terminal = {"success", "error", "failed", "stopped"}
    last_status = None
    while True:
        current = api.get(f"/api/project/{project_id}/tasks/{task_id}")
        status = current.get("status")
        if status != last_status:
            info(f"Task #{task_id} status: {status}")
            last_status = status
        if status in terminal:
            break
        time.sleep(poll_interval)

    print("\n----- task output -----")
    output = api.get(f"/api/project/{project_id}/tasks/{task_id}/output")
    for entry in output or []:
        print(entry.get("output", ""))
    print("----- end output -----\n")

    if last_status == "success":
        ok(f"Task #{task_id} finished successfully")
        parser = os.path.join(os.path.dirname(__file__), "scripts",
                              "parse_ssh_task_output.py")
        if os.path.isfile(parser):
            info("SSH diagnostic summary:")
            subprocess.run(
                [sys.executable, parser, "--project-id", str(project_id),
                 "--task-id", str(task_id)],
                check=False,
            )
        return 0
    warn(f"Task #{task_id} finished with status '{last_status}'")
    return 2


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(
        description="Provision SSH key access to servers via the Semaphore REST API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    env = os.environ.get
    p.add_argument("--url", default=env("SEMAPHORE_URL"),
                   help="Base URL of the Semaphore instance (env SEMAPHORE_URL)")
    p.add_argument("--token", default=env("SEMAPHORE_TOKEN"),
                   help="Bearer token for API auth (env SEMAPHORE_TOKEN)")
    p.add_argument("--project-id", default=env("SEMAPHORE_PROJECT_ID"),
                   help="Existing project id; skips project creation "
                        "(env SEMAPHORE_PROJECT_ID)")
    p.add_argument("--project-name", default=env("PROJECT_NAME", DEFAULT_PROJECT_NAME),
                   help="Project name to create/reuse (env PROJECT_NAME)")
    p.add_argument("--target-hosts", default=env("TARGET_HOSTS"),
                   help="Comma-separated hosts or path to a hosts file "
                        "(env TARGET_HOSTS)")
    p.add_argument("--bootstrap-user", default=env("BOOTSTRAP_USER"),
                   help="Existing sudo-capable user used to connect "
                        "(env BOOTSTRAP_USER)")
    p.add_argument("--bootstrap-ssh-key", default=env("BOOTSTRAP_SSH_KEY"),
                   help="Path to the bootstrap user's private key "
                        "(env BOOTSTRAP_SSH_KEY)")
    p.add_argument("--target-user", default=env("TARGET_USER"),
                   help="User whose authorized_keys receives the new key "
                        "(env TARGET_USER)")
    p.add_argument("--new-public-key", default=env("NEW_PUBLIC_KEY"),
                   help="Path to the public key to provision; a new ed25519 "
                        "keypair is generated if omitted (env NEW_PUBLIC_KEY)")
    p.add_argument("--ssh-key-id", default=env("SSH_KEY_ID"),
                   help="Reuse an existing Key Store key id for the inventory "
                        "connection instead of creating one (env SSH_KEY_ID)")
    p.add_argument("--become-password", default=env("BECOME_PASSWORD"),
                   help="Optional sudo/become password (env BECOME_PASSWORD)")
    p.add_argument("--repo-git-url", default=env("REPO_GIT_URL"),
                   help="Existing git repo URL containing the playbook. If omitted, "
                        "a local git repo is created (must be reachable by the "
                        "Semaphore server). (env REPO_GIT_URL)")
    p.add_argument("--repo-branch", default=env("REPO_BRANCH", DEFAULT_BRANCH),
                   help="Git branch for the repository (env REPO_BRANCH)")
    p.add_argument("--playbook", default=env("PLAYBOOK", DEFAULT_PLAYBOOK),
                   help="Playbook path within the repository (env PLAYBOOK)")
    p.add_argument("--prefix", default=env("RESOURCE_PREFIX", "ssh-provisioning"),
                   help="Name prefix for created Semaphore resources")
    p.add_argument("--save-key-dir", default=env("SAVE_KEY_DIR"),
                   help="Directory to save (or reuse) the generated ed25519 "
                        "keypair locally (env SAVE_KEY_DIR)")
    p.add_argument("--allowed-ip", default=env("ALLOWED_IP"),
                   help="Source IP to allow for SSH (used by allow_ssh_ip.yml; "
                        "env ALLOWED_IP)")
    p.add_argument("--doctl-token", default=env("DOCTL_TOKEN"),
                   help="DigitalOcean API token for Cloud Firewall SSH allow "
                        "(env DOCTL_TOKEN)")
    p.add_argument("--do-firewall-id", default=env("DO_FIREWALL_ID"),
                   help="DO Cloud Firewall UUID; auto-detected from droplet IP "
                        "if omitted (env DO_FIREWALL_ID)")
    p.add_argument("--dry-run", action="store_true",
                   help="Run the Ansible task in --check mode (no changes made)")
    p.add_argument("--no-run", action="store_true",
                   help="Set everything up but do not start a task")
    p.add_argument("--poll-interval", type=int, default=5,
                   help="Seconds between task status polls")
    p.add_argument("--verbose", action="store_true", help="Log every API request")
    return p


def build_inventory_yaml(hosts, bootstrap_user):
    lines = ["---", "all:", "  hosts:"]
    for host in hosts:
        lines.append(f"    {host}:")
        lines.append(f"      ansible_host: {host}")
        lines.append(f"      ansible_user: {bootstrap_user}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    load_dotenv()
    args = build_parser().parse_args(argv)

    if not args.url:
        die("Missing --url / SEMAPHORE_URL")
    if not args.token:
        die("Missing --token / SEMAPHORE_TOKEN")
    if not args.target_user:
        die("Missing --target-user / TARGET_USER")

    hosts = parse_hosts(args.target_hosts)
    if not hosts:
        die("No target hosts provided (--target-hosts / TARGET_HOSTS)")
    bootstrap_user = args.bootstrap_user or "root"

    api = Semaphore(args.url, args.token, verbose=args.verbose)

    info(f"Connecting to {args.url}")
    try:
        me = api.get("/api/user")
    except ApiError as exc:
        die(f"Authentication failed: {exc}")
    ok(f"Authenticated as {me.get('username')} ({me.get('name')})")

    workdir = tempfile.mkdtemp(prefix="semaphore-provision-")

    # Step 1: keypair + key store ------------------------------------------- #
    if args.new_public_key:
        pub_path = os.path.expanduser(args.new_public_key)
        with open(pub_path, encoding="utf-8") as handle:
            new_public_key = handle.read().strip()
        info("Using provided public key")
        new_private_key = None
        saved_key_dir = None
        priv_guess = pub_path[:-4] if pub_path.endswith(".pub") else pub_path
        if os.path.isfile(priv_guess):
            with open(priv_guess, encoding="utf-8") as handle:
                new_private_key = handle.read()
            info(f"Found matching private key at {priv_guess} for SSH self-test")
    else:
        new_private_key, new_public_key, saved_key_dir = load_or_generate_keypair(
            workdir, args.save_key_dir)

    project_id = ensure_project(api, args)

    # Bootstrap connection key (used by the inventory to reach the hosts).
    if args.ssh_key_id:
        connect_key_id = int(args.ssh_key_id)
        ok(f"Reusing existing Key Store key id {connect_key_id} for connection")
    elif args.bootstrap_ssh_key:
        with open(args.bootstrap_ssh_key, encoding="utf-8") as handle:
            bootstrap_private = handle.read()
        connect_key_id = ensure_key(
            api, project_id, f"{args.prefix}-bootstrap", key_type="ssh",
            login=bootstrap_user, private_key=bootstrap_private)
    elif not args.new_public_key:
        # No bootstrap key supplied: connect with the freshly generated key.
        connect_key_id = ensure_key(
            api, project_id, f"{args.prefix}-newkey", key_type="ssh",
            login=bootstrap_user, private_key=new_private_key)
    else:
        die("Provide --bootstrap-ssh-key so the inventory has a key to connect with.")

    # Step 1 (cont.): store the generated private key as its own keystore entry.
    if not args.new_public_key:
        ensure_key(api, project_id, f"{args.prefix}-newkey", key_type="ssh",
                   login=args.target_user, private_key=new_private_key)

    become_key_id = None
    if args.become_password:
        become_key_id = ensure_key(
            api, project_id, f"{args.prefix}-become", key_type="login_password",
            login=args.target_user, password=args.become_password)

    # Step 3: inventory ----------------------------------------------------- #
    inventory_yaml = build_inventory_yaml(hosts, bootstrap_user)
    inventory_id = ensure_inventory(
        api, project_id, f"{args.prefix}-inventory", inventory_yaml,
        connect_key_id, become_key_id)

    # Step 4: repository ---------------------------------------------------- #
    if args.repo_git_url:
        git_url = args.repo_git_url
    else:
        repo_path = build_local_repo(workdir)
        git_url = repo_path
        warn(f"No --repo-git-url given; created a local git repo at {git_url}. "
             f"The Semaphore server must be able to read this path.")
    repository_id = ensure_repository(
        api, project_id, f"{args.prefix}-repo", git_url, args.repo_branch,
        connect_key_id)

    # Step 5: environment (extra vars) + template --------------------------- #
    extra_vars = {
        "target_user": args.target_user,
        "bootstrap_user": bootstrap_user,
        "new_public_key": new_public_key,
    }
    if new_private_key:
        extra_vars["new_private_key"] = new_private_key
    if args.allowed_ip:
        extra_vars["allowed_ip"] = args.allowed_ip
    if args.doctl_token:
        extra_vars["doctl_token"] = args.doctl_token
    if args.do_firewall_id:
        extra_vars["do_firewall_id"] = args.do_firewall_id
    environment_id = ensure_environment(
        api, project_id, f"{args.prefix}-env", extra_vars)
    template_id = ensure_template(
        api, project_id, f"{args.prefix}-template", args.playbook,
        inventory_id, repository_id, environment_id)

    print()
    ok("Semaphore resources are ready:")
    print(f"    project_id     = {project_id}")
    print(f"    key_id         = {connect_key_id}")
    print(f"    inventory_id   = {inventory_id}")
    print(f"    repository_id  = {repository_id}")
    print(f"    environment_id = {environment_id}")
    print(f"    template_id    = {template_id}")
    print(f"    public key     = {new_public_key}")
    if saved_key_dir:
        print(f"    private key    = {os.path.join(os.path.expanduser(saved_key_dir), 'id_ed25519')}")
    print()

    # Step 6: run + poll ---------------------------------------------------- #
    if args.no_run:
        info("--no-run set; skipping task execution.")
        return 0
    return run_and_poll(api, project_id, template_id, extra_vars,
                        args.dry_run, args.poll_interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        die("Interrupted", code=130)
    except ApiError as exc:
        die(str(exc))
