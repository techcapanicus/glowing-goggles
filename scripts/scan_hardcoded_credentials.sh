#!/bin/bash
# Scan a Linux host for hardcoded credentials (run locally or via SSH).
#
# Usage (from Cursor terminal on your machine):
#   ssh -i keys/vm-access/id_ed25519 root@64.23.158.213 'bash -s' < scripts/scan_hardcoded_credentials.sh
#
# Or on the server directly:
#   bash scripts/scan_hardcoded_credentials.sh
#
# Options:
#   REDACT=1     mask values in output (default)
#   REDACT=0     print raw matches (dangerous — local only)
#   REPORT=/path write full log to file

set -uo pipefail

REDACT="${REDACT:-1}"
REPORT="${REPORT:-/tmp/credential-scan-$(date +%Y%m%d-%H%M%S).txt}"

CRED_PAT='password|passwd|secret|api[_-]?key|api[_-]?token|access[_-]?token|bearer|dop_v1|do_token|private[_-]?key|BEGIN (RSA|OPENSSH|EC) PRIVATE|aws_secret|AKIA[0-9A-Z]{16}|mongodb(\+srv)?://|mysql://|postgres(ql)?://|jdbc:|sk_live_|sk_test_|SG\.[A-Za-z0-9._-]+'

redact_line() {
  if [[ "$REDACT" == "1" ]]; then
    sed -E 's/=.*/=***REDACTED***/; s/:[[:space:]]*.*/: ***REDACTED***/; s/dop_v1_[a-f0-9]+/dop_v1_***REDACTED***/g'
  else
    cat
  fi
}

exec > >(tee "$REPORT") 2>&1

echo "=============================================="
echo "HARDCODED CREDENTIAL SCAN — $(hostname) — $(date -Iseconds)"
echo "REDACT=$REDACT  REPORT=$REPORT"
echo "=============================================="

section() { echo ""; echo "=== $1 ==="; }

section "1. LIVE .env FILES (highest risk)"
find /opt /root /var/www /home -type f \( -name '.env' -o -name '.env.*' -o -name '*.env' \) \
  ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/ansible_env/*' 2>/dev/null | sort | while read -r f; do
  hits=$(grep -ciE "$CRED_PAT" "$f" 2>/dev/null || true)
  [[ "$hits" -gt 0 ]] || continue
  echo "--- $f ($hits credential-like lines) ---"
  grep -niE "$CRED_PAT" "$f" 2>/dev/null | redact_line | head -25
done

section "2. ANSIBLE VAULT / group_vars secrets"
find /root/snap/semaphore/common/repositories /root/te -type f \
  \( -name 'vault.yml' -o -name '*.vault' -o -path '*/group_vars/*' \) \
  2>/dev/null | head -30 | while read -r f; do
  if grep -qiE 'vault|password|secret|token|dop_v1|\$ANSIBLE_VAULT' "$f" 2>/dev/null; then
    echo "--- $f ---"
    grep -niE 'vault|password|secret|token|mysql|mongo|dop_v1' "$f" 2>/dev/null | redact_line | head -8
  fi
done

section "3. CLOUD CLI CONFIG"
for f in /root/.config/doctl/config.yaml /root/.aws/credentials /root/.aws/config; do
  [[ -f "$f" ]] || continue
  echo "--- $f ---"
  redact_line < "$f"
done
find /root /home -path '*/.azure/*.json' 2>/dev/null | head -5 | while read -r f; do
  echo "--- $f ---"
  redact_line < "$f" | head -10
done

section "4. SEMAPHORE CONFIG"
CFG=/root/snap/semaphore/common/config.json
if [[ -f "$CFG" ]]; then
  echo "--- $CFG ---"
  python3 -c "import json; print(json.dumps(json.load(open('$CFG')), indent=2))" 2>/dev/null | redact_line
fi
echo "database: /root/snap/semaphore/common/database.boltdb ($(du -h /root/snap/semaphore/common/database.boltdb 2>/dev/null | awk '{print $1}'))"

section "5. PRIVATE SSH/TLS KEYS"
find /root/.ssh /opt -type f \( -name 'id_rsa' -o -name 'id_ed25519' -o -name 'id_ecdsa' -o -name '*.pem' \) \
  ! -name '*.pub' 2>/dev/null | while read -r f; do
  fp=$(ssh-keygen -lf "$f" 2>/dev/null | awk '{print $2}' || echo unreadable)
  echo "$f  perms=$(stat -c '%a' "$f" 2>/dev/null)  fp=$fp"
done

section "6. SHELL HISTORY (tokens in curl/commands)"
for hf in /root/.bash_history /root/.zsh_history; do
  [[ -f "$hf" ]] || continue
  echo "--- $hf ---"
  grep -niE 'bearer |dop_v1|password=|api[_-]?key|Authorization:|mysql://|mongodb' "$hf" 2>/dev/null | redact_line | tail -15
done

section "7. dop_v1 / DO_TOKEN (actual tokens only)"
grep -rnoE 'dop_v1_[a-f0-9]{20,}' /root /opt /etc 2>/dev/null \
  --exclude-dir=node_modules --exclude-dir=.git --exclude='*.boltdb' --exclude='*.log' | redact_line | head -20
if [[ "$(grep -rnoE 'dop_v1_[a-f0-9]{20,}' /root /opt /etc 2>/dev/null | wc -l)" -eq 0 ]]; then
  echo "(no live dop_v1 tokens found — only references in scripts/docs)"
fi

section "8. MONGODB/MYSQL CONNECTION STRINGS (live configs)"
grep -rniE 'mongodb(\+srv)?://[^[:space:]]+|mysql://[^[:space:]]+|DB_PASSWORD|DB_CONNECTION_STR|MONGO_URI|rds_dsn' \
  /opt /root/snap/semaphore/common/repositories/repository_1_1/deploy/ansible-playbooks/inventory \
  2>/dev/null | redact_line | head -25

section "9. PM2 / running app env"
if command -v pm2 >/dev/null 2>&1; then
  pm2 jlist 2>/dev/null | python3 -c "
import json,sys,re
pat=re.compile(r'password|secret|token|key', re.I)
try:
    apps=json.load(sys.stdin)
except: sys.exit(0)
for a in apps:
    env=a.get('pm2_env',{}).get('env',{})
    hits={k:v for k,v in env.items() if pat.search(k)}
    if hits:
        print('--- pm2', a.get('name'), '---')
        for k in hits: print(' ', k, '=***REDACTED***')
" 2>/dev/null
fi

section "10. GIT CONFIG (embedded tokens in URLs)"
find /root/snap/semaphore/common/repositories -path '*/.git/config' 2>/dev/null | while read -r f; do
  if grep -qE '@|token|oauth' "$f" 2>/dev/null; then
    echo "--- $f ---"
    grep -E 'url|insteadOf' "$f" | redact_line
  fi
done

echo ""
echo "=============================================="
echo "SCAN COMPLETE — $REPORT"
echo "=============================================="
