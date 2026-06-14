#!/usr/bin/env bash
# Provision SSH access for the Semaphore UI dev environment.
#
# Copy .env.example to .env, set SEMAPHORE_TOKEN and TARGET_HOSTS, then:
#   ./scripts/provision-dev-ssh.sh
#
# Omit --dry-run to actually write root's authorized_keys on the target host.
# Generated keys are saved under keys/semaphore-ui-dev/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example, set SEMAPHORE_TOKEN and TARGET_HOSTS." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a && source .env && set +a

: "${SEMAPHORE_TOKEN:?Set SEMAPHORE_TOKEN in .env}"
: "${TARGET_HOSTS:?Set TARGET_HOSTS in .env}"

exec python3 provision_ssh.py \
  --project-id "${SEMAPHORE_PROJECT_ID:-6}" \
  --ssh-key-id "${SSH_KEY_ID:-303}" \
  --prefix "${RESOURCE_PREFIX:-semaphore-ui-dev}" \
  --save-key-dir "${SAVE_KEY_DIR:-keys/semaphore-ui-dev}" \
  --bootstrap-user "${BOOTSTRAP_USER:-root}" \
  --target-user "${TARGET_USER:-root}" \
  --repo-git-url "${REPO_GIT_URL:-https://github.com/techcapanicus/glowing-goggles.git}" \
  --repo-branch "${REPO_BRANCH:-main}" \
  --playbook "${PLAYBOOK:-ansible/provision_ssh.yml}" \
  "$@"
