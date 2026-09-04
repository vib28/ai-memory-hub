#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: ./setup.sh /absolute/path/to/obsidian-vault"
  exit 1
fi

VAULT="$1"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
python -m memory_hub.cli --vault "$VAULT" init

echo
echo "Done."
echo "Vault: $VAULT"
echo "Activate with: source .venv/bin/activate"
