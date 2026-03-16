#!/bin/bash
# ============================================================
# start.sh — Start the Meta Ads AI development stack
# Automatically finds free ports if defaults are occupied.
# ============================================================
set -e

cd "$(dirname "$0")"

# ── Helpers ────────────────────────────────────────────────────
find_free_port() {
  local preferred=$1
  if ! lsof -iTCP:"$preferred" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "$preferred"
    return
  fi
  # Find a random free port
  local port
  port=$(python3 -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()")
  echo "$port"
}

# ── Resolve ports ──────────────────────────────────────────────
PORT_FRONTEND=$(find_free_port 3000)
PORT_BACKEND=$(find_free_port 8000)
PORT_MCP=$(find_free_port 8080)
PORT_SUPABASE=$(find_free_port 54321)
PORT_DB=$(find_free_port 5432)

# Export for docker-compose
export PORT_FRONTEND PORT_BACKEND PORT_MCP PORT_SUPABASE PORT_DB

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║       Meta Ads AI — Starting Stack           ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  Frontend     →  http://localhost:$PORT_FRONTEND       ║"
echo "  ║  Backend API  →  http://localhost:$PORT_BACKEND       ║"
echo "  ║  Supabase     →  http://localhost:$PORT_SUPABASE      ║"
echo "  ║  PostgreSQL   →  localhost:$PORT_DB              ║"
echo "  ║  MCP Server   →  http://localhost:$PORT_MCP       ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# Show warnings for non-default ports
if [ "$PORT_FRONTEND" != "3000" ]; then
  echo "  ⚠  Port 3000 was busy — frontend on :$PORT_FRONTEND"
fi
if [ "$PORT_BACKEND" != "8000" ]; then
  echo "  ⚠  Port 8000 was busy — backend on :$PORT_BACKEND"
fi
if [ "$PORT_SUPABASE" != "54321" ]; then
  echo "  ⚠  Port 54321 was busy — supabase gateway on :$PORT_SUPABASE"
fi
if [ "$PORT_DB" != "5432" ]; then
  echo "  ⚠  Port 5432 was busy — postgres on :$PORT_DB"
fi
if [ "$PORT_MCP" != "8080" ]; then
  echo "  ⚠  Port 8080 was busy — mcp server on :$PORT_MCP"
fi
echo ""

# ── Launch ─────────────────────────────────────────────────────
docker compose up --build -d "$@"

echo ""
echo "  ✅ Stack is up! Open http://localhost:$PORT_FRONTEND"
echo ""
echo "  Demo login:"
echo "    Email:    demo@metaads.local"
echo "    Password: MetaAdsLocal_2026xQ"
echo ""
