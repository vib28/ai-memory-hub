#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: ./setup.sh /absolute/path/to/obsidian-vault"
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv was not found on PATH. Install uv, then re-run this script."
  exit 1
fi

VAULT="$1"

uv sync
uv run python -m memory_hub.cli --vault "$VAULT" init

echo
echo "Done."
echo "Vault: $VAULT"
echo "Activate with: source .venv/bin/activate"
