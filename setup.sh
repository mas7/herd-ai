#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up Herd AI..."

# Clone Mission Control if not already present
if [ ! -d "mission-control" ]; then
  echo "==> Cloning Mission Control..."
  git clone --depth 1 https://github.com/mas7/mission-control.git mission-control
else
  echo "==> Mission Control already cloned — skipping"
fi

# Copy .env if not present
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example — fill in your API keys"
fi

echo ""
echo "==> Setup complete. Run: docker compose up"
echo ""
echo "  Dashboards:"
echo "    Mission Control  http://localhost:3010"
echo "    Arize Phoenix    http://localhost:6006"
echo "    Herd API         http://localhost:8000/docs"
