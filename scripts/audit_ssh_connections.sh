#!/bin/bash
# Collect authorized_keys / on-disk keys and test SSH auth to targets.
#
# Modes (AUDIT_MODE):
#   collect  — dump authorized_keys and key inventory on this host
#   test     — try local private keys against TARGET_HOSTS
#   full     — collect + test (default)
#
# Environment:
#   TARGET_HOSTS   comma-separated host:port or host (default: TARGET_HOST)
#   TARGET_HOST    single host fallback
#   TARGET_USER    SSH user (default: root)
#   LABEL          report prefix (default: hostname)
#   EXTRA_KEY      extra private key path to include in tests
#   EXTRA_KEYS     colon-separated extra key paths
#   KEY_DIRS       colon-separated dirs to scan (default: /root/.ssh:/home)
set -uo pipefail

AUDIT_MODE="${AUDIT_MODE:-full}"
TARGET_USER="${TARGET_USER:-root}"
LABEL="${LABEL:-$(hostname)}"
TARGET_HOST="${TARGET_HOST:-}"
TARGET_HOSTS="${TARGET_HOSTS:-$TARGET_HOST}"
EXTRA_KEY="${EXTRA_KEY:-}"
EXTRA_KEYS="${EXTRA_KEYS:-}"
KEY_DIRS="${KEY_DIRS:-/root/.ssh:/home}"

section() {
  echo ""
  echo "=== $1 ==="
}

