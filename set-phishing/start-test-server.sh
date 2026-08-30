#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8080}"

echo "Serving RingCX test login page from: $ROOT/ringcx-login"
echo "Open: http://localhost:${PORT}/"
echo "Press Ctrl+C to stop."

cd "$ROOT/ringcx-login"
python3 -m http.server "$PORT" --bind 0.0.0.0
