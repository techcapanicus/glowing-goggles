#!/usr/bin/env bash
# Allow this machine's public IP to SSH to the dev target via Semaphore/Ansible.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and set SEMAPHORE_TOKEN + TARGET_HOSTS." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a && source .env && set +a

: "${SEMAPHORE_TOKEN:?Set SEMAPHORE_TOKEN in .env}"
: "${TARGET_HOSTS:?Set TARGET_HOSTS in .env}"

VM_IP="${ALLOWED_IP:-$(curl -fsS --max-time 10 https://api.ipify.org)}"
echo "Allowing SSH from ${VM_IP} to ${TARGET_HOSTS}"

PUB_KEY="${NEW_PUBLIC_KEY:-keys/semaphore-ui-dev/id_ed25519.pub}"
if [[ ! -f "$PUB_KEY" ]]; then
  echo "Missing public key at ${PUB_KEY}" >&2
  exit 1
fi

exec python3 provision_ssh.py \
  --project-id "${SEMAPHORE_PROJECT_ID:-6}" \
  --ssh-key-id "${SSH_KEY_ID:-303}" \
  --prefix "${ALLOW_PREFIX:-ssh-allow-vm}" \
  --target-hosts "${TARGET_HOSTS}" \
  --bootstrap-user "${BOOTSTRAP_USER:-root}" \
  --target-user "${TARGET_USER:-root}" \
  --new-public-key "$PUB_KEY" \
  --playbook "${ALLOW_PLAYBOOK:-ansible/allow_ssh_ip.yml}" \
  --allowed-ip "$VM_IP" \
  --repo-git-url "${REPO_GIT_URL:-https://github.com/techcapanicus/glowing-goggles.git}" \
  --repo-branch "${REPO_BRANCH:-cursor/dev-ssh-key-provision-1218}" \
  "$@"
