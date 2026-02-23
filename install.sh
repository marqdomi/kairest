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

# ── Verificar Docker ──
if ! docker info &>/dev/null; then
  echo -e "${RED}❌ Docker no está corriendo.${NC}"
  echo -e "   Abre Docker Desktop primero y vuelve a ejecutar este script."
  echo -e "   Descarga Docker: ${BLUE}https://www.docker.com/products/docker-desktop${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} Docker está corriendo"

# ── Verificar docker compose ──
if docker compose version &>/dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo -e "${RED}❌ Docker Compose no encontrado.${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} Docker Compose disponible"

# ── Crear directorio de la app ──
INSTALL_DIR="${HOME}/kairest"
echo ""
echo -e "${BLUE}📁 Instalando en: ${BOLD}${INSTALL_DIR}${NC}"

mkdir -p "$INSTALL_DIR/backups"
cd "$INSTALL_DIR"

# ── Descargar archivos necesarios ──
REPO_RAW="https://raw.githubusercontent.com/marqdomi/kairest/main"

echo -e "${BLUE}⬇️  Descargando archivos de configuración...${NC}"
curl -sfL "${REPO_RAW}/docker-compose.prod.yml" -o docker-compose.prod.yml 2>/dev/null \
  || curl -sfL "${REPO_RAW}/docker-compose.prod.yml" -o docker-compose.prod.yml
curl -sfL "${REPO_RAW}/update.sh" -o update.sh 2>/dev/null || true
chmod +x update.sh 2>/dev/null || true

echo -e "${GREEN}✓${NC} Archivos descargados"

# ── Configurar .env ──
if [ ! -f .env ]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
  cat > .env << EOF
SECRET_KEY=${SECRET}
POSTGRES_PASSWORD=kairest_$(openssl rand -hex 8 2>/dev/null || echo "secret2026")
APP_PORT=5005
CORS_ORIGINS=http://localhost:5005
EOF
  echo -e "${GREEN}✓${NC} .env creado con SECRET_KEY automática"
else
  echo -e "${YELLOW}ℹ${NC}  .env ya existe — no se modificó"
fi

# ── Levantar servicios ──
echo ""
echo -e "${BLUE}🚀 Iniciando KaiRest POS...${NC}"
echo -e "   (primera vez puede tardar 1-2 min descargando imágenes)"
echo ""

$COMPOSE_CMD -f docker-compose.prod.yml up -d 2>&1 | tail -5

# ── Esperar a que la app esté lista ──
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
    echo -e "   ${YELLOW}Para actualizar:${NC} cd ~/kairest && ./update.sh"
    echo -e "   ${YELLOW}Para detener:${NC}    cd ~/kairest && docker compose -f docker-compose.prod.yml down"
    echo -e "   ${YELLOW}Para reiniciar:${NC}  cd ~/kairest && docker compose -f docker-compose.prod.yml restart"
    echo ""
    exit 0
  fi
  sleep 2
  printf "."
done

echo ""
echo -e "${RED}⚠️  La app no respondió en 3 minutos.${NC}"
echo -e "   Revisa los logs con: $COMPOSE_CMD -f docker-compose.prod.yml logs web"
exit 1
