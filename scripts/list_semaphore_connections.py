#!/usr/bin/env python3
"""List Semaphore projects, environments, inventories, keys, and SSH connectivity.

Reads every project the token/user can access, parses inventory YAML for hosts,
optionally tests SSH from this VM with local keys, and prints GOOD/BAD summary.

Auth (recommended: API token from browser):
  1. Log in to Semaphore in Chrome/Firefox
  2. Open DevTools → Network, filter ``api``
  3. Click any request (e.g. ``/api/projects``)
  4. Copy the ``Authorization: Bearer <token>`` value (token only, no ``Bearer``)
  5. Pass ``--token`` or set ``SEMAPHORE_TOKEN`` in ``.env``

  Alternative: User menu → API tokens → create/copy a token.

Examples:
  python3 scripts/list_semaphore_connections.py \\
      --url https://devops.nextere.com \\
      --token 'your-token-from-network-tab' \\
      --all-projects --test-local

  python3 scripts/verify_semaphore_token.py --url https://devops.nextere.com --token '…'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.semaphore_session import from_env_or_login  # noqa: E402

CONN_VARS = re.compile(
    r"ansible_host|ansible_user|ssh_user|public_ip|private_ip|"
    r"TARGET_HOST|TARGET_IP|SSH_HOST|host|ip",
    re.I,
)
HOST_LINE = re.compile(
    r"^\s{4,}(\S+):\s*$"
)
KV_LINE = re.compile(
    r"^\s{6,}(\w[\w_-]*):\s*(.+?)\s*$"
)


INI_HOST = re.compile(r"^\s*(\S+)\s+ansible_host=(\S+)")
INI_USER = re.compile(r"ansible_user=(\S+)")


def parse_inventory_hosts(yaml_text: str) -> list[dict]:
    """Best-effort parse of Semaphore static inventory YAML or INI."""
    if not yaml_text or not yaml_text.strip():
        return []

    hosts: list[dict] = []
    current: dict | None = None

    for line in yaml_text.splitlines():
        ini = INI_HOST.match(line)
        if ini:
            user_m = INI_USER.search(line)
            hosts.append({
                "name": ini.group(1),
                "ansible_host": ini.group(2),
                "ansible_user": user_m.group(1) if user_m else "root",
            })
            continue

        m_host = HOST_LINE.match(line)
        if m_host:
            name = m_host.group(1)
            if name in {"hosts", "children", "vars", "all"}:
                current = None
                continue
            current = {"name": name, "ansible_host": "", "ansible_user": ""}
            hosts.append(current)
            continue

        if current is None:
            continue

        m_kv = KV_LINE.match(line)
        if not m_kv:
            continue
        key, val = m_kv.group(1), m_kv.group(2).strip().strip("'\"")
        if key in ("ansible_host", "public_ip_addr", "public_ip", "host"):
            if val and not current.get("ansible_host"):
                current["ansible_host"] = val
        elif key in ("ansible_user", "ssh_user"):
            current["ansible_user"] = val
        elif key in ("private_ip_addr", "private_ip"):
            current["private_ip"] = val

    # Deduplicate by ansible_host
    seen = set()
    unique = []
    for h in hosts:
        addr = h.get("ansible_host") or h.get("name", "")
        if not addr or addr in seen:
            continue
        seen.add(addr)
        if not h.get("ansible_user"):
            h["ansible_user"] = "root"
        unique.append(h)
    return unique


def has_value(val) -> bool:
    if val is None:
        return False
    if isinstance(val, str):
        return val.strip() != ""
    return True


def parse_env_json(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def collect_local_keys(extra_dirs: list[str]) -> list[str]:
    keys = []
    seen = set()
    candidates = [
        os.path.expanduser("~/.ssh/id_ed25519"),
        os.path.expanduser("~/.ssh/id_rsa"),
        "/workspace/keys/media_id_ed25519",
        "/workspace/keys/mcm-controller/id_ed25519",
    ]
    for d in extra_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for name in files:
                if name.endswith(".pub") or name in {
                    "known_hosts", "authorized_keys", "config"
                }:
                    continue
                if re.match(r"^(id_|.*_(ed25519|rsa|ecdsa|dsa))$", name):
                    candidates.append(os.path.join(root, name))

    for path in candidates:
        if os.path.isfile(path) and path not in seen:
            seen.add(path)
            keys.append(path)
    return keys


def test_ssh_local(host: str, user: str, key: str, port: int = 22, timeout: int = 3):
    try:
        result = subprocess.run(
            [
                "ssh", "-p", str(port),
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "IdentitiesOnly=yes",
                "-i", key,
                f"{user}@{host}",
                "echo SSH_OK",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)


def tcp_reachable(host: str, port: int = 22, timeout: int = 2) -> bool:
    try:
        result = subprocess.run(
            ["timeout", str(timeout), "bash", "-c", f"echo >/dev/tcp/{host}/{port}"],
            capture_output=True,
            timeout=timeout + 1,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def audit_project(session, pid: int, pname: str, args) -> dict:
    report = {
        "project_id": pid,
        "project_name": pname,
        "environments": [],
        "inventories": [],
        "keys": [],
        "templates": [],
        "hosts": [],
        "local_tests": [],
    }

    envs = session.get(f"/api/project/{pid}/environment") or []
    for env in sorted(envs, key=lambda e: (e.get("name") or "").lower()):
        full = session.get(f"/api/project/{pid}/environment/{env['id']}")
        parsed = parse_env_json(full.get("json"))
        conn_keys = [k for k in sorted(parsed.keys()) if CONN_VARS.search(k)]
        report["environments"].append({
            "id": env["id"],
            "name": env.get("name", ""),
            "var_keys": sorted(parsed.keys()),
            "connection_vars": {k: parsed[k] for k in conn_keys if has_value(parsed[k])},
            "secret_names": [
                (s.get("name") or s.get("key") or "?")
                for s in (full.get("secrets") or [])
                if isinstance(s, dict)
            ],
        })

    inventories = session.get(f"/api/project/{pid}/inventory") or []
    for inv in sorted(inventories, key=lambda i: (i.get("name") or "").lower()):
        full = session.get(f"/api/project/{pid}/inventory/{inv['id']}")
        inv_yaml = full.get("inventory") or ""
        hosts = parse_inventory_hosts(inv_yaml)
        report["inventories"].append({
            "id": inv["id"],
            "name": inv.get("name", ""),
            "type": inv.get("type", ""),
            "ssh_key_id": inv.get("ssh_key_id"),
            "host_count": len(hosts),
            "hosts": hosts,
        })
        for h in hosts:
            h["inventory"] = inv.get("name", "")
            h["inventory_id"] = inv["id"]
            h["ssh_key_id"] = inv.get("ssh_key_id")
            h["project_id"] = pid
            h["project_name"] = pname
            report["hosts"].append(h)

    keys = session.get(f"/api/project/{pid}/keys") or []
    for key in sorted(keys, key=lambda k: (k.get("name") or "").lower()):
        ssh = key.get("ssh") or {}
        has_pk = has_value(ssh.get("private_key"))
        report["keys"].append({
            "id": key["id"],
            "name": key.get("name", ""),
            "type": key.get("type", ""),
            "login": ssh.get("login", ""),
            "has_private_key": has_pk,
        })

    templates = session.get(f"/api/project/{pid}/templates") or []
    env_names = {e["id"]: e.get("name", "") for e in envs}
    for tpl in sorted(templates, key=lambda t: (t.get("name") or "").lower()):
        eid = tpl.get("environment_id")
        report["templates"].append({
            "id": tpl["id"],
            "name": tpl.get("name", ""),
            "playbook": tpl.get("playbook", ""),
            "inventory_id": tpl.get("inventory_id"),
            "environment_id": eid,
            "environment_name": env_names.get(eid, ""),
        })

    if args.test_local and report["hosts"]:
        local_keys = collect_local_keys(args.key_dir)
        seen_targets = set()
        for h in report["hosts"]:
            addr = h.get("ansible_host", "")
            user = h.get("ansible_user", "root")
            sig = (addr, user)
            if not addr or sig in seen_targets:
                continue
            seen_targets.add(sig)

            port_open = tcp_reachable(addr, 22)
            entry = {
                "host": addr,
                "user": user,
                "project": pname,
                "inventory": h.get("inventory", ""),
                "port_22": "open" if port_open else "filtered",
                "working_keys": [],
                "failed_keys": [],
            }
            if not port_open:
                entry["status"] = "UNREACHABLE"
                report["local_tests"].append(entry)
                continue

            for keypath in local_keys:
                ok, msg = test_ssh_local(addr, user, keypath, timeout=args.ssh_timeout)
                fp = ""
                try:
                    fp = subprocess.check_output(
                        ["ssh-keygen", "-lf", keypath], text=True
                    ).split()[1]
                except (subprocess.CalledProcessError, IndexError):
                    fp = os.path.basename(keypath)
                if ok:
                    entry["working_keys"].append({"path": keypath, "fingerprint": fp})
                    break  # one working key is enough for this host
                else:
                    entry["failed_keys"].append({
                        "path": keypath,
                        "fingerprint": fp,
                        "error": msg[:120],
                    })
            entry["status"] = "GOOD" if entry["working_keys"] else "BAD"
            report["local_tests"].append(entry)

    return report


def print_report(reports: list[dict], out=sys.stdout):
    def p(*a, **kw):
        print(*a, **kw, file=out)

    p("=" * 90)
    p("SEMAPHORE CONNECTION AUDIT")
    p("=" * 90)

    all_hosts = []
    all_good = []
    all_bad = []
    all_unreachable = []

    for rep in reports:
        p(f"\n{'#' * 90}")
        p(f"PROJECT [{rep['project_id']}] {rep['project_name']}")
        p(f"{'#' * 90}")

        p(f"\n--- Environments ({len(rep['environments'])}) ---")
        for env in rep["environments"]:
            conn = env["connection_vars"]
            conn_s = ", ".join(f"{k}={v}" for k, v in conn.items()) if conn else "(none)"
            p(f"  [{env['id']}] {env['name']}")
            p(f"       vars: {', '.join(env['var_keys']) or '(none)'}")
            if conn:
                p(f"       connection: {conn_s}")
            if env["secret_names"]:
                p(f"       secrets: {', '.join(env['secret_names'])}")

        p(f"\n--- Key Store ({len(rep['keys'])}) ---")
        for key in rep["keys"]:
            pk = "has_key" if key["has_private_key"] else "no_key"
            p(f"  [{key['id']}] {key['name']} type={key['type']} {pk}"
              f"{(' login=' + key['login']) if key['login'] else ''}")

        p(f"\n--- Inventories ({len(rep['inventories'])}) ---")
        for inv in rep["inventories"]:
            p(f"  [{inv['id']}] {inv['name']} type={inv['type']} "
              f"ssh_key_id={inv['ssh_key_id']} hosts={inv['host_count']}")
            for h in inv["hosts"]:
                p(f"       {h['name']}: {h.get('ansible_user','root')}@"
                  f"{h.get('ansible_host','?')}")

        p(f"\n--- Templates ({len(rep['templates'])}) ---")
        for tpl in rep["templates"]:
            p(f"  [{tpl['id']}] {tpl['name']}")
            p(f"       playbook={tpl['playbook']} inv={tpl['inventory_id']} "
              f"env=[{tpl['environment_id']}] {tpl['environment_name']}")

        if rep["local_tests"]:
            p(f"\n--- Local VM SSH tests ({len(rep['local_tests'])}) ---")
            for t in rep["local_tests"]:
                all_hosts.append(t)
                if t["status"] == "GOOD":
                    all_good.append(t)
                elif t["status"] == "UNREACHABLE":
                    all_unreachable.append(t)
                else:
                    all_bad.append(t)
                status = t["status"]
                p(f"  {status:12} {t['user']}@{t['host']} "
                  f"(project={t['project']} inv={t['inventory']} port22={t['port_22']})")
                for wk in t.get("working_keys", []):
                    p(f"       GOOD key: {wk['path']} ({wk['fingerprint']})")
                if status == "BAD" and not t.get("working_keys"):
                    p(f"       no working local keys ({len(t.get('failed_keys', []))} tried)")

    p(f"\n{'=' * 90}")
    p("SUMMARY")
    p("=" * 90)
    p(f"Projects audited:     {len(reports)}")
    p(f"Total env groups:     {sum(len(r['environments']) for r in reports)}")
    p(f"Total inventories:    {sum(len(r['inventories']) for r in reports)}")
    p(f"Total hosts parsed:   {sum(len(r['hosts']) for r in reports)}")

    if all_hosts:
        p(f"\nLocal VM connectivity:")
        p(f"  GOOD (can SSH):     {len(all_good)}")
        p(f"  BAD (port open):    {len(all_bad)}")
        p(f"  UNREACHABLE:        {len(all_unreachable)}")

        if all_good:
            p("\n  Working connections from this VM:")
            for t in all_good:
                for wk in t["working_keys"]:
                    p(f"    ssh -i {wk['path']} {t['user']}@{t['host']}")

        if all_bad:
            p("\n  Hosts reachable but no local key works (use Semaphore controller key):")
            for t in all_bad:
                p(f"    {t['user']}@{t['host']} ({t['project']}/{t['inventory']})")

        if all_unreachable:
            p("\n  Unreachable from this VM (firewall/VPC):")
            for t in all_unreachable:
                p(f"    {t['user']}@{t['host']} ({t['project']}/{t['inventory']})")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL"))
    p.add_argument("--token", default=os.environ.get("SEMAPHORE_TOKEN"),
                   help="API token (from Network tab Authorization header or User → API tokens)")
    p.add_argument("--username", default=os.environ.get("SEMAPHORE_USERNAME"))
    p.add_argument("--password", default=os.environ.get("SEMAPHORE_PASSWORD"))
    p.add_argument("--project-id", type=int, action="append", dest="project_ids")
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--test-local", action="store_true",
                   help="Also test SSH from this VM (slow: ~2-3s per host; skip unless needed)")
    p.add_argument("--ssh-timeout", type=int, default=3,
                   help="SSH connect timeout seconds when using --test-local (default: 3)")
    p.add_argument("--key-dir", action="append", default=["/workspace/keys", os.path.expanduser("~/.ssh")])
    p.add_argument("--save-report", help="Write text report to this file")
    p.add_argument("--json-out", help="Write JSON report to this file")
    args = p.parse_args()

    session = from_env_or_login(
        args.url, args.token, args.username, args.password,
        url_explicit=bool(args.url),
    )
    me = session.user()
    print(f"Authenticated as {me.get('username')} ({me.get('name')}) @ {session.base_url}")

    if not session.ping():
        print("Warning: /api/ping did not return pong", file=sys.stderr)

    projects = session.get("/api/projects") or []
    if args.project_ids:
        wanted = set(args.project_ids)
        projects = [pr for pr in projects if pr["id"] in wanted]
    elif not args.all_projects:
        default_pid = os.environ.get("SEMAPHORE_PROJECT_ID")
        if default_pid:
            projects = [pr for pr in projects if pr["id"] == int(default_pid)]
        elif len(projects) == 1:
            pass
        else:
            print("Tip: pass --all-projects to audit every project", file=sys.stderr)

    reports = []
    for pr in sorted(projects, key=lambda x: (x.get("name") or "").lower()):
        reports.append(audit_project(session, pr["id"], pr.get("name", ""), args))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(reports, fh, indent=2)
        print(f"JSON report: {args.json_out}")

    if args.save_report:
        with open(args.save_report, "w", encoding="utf-8") as fh:
            print_report(reports, out=fh)
        print(f"Text report: {args.save_report}")
    else:
        print_report(reports)

    return 0


if __name__ == "__main__":
    sys.exit(main())
