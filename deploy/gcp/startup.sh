#!/bin/bash
# Script de arranque de la VM (metadata startup-script). Corre como root en CADA
# arranque: la primera vez instala todo; las siguientes sólo levanta el stack.
#
# Metadata que lee:
#   dominio  — p. ej. casaleones.kainet.mx
#   repo     — URL del repo git (default: https://github.com/marqdomi/kairest.git)
#   rama     — rama a desplegar (default: main)
set -euo pipefail

meta() {
  curl -sf -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" || true
}

DOMINIO="$(meta dominio)"
REPO="$(meta repo)"; REPO="${REPO:-https://github.com/marqdomi/kairest.git}"
RAMA="$(meta rama)"; RAMA="${RAMA:-main}"
DIR=/opt/kairest

# ── Swap: con 1 GB de RAM el build de la imagen y Postgres no caben sin él ──
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon -a || true

# ── Docker ──
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
fi

# ── Código ──
if [ ! -d "$DIR/.git" ]; then
  git clone --branch "$RAMA" "$REPO" "$DIR"
fi

cd "$DIR/deploy/gcp"

# ── .env con secretos generados una sola vez ──
if [ ! -f .env ]; then
  umask 077
  cat > .env <<EOF
DOMINIO=${DOMINIO}
SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
EOF
fi

mkdir -p backups
docker compose up -d --build
