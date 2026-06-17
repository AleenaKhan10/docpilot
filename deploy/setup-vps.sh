#!/usr/bin/env bash
# One-time first-boot setup for the Contabo VPS.
#
# Run this as root after the box comes up:
#   ssh root@YOUR-VPS-IP
#   curl -fsSL https://raw.githubusercontent.com/AleenaKhan10/docpilot/architecture-update/deploy/setup-vps.sh | bash
#
# Or, if you'd rather inspect it first:
#   wget the script, read it, then `bash setup-vps.sh`.
#
# What this does:
#   1. Hardens the host a little (firewall, automatic security updates,
#      a non-root deploy user).
#   2. Installs Docker + Docker Compose plugin.
#   3. Installs nginx + certbot.
#   4. Drops you into /home/docpilot with the repo cloned and ready to fill
#      in .env.

set -euo pipefail

# Non-interactive everything — this script gets piped to `bash` over SSH,
# so there's no TTY and any prompt will hang forever.
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1
APT_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

DEPLOY_USER="docpilot"
APP_DIR="/home/${DEPLOY_USER}/docpilot"
REPO_URL="https://github.com/AleenaKhan10/docpilot.git"
REPO_BRANCH="architecture-update"

log() { echo -e "\n\033[1;36m▶ $*\033[0m"; }

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this as root." >&2
  exit 1
fi

log "Updating apt"
apt-get update
apt-get -y "${APT_OPTS[@]}" upgrade

log "Installing base packages"
apt-get -y "${APT_OPTS[@]}" install \
  ca-certificates curl gnupg lsb-release \
  ufw fail2ban unattended-upgrades \
  nginx certbot python3-certbot-nginx \
  git htop tmux

log "Enabling unattended security updates"
# Write the config directly instead of dpkg-reconfigure, which needs a TTY.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'AUTOCFG'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
AUTOCFG
systemctl enable --now unattended-upgrades.service >/dev/null 2>&1 || true

log "Firewall: allow SSH + HTTP + HTTPS"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
yes | ufw enable || true

log "Creating deploy user '${DEPLOY_USER}'"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG sudo "${DEPLOY_USER}" || true

log "Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
  # Detect distro family (debian vs ubuntu) — Docker has separate repos for each.
  . /etc/os-release
  DOCKER_DISTRO="${ID:-debian}"
  if [[ "${DOCKER_DISTRO}" != "ubuntu" && "${DOCKER_DISTRO}" != "debian" ]]; then
    DOCKER_DISTRO="debian"
  fi
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${DOCKER_DISTRO}/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${DOCKER_DISTRO} ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get -y "${APT_OPTS[@]}" install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

usermod -aG docker "${DEPLOY_USER}"

log "Cloning the repo as ${DEPLOY_USER}"
sudo -u "${DEPLOY_USER}" -H bash <<EOF
set -e
if [ ! -d "${APP_DIR}/.git" ]; then
  git clone --branch ${REPO_BRANCH} ${REPO_URL} ${APP_DIR}
else
  cd ${APP_DIR} && git fetch origin && git checkout ${REPO_BRANCH} && git pull --ff-only
fi
EOF

log "Copying nginx config (you'll customise + reload below)"
cp "${APP_DIR}/deploy/nginx-docpilot.conf" /etc/nginx/sites-available/docpilot
ln -sf /etc/nginx/sites-available/docpilot /etc/nginx/sites-enabled/docpilot

log "Setup complete."
echo
echo "Next steps (run as ${DEPLOY_USER}):"
echo "  1. Edit nginx server_name → your real api.yourdomain.com:"
echo "       sudo nano /etc/nginx/sites-available/docpilot"
echo "  2. Test + reload nginx:"
echo "       sudo nginx -t && sudo systemctl reload nginx"
echo "  3. Issue SSL certs:"
echo "       sudo certbot --nginx -d api.yourdomain.com"
echo "  4. Fill in env:"
echo "       cd ${APP_DIR}"
echo "       cp .env.production.example .env"
echo "       nano .env"
echo "  5. Bring up the stack:"
echo "       docker compose pull && docker compose up -d --build"
echo "  6. Apply DB migrations:"
echo "       docker compose exec api alembic upgrade head"
echo
echo "See DEPLOY.md for the full runbook."
