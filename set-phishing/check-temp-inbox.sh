#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.netlify-temp-email.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

TOKEN_JSON=$(curl -s -X POST https://api.mail.tm/token \
  -H "Content-Type: application/json" \
  -d "{\"address\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")

TOKEN=$(echo "$TOKEN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

echo "Inbox: $EMAIL"
echo "---"

MESSAGES=$(curl -s https://api.mail.tm/messages -H "Authorization: Bearer $TOKEN")
echo "$MESSAGES" | python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('hydra:member', [])
if not items:
    print('No messages yet.')
else:
    for m in items:
        print(f\"[{m.get('id')}] {m.get('from',{}).get('address','?')} — {m.get('subject','(no subject)')}\")
"

if [[ "${1:-}" == "--latest-link" ]]; then
  MSG_ID=$(echo "$MESSAGES" | python3 -c "import sys,json; m=json.load(sys.stdin).get('hydra:member',[]); print(m[0]['id'] if m else '')")
  if [[ -z "$MSG_ID" ]]; then exit 0; fi
  BODY=$(curl -s "https://api.mail.tm/messages/$MSG_ID" -H "Authorization: Bearer $TOKEN")
  echo "$BODY" | python3 -c "
import sys, json, re
msg = json.load(sys.stdin)
text = (msg.get('text') or '') + ' ' + (msg.get('html') or '')
links = re.findall(r'https://app\\.netlify\\.com[^\\s\"<>]+', text)
for link in links:
    print(link)
"
fi
