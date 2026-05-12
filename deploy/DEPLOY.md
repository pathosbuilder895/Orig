# Original — production deployment runbook (Phase 2)

Single **Ubuntu 22.04** host (DigitalOcean, Lightsail, or similar): **Docker Compose** for `api` + `postgres` + `redis`, **system nginx** for TLS and static frontend, **Let’s Encrypt** for certificates, **cron** for daily DB backups, **UptimeRobot** (or similar) for `/health`.

## 1. Server bootstrap

On a fresh VM (as root):

```bash
# From your laptop — copy project and run setup (replace DOMAIN)
scp -r . root@YOUR_SERVER_IP:/opt/original
ssh root@YOUR_SERVER_IP
chmod +x /opt/original/deploy/setup-server.sh
/opt/original/deploy/setup-server.sh yourdomain.com
```

Installs Docker, nginx, Certbot, UFW, creates `/opt/original/{backups,frontend}`.

## 2. Environment

```bash
cd /opt/original
cp .env.example .env
# Set SECRET_KEY, POSTGRES_PASSWORD, _ALLOWED_ORIGINS_STR=https://yourdomain.com, ORIGINAL_BASE_URL=https://yourdomain.com
nano .env
```

`docker-compose.yml` is pinned with `name: original` so service containers are named predictably (e.g. `original-postgres-1`).

## 3. DNS

Point an **A record** for `yourdomain.com` (and `www` if needed) to the server’s public IP.

## 4. nginx + TLS

```bash
cp /opt/original/deploy/nginx.conf /etc/nginx/sites-available/original
sed -i 's/yourdomain.com/yourdomain.com/g' /etc/nginx/sites-available/original
ln -sf /etc/nginx/sites-available/original /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d yourdomain.com
```

- API is proxied at `location /api/` → `http://127.0.0.1:8000` (see [nginx.conf](nginx.conf)).
- Static site root: `/opt/original/frontend` for `location /`.

## 5. Start the stack

```bash
cd /opt/original
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
docker compose exec api python -m original.cli create-admin
```

## 6. Deploy the static frontend

From the repo, sync HTML/JS/CSS to the path nginx serves:

```bash
rsync -av --delete ./frontend/ /opt/original/frontend/
```

- [api-client.js](../frontend/api-client.js) resolves the API to **same-origin** when the site is served over `https://yourdomain.com`, so calls go to `/api/...` through nginx without CORS changes.
- Optional override: set `window.ORIGINAL_API_BASE` or `?api=` per [api-client.js](../frontend/api-client.js).

## 7. Daily PostgreSQL backups

[backup.sh](backup.sh) uses **`docker compose exec`** when `COMPOSE_DIR` is set (recommended on the same host as Compose):

```bash
chmod +x /opt/original/deploy/backup.sh
```

Crontab (3:00 daily):

```cron
0 3 * * * COMPOSE_DIR=/opt/original /opt/original/deploy/backup.sh >> /var/log/original-backup.log 2>&1
```

- Override: `S3_BUCKET=...` to upload to S3 (requires `aws` CLI configured).
- Legacy: `COMPOSE_DIR` unset and `DB_CONTAINER=original-postgres-1` uses `docker exec`.

## 8. Uptime / monitoring

- **UptimeRobot (free):** URL `https://yourdomain.com/health`, interval 5 minutes, expect HTTP 200 and JSON `{"status":"ok",...}`.
- **Metrics:** `/metrics` is meant to be restricted (see nginx `location /metrics`); scrape from inside the VPC or with SSH tunnel if needed.

## 9. Verify

```bash
curl -fsS https://yourdomain.com/health
curl -fsS -o /dev/null -w '%{http_code}\n' https://yourdomain.com/api/docs
```

## Rollback

```bash
cd /opt/original
docker compose -f docker-compose.yml pull   # if using a registry
docker compose -f docker-compose.yml up -d --build
```

Restore DB from a `.sql.gz` made by [backup.sh](backup.sh) using `pg_restore` or `gunzip` + `psql` as appropriate to your format.
