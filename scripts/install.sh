#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/max-agent init
npm ci --ignore-scripts --no-audit --no-fund
npm rebuild @opencode/cli --foreground-scripts
