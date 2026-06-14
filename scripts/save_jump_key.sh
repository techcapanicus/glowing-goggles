#!/bin/bash
# Run this on your LOCAL machine after getting
# the private key from Semaphore task output
#
# Or: paste key into PRIVATEKEY heredoc below, then:
#   ./scripts/save_jump_key.sh

set -euo pipefail

KEY_FILE="${HOME}/.ssh/media_id_ed25519"
CONFIG_FILE="${HOME}/.ssh/config"
MARKER_START="-----BEGIN OPENSSH PRIVATE KEY-----"
MARKER_END="-----END OPENSSH PRIVATE KEY-----"

mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"

if [[ "${1:-}" == "--from-file" && -n "${2:-}" ]]; then
  cp "$2" "$KEY_FILE"
elif [[ "${1:-}" == "--from-stdin" ]]; then
  cat > "$KEY_FILE"
elif grep -q "PASTE_PRIVATE_KEY_HERE" "$0" 2>/dev/null; then
  cat > "$KEY_FILE" << 'PRIVATEKEY'
PASTE_PRIVATE_KEY_HERE
PRIVATEKEY
  if grep -q "PASTE_PRIVATE_KEY_HERE" "$KEY_FILE"; then
    echo "Replace PASTE_PRIVATE_KEY_HERE in this script, or run:" >&2
    echo "  $0 --from-file /path/to/key" >&2
    echo "  semaphore-task-output.txt | $0 --from-stdin" >&2
    exit 1
  fi
else
  echo "Usage: $0 [--from-file KEY | --from-stdin]" >&2
  exit 2
fi

chmod 600 "$KEY_FILE"
echo "Key saved to $KEY_FILE"

if ! grep -q "Host semaphore-jump" "$CONFIG_FILE" 2>/dev/null; then
  cat >> "$CONFIG_FILE" << EOF

Host semaphore-jump
  HostName 209.38.146.146
  Port 443
  User root
  IdentityFile $KEY_FILE
  StrictHostKeyChecking no
  ServerAliveInterval 30

Host media
  HostName 64.23.139.247
  User root
  IdentityFile $KEY_FILE
  ProxyJump semaphore-jump
  StrictHostKeyChecking no
  ServerAliveInterval 30
EOF
  echo "SSH config updated"
else
  echo "SSH config already has semaphore-jump/media entries (skipped)"
fi

echo ""
echo "Test with: ssh -v media"
echo "Or direct: ssh -i $KEY_FILE -J root@209.38.146.146 root@64.23.139.247"
echo ""
echo "Key fingerprint:"
ssh-keygen -lf "$KEY_FILE"
echo "Expected pubkey ends with: ...ExC7wVTlqvZ1vqgHPTVUU7nVhdTPlPfWmO2ApZVeNhj root@media"
