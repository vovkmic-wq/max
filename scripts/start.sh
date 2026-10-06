#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec .venv/bin/max-agent serve --port "${PORT:-8080}"
