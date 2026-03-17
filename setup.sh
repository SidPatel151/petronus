#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║         AutoBIM Setup Script         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Backend ────────────────────────────────────────────────────────────────
echo "▶ Setting up Python backend..."
cd backend

if [ ! -d "venv" ]; then
  python3 -m venv venv
  echo "  ✓ Created virtualenv"
fi

source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "  ✓ Python deps installed"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "  ✓ Created .env from .env.example"
fi

deactivate
cd ..

# ── Frontend ───────────────────────────────────────────────────────────────
echo ""
echo "▶ Setting up Next.js frontend..."
cd frontend

if command -v npm &> /dev/null; then
  npm install --legacy-peer-deps
  echo "  ✓ Node deps installed"
else
  echo "  ✗ npm not found — install Node.js 18+ first"
  exit 1
fi

if [ ! -f ".env.local" ]; then
  echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
  echo "  ✓ Created .env.local"
fi

cd ..

echo ""
echo "╔══════════════════════════════════════╗"
echo "║            Setup Complete!           ║"
echo "╠══════════════════════════════════════╣"
echo "║                                      ║"
echo "║  1. Start services:                  ║"
echo "║     docker-compose up -d             ║"
echo "║                                      ║"
echo "║  2. Start backend:                   ║"
echo "║     ./run_backend.sh                 ║"
echo "║                                      ║"
echo "║  3. Start frontend:                  ║"
echo "║     ./run_frontend.sh                ║"
echo "║                                      ║"
echo "║  Open: http://localhost:3000         ║"
echo "║  API:  http://localhost:8000/docs    ║"
echo "╚══════════════════════════════════════╝"
