# Deploying FinGuard AI to a public server

Result: `https://<your-domain>` with automatic HTTPS, only ports 80/443 open, secrets generated on the server, and the same Docker images CI builds on every push.

```
Internet ──443──▶ Caddy (HTTPS, security headers) ──▶ frontend (nginx) ──/api──▶ backend (FastAPI + agents)
                                                                                   │
                                     private Docker network: postgres · redis · qdrant (no public ports)
```

## 1. Get a server (you do this - it needs your account)

Any Ubuntu 22.04/24.04 VM with **8 GB RAM, 2 vCPU, 40 GB disk** works (4 GB works with `--customers 500`).

| Provider | Roughly | Notes |
|---|---|---|
| Hetzner Cloud CX32 | ~€8/month | cheapest 8 GB option |
| DigitalOcean / AWS Lightsail 8 GB | ~$40-48/month | simple dashboards |
| Azure B2ms | ~$60/month | **free with Azure for Students credit** |
| Oracle Cloud Always Free (Ampere 4 vCPU / 24 GB) | €0 | free tier, ARM - all images used here support ARM |

Open inbound ports **22, 80, 443** only (firewall / security group).

**Domain:** use your own (point an `A` record at the server IP), or skip buying one and use `<server-ip>.sslip.io` (e.g. `203.0.113.10.sslip.io`) - it resolves to your IP and Caddy can still get a real certificate. A free DuckDNS name also works.

## 2. Install Docker on the server

```bash
ssh ubuntu@<server-ip>
```

```bash
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER && newgrp docker
```

(That is Docker's official install script.)

## 3. Deploy

```bash
git clone https://github.com/srinivasand04/finguard-ai.git && cd finguard-ai
```

```bash
./deploy/deploy.sh --domain <server-ip>.sslip.io --init
```

The script:

1. creates `.env` with **random** `JWT_SECRET`, Postgres password, Grafana password and demo password, sets `ENVIRONMENT=production` (it prints the demo password once; it stays in `.env`, mode 600);
2. builds and starts Postgres, Redis, Qdrant, API, frontend and Caddy;
3. builds the dataset (800 customers), models, graph, knowledge base and the six demo accounts (~15 min).

Open `https://<your-domain>` and sign in as `fraud_analyst`, `investigation_manager`, ... with that password.

### LLM features in production

A small cloud server cannot run a local LLM usefully. Add one key to `.env` and redeploy:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env && ./deploy/deploy.sh
```

Without a key everything still works: the compliance assistant quotes cited passages and investigation narratives use the verified template.

## 4. Update after new commits

```bash
git pull && ./deploy/deploy.sh
```

(Adds new tables if any; data is kept.)

## 5. Monitoring (private)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app --profile monitoring up -d
```

From your laptop, tunnel and open http://localhost:3000 (user `admin`, password `GRAFANA_ADMIN_PASSWORD` in the server's `.env`):

```bash
ssh -L 3000:127.0.0.1:3000 ubuntu@<server-ip>
```

## Production checklist

| Item | Status |
|---|---|
| HTTPS with automatic renewal (Caddy + Let's Encrypt) | ✅ |
| Security headers (HSTS, nosniff, frame deny) | ✅ |
| Only 80/443 public; DB, Redis, Qdrant, API, Grafana, Prometheus private | ✅ |
| `/metrics` not reachable from the internet | ✅ |
| Strong random secrets; API refuses to start with a weak `JWT_SECRET` | ✅ |
| Public demo password refused by `seed-users` in production | ✅ |
| Login brute-force protection (5 failures / 15 min per user+IP → HTTP 429) | ✅ |
| Containers restart after crashes / reboots | ✅ |
| Backups | ➖ add a nightly `pg_dump` (`docker compose exec -T postgres pg_dump -U finguard finguard > backup.sql`) |
| Tokens in HttpOnly cookies instead of sessionStorage | ➖ planned |
| Synthetic data only - never load real customer data into this demo | ⚠️ |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Browser shows a certificate error for a minute | Caddy is still obtaining the certificate - wait; check `docker compose ... logs caddy` |
| `ENVIRONMENT=production requires JWT_SECRET...` | `.env` has a weak secret - regenerate with `openssl rand -base64 48` |
| Build killed / very slow | Not enough RAM - use an 8 GB server or `--customers 500` |
| `rag-build` fails downloading models | The server needs outbound internet to huggingface.co |
