# SET Phishing Test — RingCX Login Page

Authorized security-awareness testing assets for use with the [Social-Engineer Toolkit (SET)](https://github.com/trustedsec/social-engineer-toolkit).

**Only use this in environments where you have explicit permission to run phishing simulations.**

## What is included

| Path | Purpose |
|------|---------|
| `ringcx-login/index.html` | Static RingCX-style login page with a standard HTML POST form (required by SET's credential harvester) |
| `start-test-server.sh` | Preview the page locally without SET |
| `run-set-harvester.sh` | Helper that prints the exact SET menu path and import folder |

## SET installation

SET is installed on this VM at `/opt/setoolkit` and available as:

```bash
sudo setoolkit
```

## Preview the login page locally

```bash
./set-phishing/start-test-server.sh
```

Open `http://localhost:8080/` in a browser.

## Run with SET credential harvester

1. Start SET as root:

   ```bash
   sudo setoolkit
   ```

2. Choose the menu path:

   ```
   1) Social-Engineering Attacks
   2) Website Attack Vectors
   3) Credential Harvester Attack Method
   2) Site Cloner
   ```

3. When prompted for the site to clone, enter:

   ```
   https://ringcx.ringcentral.com
   ```

   SET will fail to clone the React SPA correctly. Instead, use **Import your own site**:

   ```
   1) Social-Engineering Attacks
   2) Website Attack Vectors
   3) Credential Harvester Attack Method
   3) Import your own site
   ```

4. When asked for the path, enter the absolute path to this folder (must end with `/`):

   ```
   /workspace/set-phishing/ringcx-login/
   ```

5. Choose **2) Copy the entire folder** if you add static assets later; for now **1) Copy just the index.html** is enough.

6. Enter your machine's IP for POST-back when prompted. SET rewrites the form `action` to capture submitted credentials.

7. Harvested credentials are written to:

   ```
   ~/.set/reports/
   ```

   (or `/root/.set/reports/` when running with `sudo`).

## Why a custom page?

The real RingCX login (`ringcx.ringcentral.com`) is a JavaScript SPA without a simple HTML form. SET's site cloner cannot extract POST parameters from SPAs, so this static page reproduces the RingCX look from the provided source while exposing `email` and `password` fields SET can harvest.

## Form fields captured

- `email` — username / email
- `password` — password

After capture, SET redirects the victim to the real RingCX URL configured in the form action.
