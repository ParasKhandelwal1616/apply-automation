#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="$root/data/pw-browsers"
mkdir -p data/pw-browsers
playwright install chromium

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — edit TELEGRAM_CHANNEL_TITLE if needed."
fi
if [[ ! -f config/profile.yaml ]]; then
  cp config/profile.example.yaml config/profile.yaml
  echo "Created config/profile.yaml — fill YOUR name, email, resume path, skills."
fi

echo
echo "Next:"
echo "  1. Edit config/profile.yaml"
echo "  2. source .venv/bin/activate"
echo "  3. PLAYWRIGHT_BROWSERS_PATH=\"\$PWD/data/pw-browsers\" PYTHONPATH=src python -m apply_bot open-channel"
echo "  4. PLAYWRIGHT_BROWSERS_PATH=\"\$PWD/data/pw-browsers\" PYTHONPATH=src python -m apply_bot apply-once --limit 40"
