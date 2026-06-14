#!/bin/bash
set -euo pipefail

DO_TOKEN="${DO_TOKEN:?DO_TOKEN env var required}"
TARGET_IP="${TARGET_IP:-}"
SSH_KEY="${SSH_KEY_PATH:-/root/.ssh/id_ed25519}"
TARGET_HOST="64.23.139.247"
TARGET_USER="root"

echo "=== DO SSH Firewall Whitelist Script ==="

# Detect IP if not provided
if [[ -z "$TARGET_IP" ]]; then
  TARGET_IP=$(curl -sf https://api.ipify.org || \
              curl -sf https://checkip.amazonaws.com | tr -d '[:space:]')
  echo "Auto-detected IP: $TARGET_IP"
else
  echo "Using provided IP: $TARGET_IP"
fi

# Get all firewalls
echo ""
echo "=== Fetching DO Firewalls ==="
FIREWALLS=$(curl -sf \
  -H "Authorization: Bearer $DO_TOKEN" \
  "https://api.digitalocean.com/v2/firewalls")

echo "$FIREWALLS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for fw in data.get('firewalls', []):
    print(f\"  [{fw['id']}] {fw['name']}\")
"

# Add rule to each firewall
echo ""
echo "=== Adding SSH rule for $TARGET_IP/32 ==="
FIREWALL_IDS=$(echo "$FIREWALLS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for fw in data.get('firewalls', []):
    print(fw['id'])
")

for FW_ID in $FIREWALL_IDS; do
  echo -n "  Firewall $FW_ID: "
  RESULT=$(curl -sf -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $DO_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"inbound_rules\": [{
        \"protocol\": \"tcp\",
        \"ports\": \"22\",
        \"sources\": {\"addresses\": [\"${TARGET_IP}/32\"]}
      }]
    }" \
    "https://api.digitalocean.com/v2/firewalls/${FW_ID}/rules")

  if [[ "$RESULT" == "204" ]]; then
    echo "ADDED ✓"
  elif [[ "$RESULT" == "422" ]]; then
    echo "ALREADY EXISTS ✓"
  else
    echo "FAILED (HTTP $RESULT)"
  fi
done

echo ""
echo "=== Waiting 8s for propagation ==="
sleep 8

echo ""
echo "=== Testing SSH to $TARGET_HOST ==="
if ssh -o StrictHostKeyChecking=no \
       -o ConnectTimeout=10 \
       -o BatchMode=yes \
       -i "$SSH_KEY" \
       "${TARGET_USER}@${TARGET_HOST}" \
       "echo SSH_OK" 2>/dev/null; then
  echo "SUCCESS: SSH connection to $TARGET_HOST working"
else
  echo "FAILED: SSH still not connecting"
  echo "Running verbose debug:"
  ssh -vvv \
      -o StrictHostKeyChecking=no \
      -o ConnectTimeout=10 \
      -o BatchMode=yes \
      -i "$SSH_KEY" \
      "${TARGET_USER}@${TARGET_HOST}" \
      "echo SSH_OK" 2>&1 | \
      grep -E "(connect|auth|Accepted|refused|denied|timeout|key)" | \
      head -20
fi

echo ""
echo "=== To remove this rule later ==="
echo "Run: DELETE /v2/firewalls/{id}/rules with same body"
echo "Or:  doctl compute firewall list && doctl compute firewall \
remove-rules <ID> --inbound-rules protocol:tcp,ports:22,\
address:${TARGET_IP}/32"
