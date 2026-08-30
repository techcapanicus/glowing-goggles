#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPORT_PATH="$ROOT/ringcx-login/"

cat <<EOF
SET Credential Harvester — RingCX test page
===========================================

SET is installed at: $(command -v setoolkit || echo 'not found')

Import folder (use this path in SET):
  $IMPORT_PATH

Interactive SET menu path:
  1) Social-Engineering Attacks
  2) Website Attack Vectors
  3) Credential Harvester Attack Method
  3) Import your own site
  Path: $IMPORT_PATH
  Choice: 1 (copy just index.html)

Launch SET now? This requires sudo and is interactive.
EOF

read -r -p "Start sudo setoolkit? [y/N] " answer
if [[ "${answer,,}" == "y" ]]; then
  exec sudo setoolkit
fi
