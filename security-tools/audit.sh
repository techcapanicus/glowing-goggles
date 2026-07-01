#!/usr/bin/env bash
#
# audit.sh -- read-only security/hardening audit for a Debian/Ubuntu host.
#
# For use ONLY against systems you own or are explicitly authorized to
# assess. Installs a handful of well-known, read-only security auditing
# tools (nmap, lynis, rkhunter, chkrootkit) if missing, then runs them and
# writes timestamped reports plus a plaintext summary.
#
# This script does NOT modify firewall rules, SSH config, running services,
# or anything else on the host -- it only installs the audit tools
# themselves and then reads/scans. See --with-fail2ban below for the one
# opt-in exception (installing a protective service, off by default).
#
# Usage:
#   sudo ./audit.sh [--quick] [--skip-install] [--with-fail2ban] [--output-dir DIR]
#
#   --quick            Faster lynis run (skips some slower plugin checks).
#   --skip-install     Don't apt-install anything; only run tools already present.
#   --with-fail2ban    Additionally install+enable fail2ban's default sshd jail.
#                       This is the one step that changes running state (adds
#                       an active protection service). Off by default.
#   --output-dir DIR   Where to write reports (default: ~/security-reports/<timestamp>).

set -uo pipefail

QUICK=false
SKIP_INSTALL=false
WITH_FAIL2BAN=false
OUTPUT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --quick) QUICK=true ;;
    --skip-install) SKIP_INSTALL=true ;;
    --with-fail2ban) WITH_FAIL2BAN=true ;;
    --output-dir) OUTPUT_DIR="$2"; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^#//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root (sudo ./audit.sh ...) -- several checks need elevated privileges." >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
OUTPUT_DIR="${OUTPUT_DIR:-$HOME/security-reports/$TS}"
mkdir -p "$OUTPUT_DIR"
SUMMARY="$OUTPUT_DIR/summary.txt"

log() { echo "[audit] $*" | tee -a "$SUMMARY"; }

log "Security audit started $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname) ($(hostname -I 2>/dev/null | awk '{print $1}'))"
log "Reports will be written to: $OUTPUT_DIR"
echo >> "$SUMMARY"

# --- Install tools (idempotent) --------------------------------------------
if [ "$SKIP_INSTALL" = false ]; then
  log "Installing/updating audit tools (nmap, lynis, rkhunter, chkrootkit)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq nmap lynis rkhunter chkrootkit >/dev/null
  if [ "$WITH_FAIL2BAN" = true ]; then
    log "Installing fail2ban (opt-in) with its default sshd jail enabled..."
    apt-get install -y -qq fail2ban >/dev/null
    if [ ! -f /etc/fail2ban/jail.local ]; then
      cat > /etc/fail2ban/jail.local <<'EOF'
[sshd]
enabled = true
EOF
    fi
    systemctl enable --now fail2ban >/dev/null 2>&1 || true
    log "fail2ban status: $(systemctl is-active fail2ban 2>/dev/null || echo unknown)"
  fi
else
  log "Skipping package installation (--skip-install)."
fi
echo >> "$SUMMARY"

# --- 1. Listening services --------------------------------------------------
log "== Listening TCP/UDP services (ss -tulpn) =="
ss -tulpn > "$OUTPUT_DIR/listening-services.txt" 2>&1
tee -a "$SUMMARY" < "$OUTPUT_DIR/listening-services.txt" >/dev/null
cat "$OUTPUT_DIR/listening-services.txt" >> "$SUMMARY"
echo >> "$SUMMARY"

# --- 2. nmap self-scan ------------------------------------------------------
if command -v nmap >/dev/null 2>&1; then
  log "== nmap scan of localhost (top 1000 ports + version detection) =="
  nmap -sT -sV -Pn localhost > "$OUTPUT_DIR/nmap-localhost.txt" 2>&1
  echo "(full output: $OUTPUT_DIR/nmap-localhost.txt)" >> "$SUMMARY"
  grep -E "^[0-9]+/(tcp|udp)" "$OUTPUT_DIR/nmap-localhost.txt" >> "$SUMMARY" || true
else
  log "nmap not available, skipping (use without --skip-install to auto-install)."
fi
echo >> "$SUMMARY"

