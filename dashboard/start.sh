#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f dashboard/web/dist/index.html ]; then
  echo "Dashboard build missing. Run: bash dashboard/setup.sh" >&2
  exit 1
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Dashboard dependencies missing. Run: bash dashboard/setup.sh" >&2
  exit 1
fi
echo "AutoScheduler review dashboard: http://127.0.0.1:${PORT:-8000}"
exec .venv/bin/python -m uvicorn dashboard.app:app --host 127.0.0.1 --port "${PORT:-8000}" --no-access-log
