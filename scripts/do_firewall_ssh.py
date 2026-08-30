#!/usr/bin/env python3
"""Add inbound SSH (tcp/22) allow rule to a DigitalOcean Cloud Firewall.

Used by ansible/provision_ssh.yml and scripts/open_ssh_access.sh.

Environment:
  DOCTL_TOKEN or DIGITALOCEAN_TOKEN — DigitalOcean API token (required)

Examples:
  ./scripts/do_firewall_ssh.py
  ./scripts/do_firewall_ssh.py --ip 203.0.113.10 --firewall-id abc-123
  ./scripts/do_firewall_ssh.py --droplet-ip 64.23.139.247
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DO_API = "https://api.digitalocean.com/v2"
IP_SERVICES = (
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
)


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def api_request(token, method, path, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{DO_API}{path}", data=data, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            if not raw:
                return None, resp.status
            return json.loads(raw), resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        die(f"DigitalOcean API {method} {path} -> HTTP {exc.code}: {body}")


def get_public_ip():
    for url in IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "do-firewall-ssh/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                ip = resp.read().decode().strip()
                if ip and "." in ip:
                    return ip
        except urllib.error.URLError:
            continue
    die("could not detect public IP from ipify or checkip.amazonaws.com")


def list_firewalls(token):
    body, _ = api_request(token, "GET", "/firewalls")
    return body.get("firewalls", []) if body else []


def list_droplets(token):
    droplets = []
    page = 1
    while True:
        body, _ = api_request(token, "GET", f"/droplets?page={page}&per_page=200")
        droplets.extend(body.get("droplets", []))
        links = body.get("links", {}) or {}
        if not links.get("pages", {}).get("next"):
            break
        page += 1
    return droplets


def droplet_id_for_ip(token, ip):
    for droplet in list_droplets(token):
        for net in droplet.get("networks", {}).get("v4", []):
            if net.get("ip_address") == ip:
                return droplet["id"], droplet.get("name", "")
    return None, None


def firewall_for_droplet(token, droplet_id, firewall_id=None):
    if firewall_id:
        body, _ = api_request(token, "GET", f"/firewalls/{firewall_id}")
        return body.get("firewall") if body else None
    for fw in list_firewalls(token):
        if droplet_id in (fw.get("droplet_ids") or []):
            return fw
    return None


def rule_allows_ip(firewall, cidr):
    for rule in firewall.get("inbound_rules") or []:
        if rule.get("protocol") != "tcp":
            continue
        ports = str(rule.get("ports", ""))
        if ports not in ("22", "22-22") and "22" not in ports.split(","):
            continue
        for addr in (rule.get("sources") or {}).get("addresses") or []:
            if addr == cidr or addr.rstrip("/32") == cidr.rstrip("/32"):
                return True
            if addr.endswith("/8") and cidr.startswith(addr.split("/")[0].rsplit(".", 1)[0]):
                return True
    return False


def add_ssh_rule(token, firewall_id, cidr):
    payload = {
        "inbound_rules": [
            {
                "protocol": "tcp",
                "ports": "22",
                "sources": {"addresses": [cidr]},
            }
        ]
    }
    api_request(token, "POST", f"/firewalls/{firewall_id}/rules", payload)
    return True


def resolve_token(explicit=None):
    token = explicit or os.environ.get("DOCTL_TOKEN") or os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        die("set DOCTL_TOKEN or DIGITALOCEAN_TOKEN (or pass --token)")
    return token


def main(argv=None):
    p = argparse.ArgumentParser(description="Allow SSH from an IP on a DO Cloud Firewall")
    p.add_argument("--ip", help="Public IP to allow (/32 added if missing)")
    p.add_argument("--firewall-id", help="DO Cloud Firewall UUID (auto-detect if omitted)")
    p.add_argument("--droplet-ip", help="Droplet public IP for firewall auto-detection")
    p.add_argument("--token", help="DO API token (else DOCTL_TOKEN env)")
    p.add_argument("--dry-run", action="store_true", help="Show actions without API writes")
    args = p.parse_args(argv)

    token = resolve_token(args.token)
    ip = args.ip or get_public_ip()
    cidr = ip if "/" in ip else f"{ip}/32"

    firewall = None
    droplet_id = None
    droplet_name = None
    if args.firewall_id and not args.droplet_ip:
        firewall = firewall_for_droplet(token, droplet_id=0, firewall_id=args.firewall_id)
    elif args.droplet_ip:
        droplet_id, droplet_name = droplet_id_for_ip(token, args.droplet_ip)
        if not droplet_id:
            die(f"no droplet found with public IP {args.droplet_ip}")
        firewall = firewall_for_droplet(token, droplet_id,
                                      firewall_id=args.firewall_id)
    elif args.firewall_id:
        firewall = firewall_for_droplet(token, droplet_id=0, firewall_id=args.firewall_id)
    else:
        die("pass --firewall-id and/or --droplet-ip to locate the Cloud Firewall")

    if not firewall:
        die("could not find a Cloud Firewall for the target droplet")

    fw_id = firewall["id"]
    fw_name = firewall.get("name", fw_id)

    if rule_allows_ip(firewall, cidr):
        print(f"OK: {fw_name} ({fw_id}) already allows SSH from {cidr}")
        return 0

    if args.dry_run:
        print(f"DRY-RUN: would POST inbound tcp/22 allow {cidr} to firewall {fw_name} ({fw_id})")
        return 0

    add_ssh_rule(token, fw_id, cidr)
    print(f"OK: added inbound SSH (tcp/22) allow {cidr} to firewall {fw_name} ({fw_id})")
    if droplet_name:
        print(f"    droplet: {droplet_name} (id {droplet_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
