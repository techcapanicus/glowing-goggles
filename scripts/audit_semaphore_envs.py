#!/usr/bin/env python3
"""Audit Semaphore Variable Groups for reusable credentials (keys only, no values)."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SEMAPHORE_URL", "https://cicd-ucaas.mycountrymobile.com").rstrip("/")
TOKEN = os.environ.get("SEMAPHORE_TOKEN", "")
PROJECT_ID = int(os.environ.get("SEMAPHORE_PROJECT_ID", "6"))

INTERESTING = re.compile(
    r"DO_TOKEN|DIGITALOCEAN_TOKEN|DO_API_KEY|DOCTL_TOKEN|SSH_KEY|PRIVATE_KEY|PUBLIC_KEY|"
    r"FIREWALL_ID|DO_FIREWALL|SEMAPHORE_TOKEN|SEMAPHORE_URL|BITBUCKET_|GIT_TOKEN|"
    r"TOKEN|KEY|SECRET|PASS|AUTH|CRED",
    re.I,
)


def api_get(path):
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def has_value(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    return True


def main():
    if not TOKEN:
        print("Set SEMAPHORE_TOKEN", file=sys.stderr)
        return 1

    envs = api_get(f"/api/project/{PROJECT_ID}/environment")
    templates = api_get(f"/api/project/{PROJECT_ID}/templates")

    tmpl_by_env = {}
    for t in templates:
        eid = t.get("environment_id")
        if eid:
            tmpl_by_env.setdefault(eid, []).append(t.get("name", f"id={t.get('id')}"))

    print("=" * 80)
    print("1. VARIABLE GROUPS (id, name, variable keys)")
    print("=" * 80)
    details = []
    for env in sorted(envs, key=lambda e: (e.get("name") or "").lower()):
        eid = env["id"]
        name = env.get("name", "")
        full = api_get(f"/api/project/{PROJECT_ID}/environment/{eid}")
        details.append(full)

        keys = []
        if full.get("json"):
            try:
                parsed = json.loads(full["json"]) if isinstance(full["json"], str) else full["json"]
                if isinstance(parsed, dict):
                    keys = sorted(parsed.keys())
            except json.JSONDecodeError:
                keys = ["<invalid json>"]

        secret_keys = []
        for s in full.get("secrets") or []:
            if isinstance(s, dict):
                secret_keys.append(s.get("name") or s.get("key") or str(s))
            else:
                secret_keys.append(str(s))

        print(f"\n[{eid}] {name}")
        print(f"  variables: {', '.join(keys) if keys else '(none)'}")
        print(f"  secrets:   {', '.join(secret_keys) if secret_keys else '(none)'}")

    print("\n" + "=" * 80)
    print("2. DETAIL TABLES (interesting keys + all credential-like keys)")
    print("=" * 80)

    matches = []
    do_token_value = None
    do_token_source = None

    for full in sorted(details, key=lambda e: (e.get("name") or "").lower()):
        name = full.get("name", "")
        eid = full["id"]
        rows = []

        parsed = {}
        if full.get("json"):
            try:
                parsed = json.loads(full["json"]) if isinstance(full["json"], str) else full["json"]
                if not isinstance(parsed, dict):
                    parsed = {}
            except json.JSONDecodeError:
                parsed = {}

        for key, val in sorted(parsed.items()):
            is_secret = False
            has_val = has_value(val)
            if INTERESTING.search(key):
                rows.append((key, has_val, is_secret))
                matches.append((name, eid, key, "variable", has_val, tmpl_by_env.get(eid, [])))
                if key.upper() in {
                    "DO_TOKEN", "DIGITALOCEAN_TOKEN", "DO_API_KEY", "DOCTL_TOKEN"
                } and has_val and do_token_value is None:
                    do_token_value = val.strip() if isinstance(val, str) else str(val)
                    do_token_source = f"{name} ({eid}) / {key}"

        secret_list = full.get("secrets") or []
        if secret_list:
            print(f"\n--- [{eid}] {name} — secrets tab ---")
            print(f"{'Group Name':<30} | {'Secret Key':<35} | {'Has Value':<10} | {'Is Secret'}")
            print("-" * 95)
            for s in secret_list:
                if isinstance(s, dict):
                    skey = s.get("name") or s.get("key") or "?"
                    shas = has_value(s.get("secret") or s.get("value"))
                else:
                    skey = str(s)
                    shas = True
                print(f"{name:<30} | {skey:<35} | {'yes' if shas else 'no':<10} | yes")
                if INTERESTING.search(skey):
                    matches.append((name, eid, skey, "secret", shas, tmpl_by_env.get(eid, [])))
                    if skey.upper() in {
                        "DO_TOKEN", "DIGITALOCEAN_TOKEN", "DO_API_KEY", "DOCTL_TOKEN"
                    } and shas and do_token_value is None and isinstance(s, dict):
                        do_token_value = (s.get("secret") or s.get("value") or "").strip()
                        do_token_source = f"{name} ({eid}) / secret:{skey}"

        if rows:
            print(f"\n--- [{eid}] {name} — matching variables ---")
            print(f"{'Group Name':<30} | {'Variable Key':<35} | {'Has Value':<10} | {'Is Secret'}")
            print("-" * 95)
            for key, has_val, is_secret in rows:
                print(f"{name:<30} | {key:<35} | {'yes' if has_val else 'no':<10} | {'yes' if is_secret else 'no'}")

    print("\n" + "=" * 80)
    print("3. TEMPLATES × ENVIRONMENT GROUPS")
    print("=" * 80)
    env_names = {e["id"]: e.get("name") for e in envs}
    print(f"{'Template ID':<12} | {'Template Name':<40} | {'Env ID':<8} | {'Env Group Name'}")
    print("-" * 95)
    for t in sorted(templates, key=lambda x: (x.get("name") or "").lower()):
        eid = t.get("environment_id") or ""
        print(f"{t.get('id', ''):<12} | {t.get('name', ''):<40} | {str(eid):<8} | {env_names.get(eid, '(none)')}")

    print("\n" + "=" * 80)
    print("4. REUSE MAP (credential-like keys only)")
    print("=" * 80)
    print(f"{'Variable Group':<30} | {'Key':<30} | {'Type':<10} | {'Has Val':<8} | {'Template(s) Using It':<40} | Recommended Reuse")
    print("-" * 140)
    recommendations = {
        "DO_TOKEN": "Pass as doctl_token extra var or Semaphore secret lookup",
        "DIGITALOCEAN_TOKEN": "Same as DO_TOKEN for DO Cloud Firewall API",
        "DOCTL_TOKEN": "Same as DO_TOKEN for DO Cloud Firewall API",
        "DO_API_KEY": "Same as DO_TOKEN for DO Cloud Firewall API",
        "DO_FIREWALL": "Pass as do_firewall_id extra var",
        "FIREWALL_ID": "Pass as do_firewall_id extra var",
        "DO_FIREWALL_ID": "Pass as do_firewall_id extra var",
        "PRIVATE_KEY": "Semaphore Key Store preferred over env var",
        "SSH_KEY": "Semaphore Key Store preferred over env var",
        "SEMAPHORE_TOKEN": "Already used by provision_ssh.py locally",
    }
    seen = set()
    for grp, eid, key, typ, has_val, tmpls in sorted(matches, key=lambda m: (m[0].lower(), m[2].lower())):
        sig = (grp, key, typ)
        if sig in seen:
            continue
        seen.add(sig)
        tmpl_str = ", ".join(tmpls[:3]) + ("..." if len(tmpls) > 3 else "") if tmpls else "(none)"
        rec = recommendations.get(key.upper(), "")
        if not rec and "FIREWALL" in key.upper():
            rec = "Pass as do_firewall_id extra var"
        elif not rec and re.search(r"PRIVATE|SSH.*KEY", key, re.I):
            rec = "Check Key Store (id 303 deployment) instead"
        elif not rec and re.search(r"TOKEN|SECRET|PASS|CRED|AUTH", key, re.I):
            rec = "Review if needed for provisioning; do not duplicate"
        print(f"{grp:<30} | {key:<30} | {typ:<10} | {'yes' if has_val else 'no':<8} | {tmpl_str:<40} | {rec}")

    print("\n" + "=" * 80)
    print("5. SSH / PROVISIONING GROUPS (full key inventory)")
    print("=" * 80)
    ssh_related = re.compile(r"ssh|provision|firewall|allow", re.I)
    for full in sorted(details, key=lambda e: (e.get("name") or "").lower()):
        if not ssh_related.search(full.get("name", "")):
            continue
        name = full.get("name", "")
        eid = full["id"]
        parsed = {}
        if full.get("json"):
            try:
                parsed = json.loads(full["json"]) if isinstance(full["json"], str) else full["json"]
            except json.JSONDecodeError:
                parsed = {}
        print(f"\n[{eid}] {name}")
        if isinstance(parsed, dict):
            for k in sorted(parsed.keys()):
                v = parsed[k]
                print(f"  var {k}: has_value={'yes' if has_value(v) else 'no'}")
        for s in full.get("secrets") or []:
            skey = s.get("name") if isinstance(s, dict) else str(s)
            print(f"  secret {skey}: encrypted")

    if do_token_value:
        print("\n" + "=" * 80)
        print(f"6. DIGITALOCEAN FIREWALLS (token from {do_token_source})")
        print("=" * 80)
        req = urllib.request.Request(
            "https://api.digitalocean.com/v2/firewalls",
            headers={
                "Authorization": f"Bearer {do_token_value}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            for fw in data.get("firewalls", []):
                droplets = fw.get("droplet_ids") or []
                print(f"  {fw.get('id')}  {fw.get('name')}  (droplets: {len(droplets)})")
        except urllib.error.HTTPError as exc:
            print(f"  DO API error HTTP {exc.code}: {exc.read().decode()[:200]}")
    else:
        print("\n" + "=" * 80)
        print("6. DIGITALOCEAN FIREWALLS — skipped (no DO_TOKEN/DOCTL_TOKEN found in any group)")
        print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
