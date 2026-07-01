# security-tools

A read-only security/hardening audit script for hosts you own or are
explicitly authorized to assess. **Do not point this at systems you don't
own or don't have written authorization to test.**

## What it does

`audit.sh` installs (if missing) and runs a handful of standard, well-known
security auditing tools against the local host, then writes timestamped
reports and a plaintext summary:

| Tool | Purpose |
| --- | --- |
| `ss -tulpn` | What's actually listening on the network, and which process owns it |
| `nmap` | Self-scan of localhost (top 1000 ports + service/version detection) |
| `sshd -T` | Reviews the effective SSH server config (root login, password auth, etc.) |
| `apt list --upgradable` | Pending OS/package security updates |
| `ufw` / `iptables` | Current firewall rules |
| `rkhunter` | Rootkit/backdoor scanner |
| `chkrootkit` | A second, independent rootkit scanner (cross-checks `rkhunter`) |
| `lynis` | Comprehensive system hardening audit with a 0-100 score and suggestions |

All of the above are **read-only** -- they inspect and report, they don't
change firewall rules, SSH config, or running services. The only exception
is the opt-in `--with-fail2ban` flag (see below), which installs and starts
`fail2ban`'s default SSH brute-force protection jail -- an active change,
off by default.

## Usage

```bash
# Copy the script to the target host, e.g.:
scp security-tools/audit.sh user@host:~/
ssh user@host

sudo ./audit.sh                    # full audit, installs tools if missing
sudo ./audit.sh --quick            # faster lynis pass
sudo ./audit.sh --skip-install     # only use tools already installed
sudo ./audit.sh --with-fail2ban    # also enable fail2ban's sshd jail
sudo ./audit.sh --output-dir /tmp/report
```

Reports land in `~/security-reports/<timestamp>/` by default: individual
tool output files plus a `summary.txt` with the highlights (hardening
score, warning counts, pending updates, listening ports, etc.).

## Running it via the `ssh-terminal` webapp

If you're using the `ssh-terminal/` app in this repo, you can run this
directly in the browser terminal once connected -- either paste the script
contents into a file with a heredoc, or fetch it from this repo (adjust the
branch as needed):

```bash
curl -fsSL -o audit.sh \
  https://raw.githubusercontent.com/techcapanicus/glowing-goggles/main/security-tools/audit.sh
chmod +x audit.sh
sudo ./audit.sh
```

Review the script before running it, especially if you're fetching over
`curl | bash` style patterns elsewhere -- this repo's copy is safe to read
directly on GitHub first.

## Re-running periodically

For infrastructure you manage long-term, consider running this on a cron
schedule (e.g. weekly) and diffing summaries over time, or wiring it into
the existing `provision_ssh.py` / Semaphore automation in this repo so
audits run consistently across your fleet rather than ad hoc.