# --- 3. SSH hardening review -------------------------------------------------
log "== SSH server configuration review =="
{
  echo "PermitRootLogin:        $(sshd -T 2>/dev/null | awk '/^permitrootlogin/{print $2}')"
  echo "PasswordAuthentication: $(sshd -T 2>/dev/null | awk '/^passwordauthentication/{print $2}')"
  echo "PermitEmptyPasswords:   $(sshd -T 2>/dev/null | awk '/^permitemptypasswords/{print $2}')"
  echo "X11Forwarding:          $(sshd -T 2>/dev/null | awk '/^x11forwarding/{print $2}')"
  echo "MaxAuthTries:           $(sshd -T 2>/dev/null | awk '/^maxauthtries/{print $2}')"
  echo "Port:                   $(sshd -T 2>/dev/null | awk '/^port/{print $2}')"
} | tee "$OUTPUT_DIR/ssh-config-review.txt" >> "$SUMMARY"
echo >> "$SUMMARY"

# --- 4. Pending OS updates ---------------------------------------------------
log "== Pending package updates =="
apt list --upgradable 2>/dev/null | tail -n +2 > "$OUTPUT_DIR/pending-updates.txt"
UPDATE_COUNT=$(wc -l < "$OUTPUT_DIR/pending-updates.txt" | tr -d ' ')
echo "$UPDATE_COUNT package(s) have pending updates (see $OUTPUT_DIR/pending-updates.txt)" >> "$SUMMARY"
echo >> "$SUMMARY"

# --- 5. Firewall status -------------------------------------------------------
log "== Firewall status =="
if command -v ufw >/dev/null 2>&1; then
  ufw status verbose > "$OUTPUT_DIR/firewall-status.txt" 2>&1
else
  { iptables -L -n -v 2>&1; echo "---"; ip6tables -L -n -v 2>&1; } > "$OUTPUT_DIR/firewall-status.txt"
fi
cat "$OUTPUT_DIR/firewall-status.txt" >> "$SUMMARY"
echo >> "$SUMMARY"

# --- 6. rkhunter (rootkit check) ---------------------------------------------
if command -v rkhunter >/dev/null 2>&1; then
  log "== rkhunter rootkit check (this can take a minute) =="
  rkhunter --update --nocolors >/dev/null 2>&1 || true
  rkhunter --check --skip-keypress --nocolors --report-warnings-only \
    > "$OUTPUT_DIR/rkhunter.txt" 2>&1
  WARN_COUNT=$(grep -c "Warning" "$OUTPUT_DIR/rkhunter.txt" 2>/dev/null || echo 0)
  echo "rkhunter finished: $WARN_COUNT warning(s) (full output: $OUTPUT_DIR/rkhunter.txt)" >> "$SUMMARY"
else
  log "rkhunter not available, skipping."
fi
echo >> "$SUMMARY"

# --- 7. chkrootkit (rootkit check, complementary to rkhunter) ----------------
if command -v chkrootkit >/dev/null 2>&1; then
  log "== chkrootkit rootkit check =="
  chkrootkit > "$OUTPUT_DIR/chkrootkit.txt" 2>&1
  INFECTED_COUNT=$(grep -ci "INFECTED" "$OUTPUT_DIR/chkrootkit.txt" 2>/dev/null || echo 0)
  echo "chkrootkit finished: $INFECTED_COUNT possible finding(s) (full output: $OUTPUT_DIR/chkrootkit.txt)" >> "$SUMMARY"
else
  log "chkrootkit not available, skipping."
fi
echo >> "$SUMMARY"

# --- 8. lynis full hardening audit -------------------------------------------
if command -v lynis >/dev/null 2>&1; then
  log "== lynis system hardening audit (this can take a few minutes) =="
  LYNIS_ARGS="--no-colors --quiet"
  if [ "$QUICK" = true ]; then LYNIS_ARGS="$LYNIS_ARGS --quick"; fi
  lynis audit system $LYNIS_ARGS --report-file "$OUTPUT_DIR/lynis-report.dat" \
    > "$OUTPUT_DIR/lynis-output.txt" 2>&1
  HARDENING_INDEX=$(grep "hardening_index=" "$OUTPUT_DIR/lynis-report.dat" 2>/dev/null | cut -d= -f2)
  WARNINGS=$(grep -c "^warning\[\]" "$OUTPUT_DIR/lynis-report.dat" 2>/dev/null || echo 0)
  SUGGESTIONS=$(grep -c "^suggestion\[\]" "$OUTPUT_DIR/lynis-report.dat" 2>/dev/null || echo 0)
  echo "lynis hardening index: ${HARDENING_INDEX:-unknown}/100 -- $WARNINGS warning(s), $SUGGESTIONS suggestion(s)" >> "$SUMMARY"
  echo "(full report: $OUTPUT_DIR/lynis-output.txt, machine-readable: $OUTPUT_DIR/lynis-report.dat)" >> "$SUMMARY"
else
  log "lynis not available, skipping."
fi
echo >> "$SUMMARY"

log "Audit complete. Full reports in: $OUTPUT_DIR"
log "Summary: $SUMMARY"
