#!/usr/bin/env python3
"""Full Semaphore environment (variable group) audit across projects.

Equivalent to opening Edit on every environment in the UI: lists JSON variables,
encrypted secret slots, SSH key store entries, and credential-like keys.

Values are masked by default. Use --include-values only when you need a local
JSON dump (never commit that file).

Examples:
  SEMAPHORE_URL=https://devops.nextere.com \\
  SEMAPHORE_USERNAME=user SEMAPHORE_PASSWORD=pass \\
  python3 scripts/audit_semaphore_envs_full.py --all-projects

  python3 scripts/audit_semaphore_envs_full.py --url https://devops.nextere.com \\
      --token TOKEN --project-id 1 --out reports/voice-envs.json

  python3 scripts/audit_semaphore_envs_full.py --all-projects --filter do_token,azure,firewall
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.semaphore_session import from_env_or_login  # noqa: E402

DEFAULT_INTEREST = re.compile(
    r"do_token|doctl|digitalocean|dop_v1|azure|arm_|subscription|tenant|client_secret|"
    r"firewall|nsg|ssh|private_key|public_key|api_key|api_token|bearer|jwt|secret|"
    r"password|passwd|token|auth|credential|bitbucket|git_|repo_|mysql|rds|mongo|"
    r"dsn|wasabi|stripe|vault|semaphore|telnyx|sendgrid|zoho",
    re.I,
)
SENSITIVE = re.compile(
    r"password|secret|token|key|private|credential|jwt|dsn|auth|wasabi|stripe|api_key",
    re.I,
)
INFRA_KEYS = re.compile(
    r"do_token|doctl|dop_v1|digitalocean|azure_client|arm_|subscription|tenant|"
    r"firewall|nsg|ssh_key|private_key",
    re.I,
)


def has_value(val) -> bool:
    if val is None:
        return False
    if isinstance(val, str):
        return val.strip() != ""
    return True


def mask_value(key: str, val, include_values: bool) -> str:
    if include_values:
        return str(val) if val is not None else ""
    if not has_value(val):
        return "(empty)"
    sv = str(val)
    if not SENSITIVE.search(key) and not SENSITIVE.search(sv[:24]):
        return sv[:200] + ("…" if len(sv) > 200 else "")
    if len(sv) <= 8:
        return "***"
    return f"{sv[:4]}…{sv[-4:]} (len={len(sv)})"


def parse_env_rows(full: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    raw_json = full.get("json") or ""
    if raw_json:
        try:
            parsed = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            if isinstance(parsed, dict):
                for key, val in parsed.items():
                    rows.append(("json", key, val))
        except json.JSONDecodeError:
            rows.append(("json", "<parse error>", raw_json[:120]))
    for sec in full.get("secrets") or []:
        if isinstance(sec, dict):
            rows.append(("secret", sec.get("name") or sec.get("key") or "?", sec.get("value")))
        else:
            rows.append(("secret", str(sec), ""))
    raw_env = full.get("env") or ""
    if raw_env and str(raw_env).strip():
        for line in str(raw_env).strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                rows.append(("env", k.strip(), v.strip()))
    return rows


def row_matches(key: str, val, pattern: re.Pattern) -> bool:
    if pattern.search(key):
        return True
    if isinstance(val, str) and pattern.search(val[:120]):
        return True
    return False


def audit_project(session, pid: int, pname: str, args) -> dict:
    filter_re = (
        re.compile("|".join(re.escape(p) for p in args.filter), re.I)
        if args.filter
        else DEFAULT_INTEREST
    )
    envs = session.get(f"/api/project/{pid}/environment") or []
    templates = session.get(f"/api/project/{pid}/templates") or []
    keys_store = session.get(f"/api/project/{pid}/keys") or []

    tmpl_by_env: dict[int, list[str]] = defaultdict(list)
    for tpl in templates:
        eid = tpl.get("environment_id")
        if eid:
            tmpl_by_env[eid].append(tpl.get("name") or f"id={tpl.get('id')}")

    proj = {
        "project_id": pid,
        "project_name": pname,
        "ssh_keys": [
            {
                "id": k.get("id"),
                "name": k.get("name"),
                "type": k.get("type"),
            }
            for k in keys_store
        ],
        "environments": [],
    }

    for env in sorted(envs, key=lambda e: (e.get("name") or "").lower()):
        eid = env["id"]
        full = session.get(f"/api/project/{pid}/environment/{eid}")
        rows = parse_env_rows(full)
        interesting = [
            (src, k, v) for src, k, v in rows if row_matches(k, v, filter_re)
        ]

        entry = {
            "id": eid,
            "name": full.get("name"),
            "template_names": tmpl_by_env.get(eid, []),
            "total_vars": len(rows),
            "all_keys": [k for _, k, _ in rows],
            "variables": [],
            "interesting": [],
        }

        for src, k, v in rows:
            item = {
                "source": src,
                "key": k,
                "has_value": has_value(v),
                "value": mask_value(k, v, args.include_values),
            }
            if args.include_values and has_value(v):
                item["raw"] = v
            entry["variables"].append(item)
            if (src, k, v) in interesting:
                entry["interesting"].append(item)

        proj["environments"].append(entry)

    return proj


def print_summary(reports: list[dict], filter_re: re.Pattern):
    print(f"\nProjects: {len(reports)}")
    total_envs = sum(len(p["environments"]) for p in reports)
    print(f"Environments: {total_envs}\n")

    infra_hits: list[str] = []
    key_index: dict[str, list[str]] = defaultdict(list)

    for pr in reports:
        pid = pr["project_id"]
        pname = pr["project_name"]
        print("=" * 72)
        print(f"PROJECT [{pid}] {pname}")
        if pr["ssh_keys"]:
            ssh = [k for k in pr["ssh_keys"] if k.get("type") == "ssh"]
            if ssh:
                print("  SSH Key Store:", ", ".join(f"[{k['id']}]{k['name']}" for k in ssh))

        for env in pr["environments"]:
            if not env["all_keys"] and env.get("name") not in (None, "", "none"):
                continue
            interesting = env.get("interesting") or []
            if not interesting and not env["all_keys"]:
                if env.get("name") in (None, "", "none"):
                    continue
            print(f"\n  ENV [{env['id']}] {env['name']!r} ({env['total_vars']} vars)")
            if env.get("template_names"):
                print(f"    templates: {', '.join(env['template_names'][:4])}"
                      f"{'…' if len(env['template_names']) > 4 else ''}")
            if interesting:
                for item in interesting:
                    print(f"    {item['source']:6} {item['key']}: {item['value']}")
                    if has_value(item.get("raw")) or item.get("has_value"):
                        key_index[item["key"]].append(f"P{pid}/{env['name']}")
                    if INFRA_KEYS.search(item["key"]):
                        infra_hits.append(f"P{pid}/{env['name']}/{item['key']}")
            elif env["all_keys"]:
                preview = ", ".join(env["all_keys"][:12])
                if len(env["all_keys"]) > 12:
                    preview += "…"
                print(f"    keys: {preview}")

    print("\n" + "=" * 72)
    print("INFRA / FIREWALL / CLOUD API KEYS")
    if infra_hits:
        for hit in sorted(set(infra_hits)):
            print(f"  {hit}")
    else:
        print("  (none found in any environment)")

    print("\nCROSS-PROJECT KEYS WITH VALUES (sample)")
    for k in sorted(key_index.keys(), key=str.lower)[:40]:
        locs = key_index[k]
        print(f"  {k}: {', '.join(locs[:4])}{'…' if len(locs) > 4 else ''}")
    if len(key_index) > 40:
        print(f"  … and {len(key_index) - 40} more")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("SEMAPHORE_URL", "https://devops.nextere.com"))
    p.add_argument("--token", default="")
    p.add_argument("--username", default=os.environ.get("SEMAPHORE_USERNAME"))
    p.add_argument("--password", default=os.environ.get("SEMAPHORE_PASSWORD"))
    p.add_argument("--project-id", type=int, action="append", dest="project_ids")
    p.add_argument("--all-projects", action="store_true")
    p.add_argument("--filter", help="Comma-separated substrings (default: built-in credential list)")
    p.add_argument("--out", default="reports/semaphore-env-audit.json")
    p.add_argument("--include-values", action="store_true",
                   help="Store raw values in JSON (sensitive — do not commit)")
    p.add_argument("--quiet", action="store_true", help="JSON only, no console summary")
    args = p.parse_args()

    if not args.all_projects and not args.project_ids:
        print("Use --all-projects or --project-id", file=sys.stderr)
        return 2

    session = from_env_or_login(
        args.url,
        args.token or None,
        args.username,
        args.password,
        url_explicit=bool(args.url),
    )
    me = session.user()
    if not args.quiet:
        print(f"Authenticated: {me.get('username')} @ {session.base_url}")

    projects = session.get("/api/projects") or []
    if args.project_ids:
        wanted = set(args.project_ids)
        projects = [pr for pr in projects if pr["id"] in wanted]

    reports = []
    for pr in sorted(projects, key=lambda x: (x.get("name") or "").lower()):
        reports.append(audit_project(session, pr["id"], pr.get("name", ""), args))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(reports, fh, indent=2)

    if not args.quiet:
        filter_re = (
            re.compile("|".join(re.escape(x) for x in args.filter), re.I)
            if args.filter
            else DEFAULT_INTEREST
        )
        print_summary(reports, filter_re)
        print(f"\nJSON report: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
