#!/usr/bin/env python3
"""Probe outbound network access from every host we can SSH into.

Runs curl/tcp checks locally and via SSH on known reachable servers, then
reports which targets are reachable from each jump point. Useful for finding
a host that can call DO/Azure APIs or reach sipcore firewalls.

Default controllers (override with --host user@ip or --hosts-file):
  - local agent VM
  - root@64.23.158.213 (ASR / Semaphore) via keys/vm-access/id_ed25519
  - emir_@34.74.45.172 (max-quota) via keys/vm-access/id_ed25519

Examples:
  python3 scripts/probe_outbound_access.py
  python3 scripts/probe_outbound_access.py --host root@64.23.158.213
  python3 scripts/probe_outbound_access.py --out reports/outbound-probe.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field

DEFAULT_KEY = os.environ.get("PROBE_SSH_KEY", "keys/vm-access/id_ed25519")

# name, user@host or None for local, key path
DEFAULT_CONTROLLERS = [
    ("agent-vm", None, ""),
    ("ASR-semaphore", "root@64.23.158.213", DEFAULT_KEY),
    ("max-quota", "emir_@34.74.45.172", DEFAULT_KEY),
]

# Outbound targets to test from each controller
DEFAULT_TARGETS = [
    {"id": "public-ip", "kind": "curl", "url": "https://api.ipify.org?format=json",
     "expect_substr": "ip"},
    {"id": "digitalocean-api", "kind": "curl",
     "url": "https://api.digitalocean.com/v2/account",
     "expect_code": "401"},  # reachable without token
    {"id": "azure-mgmt", "kind": "curl",
     "url": "https://management.azure.com/",
     "expect_code": "400"},  # reachable, needs auth
    {"id": "devops-nextere", "kind": "curl", "url": "https://devops.nextere.com/api/ping",
     "expect_substr": "pong"},
    {"id": "sipcore-azure-pub", "kind": "tcp", "host": "172.178.82.217", "port": 22},
    {"id": "sipcore-azure-priv", "kind": "tcp", "host": "10.0.0.5", "port": 22},
    {"id": "sipcore-do-legacy", "kind": "tcp", "host": "149.130.210.6", "port": 22},
    {"id": "sipcore-do-api", "kind": "tcp", "host": "149.130.210.6", "port": 8003},
    {"id": "sipmedia-azure", "kind": "tcp", "host": "48.217.232.252", "port": 22},
    {"id": "voice-mysql-priv", "kind": "tcp", "host": "10.124.0.2", "port": 3306},
]


@dataclass
class ProbeResult:
    controller: str
    target_id: str
    status: str  # ok | fail | skip
    detail: str = ""
    egress_ip: str = ""


@dataclass
class Controller:
    name: str
    ssh_target: str | None  # None = local
    key_path: str = ""
    egress_ip: str = ""
    results: list[ProbeResult] = field(default_factory=list)


def local_shell(script: str, timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as exc:
        return 1, str(exc)


def remote_shell(ssh_target: str, key_path: str, script: str, timeout: int = 45) -> tuple[int, str]:
    if not os.path.isfile(key_path):
        return 127, f"missing key: {key_path}"
    cmd = [
        "ssh",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=12",
        "-o", "BatchMode=yes",
        ssh_target,
        "bash", "-s",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, "ssh timeout"
    except OSError as exc:
        return 1, str(exc)


def run_on(ctrl: Controller, script: str, timeout: int = 45) -> tuple[int, str]:
    if ctrl.ssh_target is None:
        return local_shell(script, timeout=timeout)
    return remote_shell(ctrl.ssh_target, ctrl.key_path, script, timeout=timeout)


def detect_egress_ip(ctrl: Controller) -> str:
    rc, out = run_on(ctrl, "curl -sf --max-time 8 https://api.ipify.org || true", timeout=15)
    ip = out.strip().splitlines()[-1] if out else ""
    if rc == 0 and re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
        return ip
    return ""


def probe_curl(ctrl: Controller, target: dict) -> ProbeResult:
    url = target["url"]
    expect_sub = target.get("expect_substr", "")
    expect_code = target.get("expect_code", "")
    script = f"""
url={json.dumps(url)}
code=$(curl -s -o /tmp/probe_out -w '%{{http_code}}' --max-time 12 "$url" 2>/dev/null || echo 000)
body=$(head -c 200 /tmp/probe_out 2>/dev/null || true)
echo "HTTP_CODE=$code"
echo "BODY=$body"
"""
    rc, out = run_on(ctrl, script)
    if rc == 124:
        return ProbeResult(ctrl.name, target["id"], "fail", "timeout")
    if rc != 0 and "HTTP_CODE=" not in out:
        return ProbeResult(ctrl.name, target["id"], "fail", out[:120] or f"exit {rc}")

    code_m = re.search(r"HTTP_CODE=(\d+)", out)
    body_m = re.search(r"BODY=(.*)", out, re.S)
    code = code_m.group(1) if code_m else "?"
    body = (body_m.group(1).strip() if body_m else "")[:80]

    if expect_code and code == expect_code:
        return ProbeResult(ctrl.name, target["id"], "ok", f"HTTP {code}")
    if expect_sub and expect_sub in body:
        return ProbeResult(ctrl.name, target["id"], "ok", f"HTTP {code} body match")
    if not expect_code and not expect_sub and code.startswith(("2", "3")):
        return ProbeResult(ctrl.name, target["id"], "ok", f"HTTP {code}")
    return ProbeResult(ctrl.name, target["id"], "fail", f"HTTP {code} {body}")


def probe_tcp(ctrl: Controller, target: dict) -> ProbeResult:
    host = target["host"]
    port = int(target["port"])
    script = f"""
