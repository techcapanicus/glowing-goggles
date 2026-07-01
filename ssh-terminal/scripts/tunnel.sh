#!/usr/bin/env bash
# Expose the locally running ssh-terminal server (see `npm start`) via a
# free Cloudflare "quick tunnel" — no account, no DNS, no inbound firewall
# rules needed. Prints a random https://*.trycloudflare.com URL.
#
# These quick tunnels have no uptime guarantee and are meant for temporary/
# personal use (see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/).
# For anything long-lived, create a named Cloudflare Tunnel instead.
set -euo pipefail

PORT="${PORT:-3001}"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.bin"
CLOUDFLARED="$BIN_DIR/cloudflared"

mkdir -p "$BIN_DIR"

if [ ! -x "$CLOUDFLARED" ]; then
  echo "Downloading cloudflared..." >&2
  arch="$(uname -m)"
  case "$arch" in
    x86_64) cf_arch="amd64" ;;
    aarch64|arm64) cf_arch="arm64" ;;
    *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
  esac
  curl -sL -o "$CLOUDFLARED" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$cf_arch"
  chmod +x "$CLOUDFLARED"
fi

echo "Tunneling http://localhost:$PORT -- watch below for your https://*.trycloudflare.com URL" >&2
exec "$CLOUDFLARED" tunnel --url "http://localhost:$PORT"