collect_authorized_keys() {
  section "HOST INFO — ${LABEL}"
  echo "hostname=$(hostname)"
  echo "fqdn=$(hostname -f 2>/dev/null || hostname)"
  echo "date=$(date -Iseconds)"
  ip -4 addr show scope global 2>/dev/null | awk '/inet /{print "ipv4="$2}' || true

  section "ACTIVE SSH SESSION"
  echo "SSH_CONNECTION=${SSH_CONNECTION:-}"
  echo "SSH_CLIENT=${SSH_CLIENT:-}"
  who -a 2>/dev/null | head -20 || true

  section "AUTHORIZED_KEYS (root)"
  if [[ -f /root/.ssh/authorized_keys ]]; then
    nl -ba /root/.ssh/authorized_keys 2>/dev/null | while read -r _ n line; do
      [[ -z "$line" || "$line" =~ ^# ]] && continue
      fp=$(echo "$line" | awk '{print $1, $2}' | ssh-keygen -lf - 2>/dev/null | awk '{print $2}' || echo "?")
      comment=$(echo "$line" | awk '{print $NF}')
      echo "  [$n] $fp $comment"
      echo "       ${line:0:100}..."
    done
  else
    echo "(no /root/.ssh/authorized_keys)"
  fi

  section "ALL authorized_keys ON SYSTEM"
  find /etc /root /home -name authorized_keys 2>/dev/null \
    | grep -v /proc | head -50 | while read -r ak; do
    echo "--- $ak ---"
    grep -v '^#' "$ak" 2>/dev/null | while read -r line; do
      [[ -z "$line" ]] && continue
      fp=$(echo "$line" | awk '{print $1, $2}' | ssh-keygen -lf - 2>/dev/null | awk '{print $2}' || echo "?")
      comment=$(echo "$line" | awk '{print $NF}')
      echo "  $fp $comment"
    done
  done

  section "PRIVATE KEYS ON DISK (fingerprints only)"
  IFS=':' read -ra DIRS <<< "$KEY_DIRS"
  for dir in "${DIRS[@]}"; do
    [[ -d "$dir" ]] || continue
    find "$dir" -type f \
      \( -name 'id_*' -o -name '*_ed25519' -o -name '*_rsa' \
      -o -name '*_ecdsa' -o -name '*_dsa' \) \
      ! -name '*.pub' ! -name 'known_hosts' ! -name 'authorized_keys' \
      ! -name 'config' 2>/dev/null | sort -u | while read -r key; do
      fp=$(ssh-keygen -lf "$key" 2>/dev/null | awk '{print $2}' || echo "unreadable")
      comment=$(ssh-keygen -lf "$key" 2>/dev/null | awk '{print $NF}' || true)
      echo "  $key  $fp  $comment"
    done
  done

  section "PUBLIC KEY FILES"
  for dir in "${DIRS[@]}"; do
    [[ -d "$dir" ]] || continue
    find "$dir" -name '*.pub' 2>/dev/null | sort -u | while read -r pub; do
      echo "  $pub: $(cat "$pub" 2>/dev/null | awk '{print $3}')"
    done
  done

  section "SSHD CONFIG"
  grep -iE '^(Port|ListenAddress|AuthorizedKeysFile|PermitRootLogin|PubkeyAuthentication|PasswordAuthentication)' \
    /etc/ssh/sshd_config 2>/dev/null || true

  section "DIGITALOCEAN METADATA KEYS"
  curl -sf http://169.254.169.254/metadata/v1/public-keys 2>/dev/null \
    | while read -r line; do
      [[ -z "$line" ]] && continue
      fp=$(echo "$line" | awk '{print $1, $2}' | ssh-keygen -lf - 2>/dev/null | awk '{print $2}' || echo "?")
      echo "  metadata $fp $(echo "$line" | awk '{print $NF}')"
    done || echo "(metadata unavailable)"
}

add_key() {
  local k="$1"
  [[ -f "$k" && -r "$k" ]] || return
  [[ -n "${SEEN_KEYS[$k]:-}" ]] && return
  SEEN_KEYS[$k]=1
  KEYS+=("$k")
}

test_connections() {
  declare -A SEEN_KEYS
  KEYS=()

  [[ -n "$EXTRA_KEY" ]] && add_key "$EXTRA_KEY"
  if [[ -n "$EXTRA_KEYS" ]]; then
    IFS=':' read -ra EK <<< "$EXTRA_KEYS"
    for k in "${EK[@]}"; do add_key "$k"; done
  fi

  IFS=':' read -ra DIRS <<< "$KEY_DIRS"
  for dir in "${DIRS[@]}"; do
    [[ -d "$dir" ]] || continue
    while IFS= read -r k; do
      add_key "$k"
    done < <(find "$dir" -type f \
      \( -name 'id_*' -o -name '*_ed25519' -o -name '*_rsa' \
      -o -name '*_ecdsa' -o -name '*_dsa' \) \
      ! -name '*.pub' ! -name 'known_hosts' ! -name 'authorized_keys' \
      ! -name 'config' 2>/dev/null | sort -u)
  done

  # Local VM keys
  for k in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa" \
           /workspace/keys/media_id_ed25519 \
           /workspace/keys/mcm-controller/id_ed25519; do
    add_key "$k"
  done

  section "SSH CONNECTION TESTS from ${LABEL}"
  echo "keys_to_test=${#KEYS[@]}"

  if [[ -z "$TARGET_HOSTS" ]]; then
    echo "No TARGET_HOSTS set — skipping connection tests"
    return
  fi

  IFS=',' read -ra HOSTS <<< "$TARGET_HOSTS"
  for raw in "${HOSTS[@]}"; do
    raw="${raw// /}"
    [[ -z "$raw" ]] && continue
    host="$raw"
    port=22
    if [[ "$raw" == *:* ]]; then
      host="${raw%%:*}"
      port="${raw##*:}"
    fi

    echo ""
    echo "--- target ${TARGET_USER}@${host}:${port} ---"
    if ! timeout 5 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
      echo "  PORT: UNREACHABLE (tcp/$port closed or filtered)"
      continue
    fi
    echo "  PORT: tcp/$port reachable"

    if [[ ${#KEYS[@]} -eq 0 ]]; then
      echo "  KEYS: none found on this host"
      continue
    fi

    for key in "${KEYS[@]}"; do
      name=$(basename "$key")
      fp=$(ssh-keygen -lf "$key" 2>/dev/null | awk '{print $2}' || echo "?")
      if out=$(ssh -p "$port" -o BatchMode=yes \
                  -o StrictHostKeyChecking=no \
                  -o ConnectTimeout=8 \
                  -o IdentitiesOnly=yes \
                  -i "$key" \
                  "${TARGET_USER}@${host}" \
                  "echo SSH_OK; hostname" 2>&1); then
        echo "  GOOD  key=$name fp=$fp -> $(echo "$out" | tr '\n' ' ')"
      else
        err=$(echo "$out" | tail -2 | tr '\n' ' ')
        echo "  BAD   key=$name fp=$fp -> $err"
      fi
    done
  done
}

echo "=============================================="
echo "SSH AUDIT — ${LABEL} — mode=${AUDIT_MODE}"
echo "=============================================="

case "$AUDIT_MODE" in
  collect) collect_authorized_keys ;;
  test)    test_connections ;;
  full)
    collect_authorized_keys
    test_connections
    ;;
  *)
    echo "Unknown AUDIT_MODE=$AUDIT_MODE (use collect|test|full)"
    exit 2
    ;;
esac

echo ""
echo "=============================================="
echo "AUDIT COMPLETE — ${LABEL}"
echo "=============================================="
