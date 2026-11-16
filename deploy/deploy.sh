#!/usr/bin/env bash
# FinGuard AI - deploy or update on a Linux server (Ubuntu 22.04/24.04 with Docker installed).
#
#   ./deploy/deploy.sh --domain finguard.example.com --init    # first deploy: secrets + data + models
#   ./deploy/deploy.sh                                          # update after `git pull`
#
# --domain     public hostname; tip: <server-ip>.sslip.io works without buying a domain
# --init       build the synthetic dataset, models, graph, knowledge base and demo users (~15 min)
# --customers  dataset size for --init (default 800 - fits a 4-8 GB server)
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN_ARG="" INIT=0 CUSTOMERS=800
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN_ARG="$2"; shift 2 ;;
    --init) INIT=1; shift ;;
    --customers) CUSTOMERS="$2"; shift 2 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done

command -v docker >/dev/null || { echo "Docker is not installed - see docs/DEPLOYMENT.md step 2"; exit 1; }
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app"

# ---- 1. production .env (created once, never committed) ------------------------------------
if [[ ! -f .env ]]; then
  [[ -n "$DOMAIN_ARG" ]] || { echo "First run needs --domain"; exit 1; }
  rand() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
  DEMO_PW="Fg-$(rand 14)9"
  cp .env.example .env
  sed -i \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=$(rand 64)|" \
    -e "s|^DEMO_USER_PASSWORD=.*|DEMO_USER_PASSWORD=${DEMO_PW}|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 32)|" \
    -e "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(rand 20)|" \
    .env
  # the container connects to postgres by service name; keep DATABASE_URL in sync with the new password
  PG_PW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://finguard:${PG_PW}@localhost:55432/finguard|" .env
  printf '\n# --- production ---\nENVIRONMENT=production\nDOMAIN=%s\n' "$DOMAIN_ARG" >> .env
  chmod 600 .env
  echo "Created .env with random secrets. Demo password for all six accounts: ${DEMO_PW}"
  echo "(stored as DEMO_USER_PASSWORD in .env - add ANTHROPIC_API_KEY or OPENAI_API_KEY there for LLM features)"
elif [[ -n "$DOMAIN_ARG" ]]; then
  grep -q '^DOMAIN=' .env && sed -i "s|^DOMAIN=.*|DOMAIN=${DOMAIN_ARG}|" .env || echo "DOMAIN=${DOMAIN_ARG}" >> .env
fi

# ---- 2. build and start -------------------------------------------------------------------
$COMPOSE up -d --build
echo -n "Waiting for the API"
for _ in $(seq 1 60); do
  if $COMPOSE exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null; then
    echo " - up"; break
  fi
  echo -n "."; sleep 5
done

# ---- 3. first deploy: data, models, graph, knowledge base, demo users -----------------------
if [[ $INIT -eq 1 ]]; then
  $COMPOSE exec -T backend python -m app.cli init-db --drop
  $COMPOSE exec -T backend python -m app.cli generate --customers "$CUSTOMERS" --days 180
  for step in ingest train score graph risk alerts rag-build seed-users; do
    echo "== $step"; $COMPOSE exec -T backend python -m app.cli "$step"
  done
else
  $COMPOSE exec -T backend python -m app.cli init-db      # adds any new tables, keeps data
fi

DOMAIN_NOW=$(grep '^DOMAIN=' .env | cut -d= -f2)
echo
echo "FinGuard AI is live at https://${DOMAIN_NOW}  (first HTTPS certificate can take ~1 minute)"
echo "Sign in as fraud_analyst / investigation_manager / ... with DEMO_USER_PASSWORD from .env"
