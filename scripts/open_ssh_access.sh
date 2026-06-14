#!/usr/bin/env bash
# Whitelist an IP for SSH (tcp/22) on a DigitalOcean Cloud Firewall.
#
# Usage:
#   export DOCTL_TOKEN=...
#   ./scripts/open_ssh_access.sh --firewall-id <uuid>
#   ./scripts/open_ssh_access.sh --ip 203.0.113.10 --firewall-id <uuid>
#   ./scripts/open_ssh_access.sh --droplet-ip 64.23.139.247   # auto-detect firewall
#
# DO_FIREWALL_ID and TARGET_HOSTS from .env are used as defaults when set.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

IP=""
FIREWALL_ID="${DO_FIREWALL_ID:-}"
DROPLET_IP="${TARGET_HOSTS%%,*}"
DRY_RUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip) IP="$2"; shift 2 ;;
    --firewall-id) FIREWALL_ID="$2"; shift 2 ;;
    --droplet-ip) DROPLET_IP="$2"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

ARGS=()
[[ -n "$IP" ]] && ARGS+=(--ip "$IP")
[[ -n "$FIREWALL_ID" ]] && ARGS+=(--firewall-id "$FIREWALL_ID")
[[ -n "$DROPLET_IP" ]] && ARGS+=(--droplet-ip "$DROPLET_IP")
[[ -n "$DRY_RUN" ]] && ARGS+=("$DRY_RUN")

if [[ -z "$FIREWALL_ID" && -z "$DROPLET_IP" ]]; then
  echo "Pass --firewall-id and/or --droplet-ip (or set DO_FIREWALL_ID / TARGET_HOSTS in .env)." >&2
  exit 2
fi

python3 scripts/do_firewall_ssh.py "${ARGS[@]}"
