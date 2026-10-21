#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r dashboard/requirements.txt
npm --prefix dashboard/web ci --prefer-offline --no-audit --no-fund
npm --prefix dashboard/web run build
echo "Setup complete. Run: bash dashboard/start.sh"
