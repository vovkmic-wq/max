#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -n "${PORT:-}" ]; then
    exec .venv/bin/max-agent serve --port "$PORT"
else
    exec .venv/bin/max-agent serve
fi
