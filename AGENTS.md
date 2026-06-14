# AGENTS.md

## Cursor Cloud specific instructions

This repo holds two things that both talk to the My Country Mobile Semaphore UI
(`https://cicd-ucaas.mycountrymobile.com/`):

- A Vue 3 + Vuetify web dashboard (root: `index.html`, `src/`, `vite.config.js`).
- `provision_ssh.py`: a single-file, stdlib-only Semaphore REST API script
  (+ embedded/`ansible/provision_ssh.yml` playbook).

### Running / lint / build / test
- Standard commands live in `package.json` scripts and `README.md`. In short:
  `npm run dev` (Vite dev server, port 5173, bound to `0.0.0.0`), `npm run lint`
  (ESLint flat config), `npm run build`. There is no JS test suite.
- The Vite dev server proxies `/api` to the Semaphore instance
  (`vite.config.js`, `SEMAPHORE_URL` env, default is the cicd-ucaas URL). This
  keeps browser API calls same-origin and avoids CORS. Restart `npm run dev`
  after changing `vite.config.js` (proxy/`define` changes are not hot-reloaded).
- `provision_ssh.py` needs only Python 3, `ssh-keygen`, and `git` (all present
  in the base image). Verify with `python3 -m py_compile provision_ssh.py`.

### Non-obvious gotchas
- **Cloudflare bans default client user-agents.** The Semaphore instance sits
  behind Cloudflare, which returns `HTTP 403 / error 1010` ("browser signature
  banned") for `Python-urllib`, etc. `provision_ssh.py` works around this by
  sending a browser-like `User-Agent`; `curl`'s default UA is also allowed.
  Any new HTTP client hitting this host must set a browser-like UA.
- **The API token user is not an admin** (`can_create_project: false`). Project
  creation via `POST /api/projects` fails (HTTP 400/403). Reuse the existing
  `MCM` project (id `6`) via `--project-id`/`SEMAPHORE_PROJECT_ID`.
- **Playbooks must be reachable by the Semaphore server**, not by this VM. Use a
  public Git URL (this repo is public) or a path that exists on the Semaphore
  host (the instance already has a local repo at `/tmp/mycountrymobile-devops`).
  A locally-generated `file://` repo from this VM is NOT visible to the server.
- **`MCM` (id 6) is production infrastructure** (live SIP/web servers, real SSH
  keys). Run `provision_ssh.py --dry-run` (Ansible `--check`, no changes) unless
  you intend to actually modify `authorized_keys`. Reuse the existing `deployment`
  Key Store key (id `303`) via `--ssh-key-id` for connectivity to those hosts.

### Secrets
- The web app stores the token in `localStorage` under `semaphore.token`.
- `provision_ssh.py` reads `SEMAPHORE_URL`/`SEMAPHORE_TOKEN` from env or a
  `.env` file (auto-loaded). `.env` is gitignored — never commit it. See
  `.env.example`.
