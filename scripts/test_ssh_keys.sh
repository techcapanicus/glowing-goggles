#!/bin/bash
# Test SSH authentication with each private key file found on this host.
# Usage: TARGET_HOST=64.23.139.247 TARGET_USER=root LABEL=droplet ./scripts/test_ssh_keys.sh
set -uo pipefail

TARGET_HOST="${TARGET_HOST:-64.23.139.247}"
TARGET_USER="${TARGET_USER:-root}"
LABEL="${LABEL:-host}"
EXTRA_KEY="${EXTRA_KEY:-}"

test_key() {
  local key="$1"
  local name="$2"
  local host="$3"
  local fp pub out
  fp=$(ssh-keygen -lf "$key" 2>/dev/null | awk '{print $2}' || echo "unknown")
  pub=$(ssh-keygen -y -f "$key" 2>/dev/null | awk '{print $1, $2}' || echo "")
  echo ""
  echo "=== TEST: ${LABEL}:${name} ==="
  echo "  file: $key"
  echo "  fingerprint: $fp"
  echo "  pubkey: ${pub:0:72}..."
  if out=$(ssh -o BatchMode=yes \
               -o StrictHostKeyChecking=no \
               -o ConnectTimeout=8 \
               -o IdentitiesOnly=yes \
               -i "$key" \
               "${TARGET_USER}@${host}" \
               "echo SSH_OK; hostname" 2>&1); then
    echo "  RESULT: SUCCESS"
    echo "  output: $out"
  else
    echo "  RESULT: FAILED"
    echo "  error: $(echo "$out" | tail -3 | tr '\n' ' ')"
  fi
}

echo "=============================================="
echo "${LABEL^^} KEY TESTS -> ${TARGET_USER}@${TARGET_HOST} from $(hostname)"
echo "=============================================="

declare -A SEEN
KEYS=()
add_key() {
  local k="$1"
  [[ -f "$k" && -r "$k" ]] || return
  [[ -n "${SEEN[$k]:-}" ]] && return
  SEEN[$k]=1
  KEYS+=("$k")
}

[[ -n "$EXTRA_KEY" ]] && add_key "$EXTRA_KEY"
while IFS= read -r k; do
  add_key "$k"
done < <(find /tmp/semaphore /root/.ssh /home -type f \
  \( -name 'id_*' -o -name '*_ed25519' -o -name '*_rsa' \
  -o -name '*_ecdsa' -o -name '*_dsa' \) \
  ! -name '*.pub' ! -name 'known_hosts' \
  ! -name 'authorized_keys' ! -name 'config' 2>/dev/null | sort -u)

if [[ ${#KEYS[@]} -eq 0 ]]; then
  echo "No private key files found"
else
  for key in "${KEYS[@]}"; do
    test_key "$key" "$(basename "$key")" "$TARGET_HOST"
  done
fi

if [[ -f /root/.ssh/authorized_keys ]]; then
  echo ""
  echo "=== authorized_keys vs on-disk private keys ==="
  while IFS= read -r publine; do
    [[ -z "$publine" || "$publine" =~ ^# ]] && continue
    comment=$(echo "$publine" | awk '{print $NF}')
    matched="no"
    pubtype=$(echo "$publine" | awk '{print $1}')
    pubdata=$(echo "$publine" | awk '{print $2}')
    for key in "${KEYS[@]}"; do
      derived=$(ssh-keygen -y -f "$key" 2>/dev/null || true)
      dtype=$(echo "$derived" | awk '{print $1}')
      ddata=$(echo "$derived" | awk '{print $2}')
      if [[ "$pubtype" == "$dtype" && "$pubdata" == "$ddata" ]]; then
        matched="$key"
        break
      fi
    done
    echo "  [$comment] -> private_key=${matched}"
  done < /root/.ssh/authorized_keys
fi

echo ""
echo "=== SSH AGENT ==="
for sock in "${SSH_AUTH_SOCK:-}" /run/user/0/openssh_agent; do
  [[ -n "$sock" && -S "$sock" ]] || continue
  SSH_AUTH_SOCK="$sock" ssh-add -l 2>/dev/null || echo "  $sock: empty"
done

echo ""
echo "=============================================="
echo "TESTS COMPLETE"
echo "=============================================="
