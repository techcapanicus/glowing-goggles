# glowing-goggles

Tooling for the **My Country Mobile Semaphore UI** (`https://cicd-ucaas.mycountrymobile.com/`).

It contains two things:

1. **MyCountry Semaphore dashboard** — a Vue 3 + Vuetify single-page web app
   that connects to the Semaphore REST API with a bearer token and lets you
   browse projects, task templates, and recent task history (and run templates).
2. **`provision_ssh.py`** — a single-file script that drives the Semaphore REST
   API to provision SSH key access to a list of target servers.

## Web app

```bash
npm install
npm run dev      # http://localhost:5173  (Vite proxies /api -> Semaphore)
npm run lint
npm run build
```

Open the app, paste a Semaphore API token in the Connect screen (stored in
`localStorage`), and the dashboard loads. The dev server proxies `/api` to the
Semaphore instance to avoid browser CORS issues.

## SSH provisioning script

`provision_ssh.py` uses only the Python standard library (no dependencies) and
needs `ssh-keygen` and `git` on `PATH`.

```bash
# Configure via flags or environment (.env is auto-loaded; see .env.example)
python3 provision_ssh.py \
  --url https://cicd-ucaas.mycountrymobile.com \
  --token "$SEMAPHORE_TOKEN" \
  --project-id 6 \
  --ssh-key-id 303 \
  --target-hosts 64.23.139.247 \
  --bootstrap-user root --target-user root \
  --repo-git-url https://github.com/techcapanicus/glowing-goggles.git \
  --repo-branch main --playbook ansible/provision_ssh.yml \
  --dry-run            # Ansible --check mode: makes no changes
```

The script generates (or accepts) an ed25519 keypair, stores it in the Key
Store, reuses/creates a project, builds a static inventory, wires up a
repository + environment (extra vars) + task template, then runs the task and
polls to completion while streaming the log. The idempotent playbook is embedded
in the script and also committed at [`ansible/provision_ssh.yml`](ansible/provision_ssh.yml)
for repo-based runs. Run `python3 provision_ssh.py --help` for all options.

> The Semaphore server must be able to reach the playbook repository (a public
> Git URL, or a local path that exists on the server). Omit `--dry-run` only
> when you intend to actually modify `authorized_keys` on the target hosts.

### Dev environment (Semaphore UI)

For the dashboard dev workflow, use the helper script. It reuses project `MCM`
(id `6`), the `deployment` Key Store key (id `303`) for bootstrap SSH, and saves
the generated keypair under `keys/semaphore-ui-dev/` (gitignored):

```bash
cp .env.example .env
# Set SEMAPHORE_TOKEN and TARGET_HOSTS (your dev server IP) in .env
./scripts/provision-dev-ssh.sh          # actually provisions root authorized_keys
# ./scripts/provision-dev-ssh.sh --dry-run   # Ansible --check only
```

Connect with the saved private key:

```bash
ssh -i keys/semaphore-ui-dev/id_ed25519 root@<dev-server>
```
