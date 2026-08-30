#!/bin/bash
# Deep credential inspection for ASR or any Linux host.
set -uo pipefail
REPORT="${REPORT:-/tmp/deep-cred-scan-$(date +%Y%m%d-%H%M%S).txt}"
exec > >(tee "$REPORT") 2>&1

mask() {
  sed -E \
    -e 's/(aws_access_key_id[[:space:]]*=[[:space:]]*)[^[:space:]]+/\1***REDACTED***/g' \
    -e 's/(aws_secret_access_key[[:space:]]*=[[:space:]]*)[^[:space:]]+/\1***REDACTED***/g' \
    -e 's/(Bearer[[:space:]]+)[^[:space:]]+/\1***REDACTED***/gi' \
    -e 's/dop_v1_[a-f0-9]+/dop_v1_***REDACTED***/g' \
    -e 's#(mongodb(\+srv)?://)[^@]+@#\1***@#g' \
    -e 's#(mysql://)[^@]+@#\1***@#g' \
    -e 's/(password[[:space:]]*[=:][[:space:]]*)[^[:space:]"'"'"']+/\1***REDACTED***/gi' \
    -e 's/(secret[[:space:]]*[=:][[:space:]]*)[^[:space:]"'"'"']+/\1***REDACTED***/gi' \
    -e 's/(token[[:space:]]*[=:][[:space:]]*)[^[:space:]"'"'"']+/\1***REDACTED***/gi' \
    -e 's/(api[_-]?key[[:space:]]*[=:][[:space:]]*)[^[:space:]"'"'"']+/\1***REDACTED***/gi' \
    -e 's/sk_live_[a-zA-Z0-9]+/sk_live_***REDACTED***/g' \
    -e 's/sk_test_[a-zA-Z0-9]+/sk_test_***REDACTED***/g' \
    -e 's/SG\.[a-zA-Z0-9._-]+/SG.***REDACTED***/g' \
    -e 's/eyJ[a-zA-Z0-9._-]{20,}/eyJ***REDACTED***/g' \
    -e 's/KEY0[a-zA-Z0-9]+/KEY0***REDACTED***/g' \
    -e 's/HTPP[a-zA-Z0-9]+/HTPP***REDACTED***/g'
}

echo "################################################################"
echo "# DEEP CREDENTIAL SCAN — $(hostname) — $(date -Iseconds)"
echo "################################################################"

echo ""
echo "========== TIER 1: LIVE PLAINTEXT .env FILES =========="
while IFS= read -r f; do
  lines=$(wc -l < "$f" 2>/dev/null || echo 0)
  echo ""
  echo "FILE: $f ($lines lines)"
  grep -nE 'PASSWORD|SECRET|TOKEN|KEY|DSN|CONNECTION|MONGO|JWT|STRIPE|SENDGRID|TELNYX|CRYPTO|WASABI|AWS_|PRIVATE|mysql://|mongodb' "$f" 2>/dev/null | mask | head -35
done < <(find /opt /root/te /var/www /home -type f \( -name '.env' -o -name '.env.bak' -o -name '.env.production' \) ! -path '*/node_modules/*' 2>/dev/null | sort)

echo ""
echo "========== TIER 2: AWS / WASABI / DOCTL =========="
for f in /root/.aws/credentials /root/.aws/config /root/.config/doctl/config.yaml; do
  if [[ -f "$f" ]]; then echo "--- $f ---"; mask < "$f"; fi
done

echo ""
echo "========== TIER 3: PRIVATE SSH KEYS =========="
find /root/.ssh /opt -type f \( -name 'id_rsa' -o -name 'id_ed25519' -o -name 'id_ecdsa' \) ! -name '*.pub' 2>/dev/null | while read -r f; do
  fp=$(ssh-keygen -lf "$f" 2>/dev/null | awk '{print $2,$3}' || echo unreadable)
  echo "$f  perms=$(stat -c '%a' "$f" 2>/dev/null)  $fp"
done

echo ""
echo "========== TIER 4: SEMAPHORE =========="
[[ -f /root/snap/semaphore/common/config.json ]] && echo "--- config.json ---" && mask < /root/snap/semaphore/common/config.json
echo "--- boltdb credential string sample ---"
strings /root/snap/semaphore/common/database.boltdb 2>/dev/null | \
  grep -iE 'dop_v1_|BEGIN (RSA|OPENSSH)|mongodb(\+srv)?://|mysql://|sk_live|sk_test|SG\.|eyJhbG|password|secret' | \
  mask | sort -u | head -50

