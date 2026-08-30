#!/usr/bin/env bash
# Run this ON the server (e.g. an Oracle Cloud "Always Free" VM) as the
# ubuntu user, after cloning the repo to /home/ubuntu/whatsapp-correction-bot.
#
# What it does:
#   1. Installs Python + Caddy (reverse proxy with automatic free HTTPS)
#   2. Sets up a virtualenv and installs requirements.txt
#   3. Registers the bot as a systemd service (auto-restart on crash/reboot)
#   4. Configures Caddy to reverse-proxy a public HTTPS hostname to the app,
#      using a free nip.io hostname so no domain purchase is needed.
#
# Safe to re-run — each step is idempotent.

set -euo pipefail

APP_DIR="/home/ubuntu/whatsapp-correction-bot"
SERVICE_NAME="whatsapp-bot"

if [ ! -d "$APP_DIR" ]; then
  echo "Expected the repo at $APP_DIR — clone it there first:"
  echo "  git clone https://github.com/evaamin/whatsapp-correction-bot.git $APP_DIR"
  exit 1
fi

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git curl debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null 2>&1; then
  echo "==> Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi

echo "==> Setting up virtualenv"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f "$APP_DIR/.env" ]; then
  echo "!! No .env found at $APP_DIR/.env"
  echo "   cp .env.example .env, then fill in real credentials before starting the service."
fi
if [ ! -f "$APP_DIR/centers.json" ]; then
  echo "!! No centers.json found at $APP_DIR/centers.json"
  echo "   cp centers.example.json centers.json, then fill in real center numbers."
fi

echo "==> Installing systemd service"
sudo cp "$APP_DIR/deploy/whatsapp-bot.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "==> Detecting public IP and configuring Caddy"
PUBLIC_IP=$(curl -s https://ifconfig.me)
NIP_HOST="$(echo "$PUBLIC_IP" | tr '.' '-').nip.io"

sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
${NIP_HOST} {
    reverse_proxy localhost:8000
}
EOF
sudo systemctl restart caddy

if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  echo "==> Opening firewall ports 80/443 (ufw)"
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
fi

echo ""
echo "=================================================================="
echo "Done. Your public HTTPS URL is:"
echo ""
echo "  https://${NIP_HOST}"
echo ""
echo "IMPORTANT — you also need to open ports 80 and 443 in the Oracle"
echo "Cloud console's Security List / Network Security Group for this"
echo "VM's subnet (ufw alone isn't enough — OCI has its own cloud-level"
echo "firewall in front of the instance)."
echo ""
echo "Use https://${NIP_HOST}/webhook/whatsapp/meta as the Meta webhook"
echo "callback URL. Check service status with:"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo "=================================================================="
