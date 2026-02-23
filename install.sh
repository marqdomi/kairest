#!/usr/bin/env bash
# ═══════════════════════════════════════════════════
# KaiRest POS — Instalación para Clientes
# Ejecuta este script en la Mac del restaurante
# Requisito: Docker Desktop instalado y corriendo
# ═══════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BLUE}${BOLD}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}${BOLD}║       🍽  KaiRest POS — Instalación     ║${NC}"
echo -e "${BLUE}${BOLD}╚════════════════════════════════════════╝${NC}"
echo ""

# ── Verify Docker ──
if ! docker info &>/dev/null; then
  echo -e "${RED}❌ Docker no está corriendo.${NC}"
  echo -e "   Abre Docker Desktop primero y vuelve a ejecutar este script."
  echo -e "   Descarga Docker: ${BLUE}https://www.docker.com/products/docker-desktop${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} Docker está corriendo"

# ── Verify docker compose ──
if docker compose version &>/dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo -e "${RED}❌ Docker Compose no encontrado.${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} Docker Compose disponible"

# ── Verify git ──
if ! command -v git &>/dev/null; then
  echo -e "${RED}❌ Git no encontrado. Instala con: xcode-select --install${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} Git disponible"

# ── Clone or update repo ──
INSTALL_DIR="${HOME}/kairest"
echo ""
echo -e "${BLUE}📁 Instalando en: ${BOLD}${INSTALL_DIR}${NC}"

if [ -d "$INSTALL_DIR/.git" ]; then
  echo -e "${BLUE}ℹ${NC}  Actualizando código existente..."
  cd "$INSTALL_DIR"
  git pull --rebase 2>/dev/null || echo "⚠️  No se pudo actualizar."
else
  echo -e "${BLUE}⬇️  Descargando KaiRest...${NC}"
  git clone https://github.com/marqdomi/kairest.git "$INSTALL_DIR" 2>&1 | tail -2
  cd "$INSTALL_DIR"
fi

mkdir -p backups
echo -e "${GREEN}✓${NC} Código descargado"

# ── Configure .env ──
if [ ! -f .env ]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
  PG_PASS="kairest_$(openssl rand -hex 8 2>/dev/null || echo 'secret2026')"
  cat > .env << EOF
SECRET_KEY=${SECRET}
POSTGRES_PASSWORD=${PG_PASS}
APP_PORT=5005
CORS_ORIGINS=http://localhost:5005
EOF
  echo -e "${GREEN}✓${NC} .env creado con SECRET_KEY automática"
else
  echo -e "${YELLOW}ℹ${NC}  .env ya existe — no se modificó"
fi

# ── Start services ──
echo ""
echo -e "${BLUE}🚀 Iniciando KaiRest POS...${NC}"
echo -e "   (primera vez puede tardar 2-5 min compilando la imagen)"
echo ""

# Use docker-compose.yml (builds locally — works on any architecture)
$COMPOSE_CMD up -d --build 2>&1 | tail -8

# ── Wait for health ──
echo -e "${BLUE}⏳ Esperando a que la aplicación inicie...${NC}"
PORT="${APP_PORT:-5005}"
for i in $(seq 1 90); do
  if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    echo ""
    echo -e "${GREEN}${BOLD}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║    ✅ KaiRest instalado exitosamente    ║${NC}"
    echo -e "${GREEN}${BOLD}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "   ${BOLD}Abre tu navegador en:${NC}"
    echo -e "   ${BLUE}${BOLD}👉 http://localhost:${PORT}${NC}"
    echo ""
    echo -e "   Verás el asistente de configuración para"
    echo -e "   registrar tu restaurante y crear tu usuario."
    echo ""
    echo -e "   ${YELLOW}Para actualizar:${NC}  cd ~/kairest && ./update.sh"
    echo -e "   ${YELLOW}Para detener:${NC}     cd ~/kairest && docker compose down"
    echo -e "   ${YELLOW}Para reiniciar:${NC}   cd ~/kairest && docker compose restart"
    echo ""
    exit 0
  fi
  sleep 2
  printf "."
done

echo ""
echo -e "${RED}⚠️  La app no respondió en 3 minutos.${NC}"
echo -e "   Revisa los logs con: $COMPOSE_CMD logs web"
exit 1