echo ""
echo "========== TIER 5: ANSIBLE group_vars (voice/phone) =========="
for f in $(find /root/snap/semaphore/common/repositories/repository_1_1/deploy/ansible-playbooks/inventory \
           /root/te/devops/deploy/ansible-playbooks/inventory -name 'all.yml' 2>/dev/null); do
  if grep -qiE 'password|secret|token|vault|mysql|mongo' "$f" 2>/dev/null; then
    echo "--- $f ---"
    grep -nE 'password|secret|token|mysql|mongo|vault|dsn|dop_v1' "$f" 2>/dev/null | mask | head -15
  fi
done

echo ""
echo "========== TIER 6: RUNNING PROCESS ENV (secrets in memory) =========="
for pid in $(pgrep -f 'node|python|semaphore|pm2' 2>/dev/null | head -40); do
  cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | cut -c1-90)
  envhits=$(tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -iE 'PASSWORD|SECRET|TOKEN|KEY|DSN|JWT|AWS_|STRIPE' | mask | head -6)
  if [[ -n "$envhits" ]]; then
    echo "--- PID $pid: $cmd ---"
    echo "$envhits"
  fi
done

echo ""
echo "========== TIER 7: PM2 =========="
if command -v pm2 >/dev/null; then
  pm2 list 2>/dev/null || true
  pm2 jlist 2>/dev/null | python3 -c "
import json,sys,re
pat=re.compile(r'PASS|SECRET|TOKEN|KEY|DSN|JWT|STRIPE|SENDGRID|WASABI|CRYPTO', re.I)
try: apps=json.load(sys.stdin)
except: sys.exit(0)
for a in apps:
    env=a.get('pm2_env',{}).get('env',{}) or {}
    hits={k:v for k,v in env.items() if pat.search(k) and v}
    if hits:
        print('--- pm2', a.get('name'), '---')
        for k,v in hits.items():
            print('  %s=***REDACTED*** (len=%d)' % (k, len(str(v))))
" 2>/dev/null || true
fi

echo ""
echo "========== TIER 8: MYSQL LOCAL =========="
[[ -f /etc/mysql/debian.cnf ]] && echo "--- debian.cnf ---" && mask < /etc/mysql/debian.cnf
mysql -N -e "SELECT user,host,plugin FROM mysql.user LIMIT 20;" 2>/dev/null || echo "(no local mysql shell access)"

echo ""
echo "========== TIER 9: BASH HISTORY =========="
[[ -f /root/.bash_history ]] && grep -niE 'bearer |Authorization:|dop_v1|password=|sk_live|sk_test|KEY0|mongodb|mysql://' /root/.bash_history 2>/dev/null | mask | tail -25

echo ""
echo "========== TIER 10: LIVE dop_v1 / AZURE ON DISK =========="
echo -n "dop_v1 count: "
grep -roE 'dop_v1_[a-f0-9]{20,}' /root /opt /etc 2>/dev/null --exclude='*.boltdb' | wc -l
grep -roE 'dop_v1_[a-f0-9]{20,}' /root /opt /etc 2>/dev/null --exclude='*.boltdb' | mask | head -3
echo -n "Azure client_secret in .env: "
grep -rl 'AZURE_CLIENT_SECRET\|client_secret' /opt --include='*.env' 2>/dev/null | wc -l

echo ""
echo "========== TIER 11: CREDENTIAL KEY INVENTORY (.env var names) =========="
python3 <<'PY'
import os, re
from collections import defaultdict
by_key = defaultdict(set)
for root, dirs, files in os.walk('/opt'):
    if 'node_modules' in root:
        continue
    for fn in files:
        if not (fn.startswith('.env') or fn.endswith('.env')):
            continue
        path = os.path.join(root, fn)
        try:
            for line in open(path, errors='replace'):
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                k = line.split('=', 1)[0].strip()
                if re.search(r'PASS|SECRET|TOKEN|KEY|DSN|JWT|STRIPE|CRYPTO|WASABI|MONGO|AUTH', k, re.I):
                    by_key[k].add(path)
        except OSError:
            pass
for k in sorted(by_key):
    print(f"  {k}: {', '.join(sorted(by_key[k]))}")
PY

echo ""
echo "################################################################"
echo "# DONE — $REPORT"
echo "################################################################"
