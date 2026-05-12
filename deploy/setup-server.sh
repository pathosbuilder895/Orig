#!/bin/bash
# ──────────────────────────────────────────────────────────────────
# Server setup script for Original API
#
# Target: Ubuntu 22.04 LTS on DigitalOcean / AWS Lightsail
# Run as root on a fresh server.
#
# What this does:
#   1. Install Docker and Docker Compose
#   2. Install nginx and Certbot
#   3. Create application directory structure
#   4. Print next steps
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

DOMAIN="${1:?Usage: ./setup-server.sh yourdomain.com}"
APP_DIR="/opt/original"

echo "=== Original Server Setup ==="
echo "Domain: ${DOMAIN}"
echo ""

# ── 1. System updates ────────────────────────────────────────────
echo "[1/5] Updating system packages..."
apt-get update && apt-get upgrade -y

# ── 2. Docker ────────────────────────────────────────────────────
echo "[2/5] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi
docker --version

# ── 3. nginx + Certbot ──────────────────────────────────────────
echo "[3/5] Installing nginx and Certbot..."
apt-get install -y nginx certbot python3-certbot-nginx

# ── 4. Application directory ─────────────────────────────────────
echo "[4/5] Creating application directory..."
mkdir -p "${APP_DIR}"/{backups,frontend}

# ── 5. Firewall ──────────────────────────────────────────────────
echo "[5/5] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy your project files to ${APP_DIR}/"
echo "     scp -r ./* root@${DOMAIN}:${APP_DIR}/"
echo ""
echo "  2. Create your .env file:"
echo "     cp ${APP_DIR}/.env.example ${APP_DIR}/.env"
echo "     nano ${APP_DIR}/.env   # Fill in SECRET_KEY and passwords"
echo ""
echo "  3. Set up nginx:"
echo "     cp ${APP_DIR}/deploy/nginx.conf /etc/nginx/sites-available/original"
echo "     sed -i 's/yourdomain.com/${DOMAIN}/g' /etc/nginx/sites-available/original"
echo "     ln -sf /etc/nginx/sites-available/original /etc/nginx/sites-enabled/"
echo "     rm -f /etc/nginx/sites-enabled/default"
echo "     nginx -t && systemctl reload nginx"
echo ""
echo "  4. Get SSL certificate:"
echo "     certbot --nginx -d ${DOMAIN}"
echo ""
echo "  5. Start the application:"
echo "     cd ${APP_DIR} && docker compose up -d"
echo ""
echo "  6. Create admin user:"
echo "     docker compose exec api python -m original.cli create-admin"
echo ""
echo "  7. Set up daily backups:"
echo "     chmod +x ${APP_DIR}/deploy/backup.sh"
echo "     echo '0 3 * * * COMPOSE_DIR=${APP_DIR} ${APP_DIR}/deploy/backup.sh >> /var/log/original-backup.log 2>&1' | crontab -"
echo "     (See ${APP_DIR}/deploy/DEPLOY.md for the full runbook.)"
echo ""
echo "  8. Set up UptimeRobot (free):"
echo "     Monitor https://${DOMAIN}/health every 5 minutes"
