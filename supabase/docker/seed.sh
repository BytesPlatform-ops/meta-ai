#!/bin/sh
# ============================================================
# Seed a demo user into GoTrue for local development.
# Runs after all Supabase services are healthy.
# ============================================================
set -e

GOTRUE_URL="http://supabase-auth:9999"
ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyAgCiAgICAicm9sZSI6ICJhbm9uIiwKICAgICJpc3MiOiAic3VwYWJhc2UtZGVtbyIsCiAgICAiaWF0IjogMTY0MTc2OTIwMCwKICAgICJleHAiOiAxNzk5NTM1NjAwCn0.dc_X5iR_VP_qT0zsiyj_I_OZ2T9FtRU2BBNWN8Bu4GE"

echo "⏳ Waiting for GoTrue to be ready..."
until wget -q -O /dev/null "$GOTRUE_URL/health" 2>/dev/null; do
  sleep 2
done
echo "✅ GoTrue is ready"

# Check if user already exists by trying to sign in
STATUS=$(wget -q -O /dev/null --server-response \
  --header="Content-Type: application/json" \
  --header="apikey: $ANON_KEY" \
  --post-data='{"email":"demo@metaads.local","password":"MetaAdsLocal_2026xQ"}' \
  "$GOTRUE_URL/token?grant_type=password" 2>&1 | grep "HTTP/" | tail -1 | awk '{print $2}')

if [ "$STATUS" = "200" ]; then
  echo "ℹ️  Demo user already exists — skipping seed"
  exit 0
fi

echo "🌱 Creating demo user..."
wget -q -O /dev/null \
  --header="Content-Type: application/json" \
  --header="apikey: $ANON_KEY" \
  --post-data='{"email":"demo@metaads.local","password":"MetaAdsLocal_2026xQ","data":{"full_name":"Demo User"}}' \
  "$GOTRUE_URL/signup"

echo "🎉 Demo user seeded!"
echo "   Email:    demo@metaads.local"
echo "   Password: MetaAdsLocal_2026xQ"