if timeout 5 bash -c 'echo > /dev/tcp/{host}/{port}' 2>/dev/null; then
  echo TCP_OPEN
else
  echo TCP_CLOSED
fi
"""
    rc, out = run_on(ctrl, script, timeout=20)
    if rc == 124:
        return ProbeResult(ctrl.name, target["id"], "fail", "timeout")
    if "TCP_OPEN" in out:
        return ProbeResult(ctrl.name, target["id"], "ok", f"{host}:{port} open")
    if rc == 127 and "missing key" in out:
        return ProbeResult(ctrl.name, target["id"], "skip", out)
    if rc != 0 and "TCP_" not in out:
        return ProbeResult(ctrl.name, target["id"], "skip", out[:100] or f"ssh fail {rc}")
    return ProbeResult(ctrl.name, target["id"], "fail", f"{host}:{port} closed")


def probe_target(ctrl: Controller, target: dict) -> ProbeResult:
    kind = target.get("kind", "curl")
    if kind == "tcp":
        return probe_tcp(ctrl, target)
    return probe_curl(ctrl, target)


def parse_host_spec(spec: str, default_key: str) -> tuple[str, str | None, str]:
    """name or user@host or name:user@host"""
    key = default_key
    name = spec
    ssh = spec
    if ":" in spec and "@" in spec.split(":", 1)[1]:
        name, ssh = spec.split(":", 1)
    if ssh in ("local", "localhost", "-"):
        return name, None, ""
    return name, ssh, key


def load_controllers(args) -> list[Controller]:
    controllers: list[Controller] = []
    if args.host:
        for spec in args.host:
            name, ssh, key = parse_host_spec(spec, args.key)
            controllers.append(Controller(name=name, ssh_target=ssh, key_path=key))
    else:
        for name, ssh, key in DEFAULT_CONTROLLERS:
            controllers.append(Controller(name=name, ssh_target=ssh, key_path=key))
    return controllers


def print_report(controllers: list[Controller], targets: list[dict]):
    print("\n" + "=" * 80)
    print("OUTBOUND ACCESS MATRIX")
    print("=" * 80)
    header = f"{'Controller':<18} {'Egress IP':<18} " + " ".join(f"{t['id']:<16}" for t in targets)
    print(header)
    print("-" * len(header))

    for ctrl in controllers:
        by_id = {r.target_id: r for r in ctrl.results}
        cells = []
        for t in targets:
            r = by_id.get(t["id"])
            if not r:
                cells.append("?".ljust(16))
            elif r.status == "ok":
                cells.append("OK".ljust(16))
            elif r.status == "skip":
                cells.append("SKIP".ljust(16))
            else:
                cells.append("FAIL".ljust(16))
        print(f"{ctrl.name:<18} {(ctrl.egress_ip or 'n/a'):<18} " + " ".join(cells))

    print("\nDETAILS")
    for ctrl in controllers:
        print(f"\n--- {ctrl.name} ({ctrl.ssh_target or 'local'}) egress={ctrl.egress_ip or '?'} ---")
        for r in ctrl.results:
            print(f"  [{r.status:4}] {r.target_id}: {r.detail}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", action="append",
                   help="Controller: user@ip or name:user@ip or name:local")
    p.add_argument("--key", default=DEFAULT_KEY, help="SSH private key for remote controllers")
    p.add_argument("--out", default="reports/outbound-probe.json")
    p.add_argument("--targets-file", help="JSON file listing probe targets")
    p.add_argument("--skip-local", action="store_true")
    args = p.parse_args()

    targets = DEFAULT_TARGETS
    if args.targets_file:
        with open(args.targets_file, encoding="utf-8") as fh:
            targets = json.load(fh)

    controllers = load_controllers(args)
    if args.skip_local:
        controllers = [c for c in controllers if c.ssh_target is not None]

    for ctrl in controllers:
        if ctrl.ssh_target is None:
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(
                        "https://api.ipify.org",
                        headers={"User-Agent": "probe-outbound/1.0"},
                    ),
                    timeout=8,
                ) as resp:
                    ctrl.egress_ip = resp.read().decode().strip()
            except OSError:
                ctrl.egress_ip = detect_egress_ip(ctrl)
        else:
            rc, out = run_on(ctrl, "echo SSH_OK", timeout=15)
            if rc != 0:
                for t in targets:
                    ctrl.results.append(
                        ProbeResult(ctrl.name, t["id"], "skip", out[:80] or "ssh unreachable")
                    )
                continue
            ctrl.egress_ip = detect_egress_ip(ctrl)

        for target in targets:
            ctrl.results.append(probe_target(ctrl, target))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    payload = {
        "controllers": [
            {
                "name": c.name,
                "ssh_target": c.ssh_target,
                "egress_ip": c.egress_ip,
                "results": [
                    {"target_id": r.target_id, "status": r.status, "detail": r.detail}
                    for r in c.results
                ],
            }
            for c in controllers
        ],
        "targets": targets,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print_report(controllers, targets)
    print(f"\nJSON report: {args.out}")

    # Highlight controllers that can reach cloud APIs
    print("\n" + "=" * 80)
    print("CONTROLLERS THAT CAN REACH CLOUD / SIP TARGETS")
    for ctrl in controllers:
        ok_cloud = [r for r in ctrl.results
                    if r.status == "ok" and r.target_id in (
                        "digitalocean-api", "azure-mgmt", "sipcore-azure-pub",
                        "sipcore-do-legacy", "sipcore-do-api")]
        if ok_cloud:
            print(f"  {ctrl.name} ({ctrl.egress_ip}): "
                  + ", ".join(f"{r.target_id}" for r in ok_cloud))

    return 0


if __name__ == "__main__":
    sys.exit(main())
