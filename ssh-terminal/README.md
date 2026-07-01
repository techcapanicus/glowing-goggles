# ssh-terminal

A smooth, fast browser-based terminal that bridges to a single SSH target over
a WebSocket. Frontend is [xterm.js](https://xtermjs.org/) (with the WebGL
renderer when available); backend is a small Node/Express server that uses
[`ssh2`](https://github.com/mscdex/ssh2) to open a real interactive shell on
the target host and streams bytes both ways over `ws`.

```
Browser (xterm.js) <--WebSocket--> Node server (ssh2) <--SSH--> target host
```

## Setup

```bash
cd ssh-terminal
npm install
cp .env.example .env   # then edit .env with real values
npm start               # http://0.0.0.0:3001
```

Open `http://<host>:3001` in a browser. If `APP_PASSWORD` is set, you'll be
prompted for it before the server opens the SSH session; the SSH credentials
themselves are never sent to or entered in the browser — they live only in
the server's `.env`.

## Configuration (`.env`)

| Variable       | Default   | Description                                                                 |
| -------------- | --------- | ---------------------------------------------------------------------------- |
| `PORT`         | `3001`    | HTTP/WebSocket port for this webapp                                          |
| `HOST`         | `0.0.0.0` | Bind address                                                                  |
| `SSH_HOST`     | —         | Target host to SSH into                                                      |
| `SSH_PORT`     | `22`      | Target SSH port                                                              |
| `SSH_USER`     | —         | SSH username                                                                 |
| `SSH_PASSWORD` | —         | SSH password                                                                 |
| `APP_PASSWORD` | (empty)   | If set, browsers must enter this before a session is opened. Strongly recommended for anything reachable outside `localhost`. |

`.env` is gitignored — never commit real credentials. See `.env.example`.

## Exposing it publicly

By default the server just binds `HOST:PORT` (e.g. `0.0.0.0:3001`), which is
only reachable on your local network/machine. To get a public HTTPS URL
without touching any firewall/router config, run a free Cloudflare "quick
tunnel" alongside `npm start`:

```bash
npm run tunnel
```

This downloads a local `cloudflared` binary into `ssh-terminal/.bin/`
(gitignored) and prints a random `https://<random-words>.trycloudflare.com`
URL that proxies straight through to your local server. It's an
outbound-only connection — no inbound ports need to be opened anywhere.

Quick tunnels are meant for temporary/personal use: no uptime guarantee, and
the URL changes every time you restart the tunnel. For anything long-lived,
set up a [named Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
(or another reverse proxy with a real TLS cert) instead, and keep
`APP_PASSWORD` set — a quick tunnel makes this server (and therefore the SSH
session it opens) reachable by anyone with the URL until you stop it.

## Deploying to Azure Container Apps

If you'd rather have this always running on a stable, HTTPS-by-default URL
than run it in this sandbox/behind a tunnel, `Dockerfile` in this directory
lets you deploy it to [Azure Container Apps](https://azure.microsoft.com/products/container-apps)
entirely from Azure Cloud Shell (`https://shell.azure.com`) — no local Docker,
and no need to hand Azure credentials to anything outside your own session.

```bash
# Avoid bash history-expansion mangling passwords containing "!"
set +H

az account set --subscription "<your-subscription-id>"
RESOURCE_GROUP="TERMINALAPP"     # reuse an existing group, or create one
LOCATION="eastus"                # use a region where you have compute quota
ACR_NAME="sshterminalacr$RANDOM" # must be globally unique, alnum only
ENV_NAME="ssh-terminal-env"
APP_NAME="ssh-terminal"

az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az extension add --name containerapp --upgrade --yes

az acr create --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" --sku Basic --admin-enabled true

git clone https://github.com/techcapanicus/glowing-goggles.git
cd glowing-goggles/ssh-terminal

# Builds the image in the cloud via ACR Tasks -- no local Docker needed
az acr build --registry "$ACR_NAME" --image ssh-terminal:latest .

az containerapp env create --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" --location "$LOCATION"

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USER=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASS=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

az containerapp create \
  --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_LOGIN_SERVER/ssh-terminal:latest" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
  --target-port 8080 --ingress external \
  --env-vars \
    SSH_HOST=172.174.232.34 SSH_PORT=22 SSH_USER=adminuser \
    SSH_PASSWORD='<your-ssh-password>' \
    APP_PASSWORD='<pick-a-strong-app-password>' \
    PORT=8080 HOST=0.0.0.0

az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv
```

The last command prints the app's `*.azurecontainerapps.io` FQDN — the app
is reachable at `https://<that-fqdn>` with a free, automatically-managed TLS
certificate. WebSockets work over Container Apps ingress with no extra
config. Redeploy a new image later with:

```bash
az acr build --registry "$ACR_NAME" --image ssh-terminal:latest .
az containerapp update --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --image "$ACR_LOGIN_SERVER/ssh-terminal:latest"
```

> Azure tracks App Service (`Microsoft.Web`) and regular VM (`Microsoft.Compute`)
> compute against separate quota pools from Container Apps/Container Instances.
> If `az appservice plan create` fails with `Current Limit (Total VMs): 0`,
> that's an App-Service-specific quota — it doesn't mean Container Apps or ACI
> are blocked too (and vice versa). Request quota increases (portal → "Quotas")
> for whichever specific service you end up using.

## Notes

- Each browser tab that connects opens its **own** SSH connection/shell to
  the target host (one WebSocket == one `ssh2` `Client` + PTY). Closing the
  tab or clicking "Reconnect" tears down and re-establishes the session.
- Terminal resizes are forwarded to the remote PTY (`stream.setWindow`), so
  full-screen programs (`top`, `vim`, `less`, …) resize correctly.
- This uses password auth because that's what was provided for the target
  host. Password auth over SSH is weaker than key-based auth — consider
  switching `SSH_PASSWORD` for a private key (see `ssh2`'s `privateKey`
  connect option) and rotating the password once it's no longer needed here.
- This app is a thin, single-target bridge, not a general-purpose SSH client:
  the target host is fixed via server-side env vars, not user input, so it
  can't be pointed at arbitrary hosts from the browser.
