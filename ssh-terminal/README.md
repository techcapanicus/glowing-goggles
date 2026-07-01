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
