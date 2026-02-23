#!/usr/bin/env bash
# ═══════════════════════════════════════════════════
# KaiRest POS — Actualizar a la última versión
# Este script actualiza el sistema completo en ~15 seg
# sin necesidad de compilar ni instalar dependencias.
# ═══════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BLUE}${BOLD}🍽  KaiRest POS — Actualizar${NC}"
echo ""

# ── Detect compose command ──
if docker compose version &>/dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo -e "${RED}❌ Docker Compose no encontrado.${NC}"
  exit 1
fi

# ── Determine compose file ──
if [ -f docker-compose.prod.yml ]; then
  COMPOSE_FILE="-f docker-compose.prod.yml"
  echo -e "${BLUE}ℹ ${NC} Usando docker-compose.prod.yml (modo producción)"
elif [ -f docker-compose.yml ]; then
  COMPOSE_FILE=""
  echo -e "${BLUE}ℹ ${NC} Usando docker-compose.yml (modo desarrollo)"
  # In dev mode, pull latest code if git repo
  if [ -d .git ]; then
    echo -e "${BLUE}ℹ ${NC} Descargando última versión del código..."
    git pull --rebase 2>/dev/null || echo "⚠️  No se pudo hacer git pull."
  fi
else
  echo -e "${RED}❌ No se encontró docker-compose.yml ni docker-compose.prod.yml${NC}"
  exit 1
fi

# ── Create backup before updating ──
echo -e "${BLUE}ℹ ${NC} Creando backup de la base de datos..."
mkdir -p backups
$COMPOSE_CMD $COMPOSE_FILE exec -T db pg_dump -Fc -U casaleones casaleones \
  > "backups/pre_update_$(date +%Y%m%d_%H%M%S).dump" 2>/dev/null \
  || echo "⚠️  No se pudo crear backup (¿primera instalación?)."

# ── Pull latest image / rebuild ──
echo -e "${BLUE}ℹ ${NC} Descargando última versión..."
$COMPOSE_CMD $COMPOSE_FILE pull 2>&1 | tail -3

echo -e "${BLUE}ℹ ${NC} Aplicando actualización..."
$COMPOSE_CMD $COMPOSE_FILE up -d 2>&1 | tail -5

# ── Wait for health ──
echo -e "${BLUE}ℹ ${NC} Esperando a que la aplicación inicie..."
PORT="${APP_PORT:-5005}"
for i in $(seq 1 60); do
  if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    echo ""
    VERSION=$(curl -sf "http://localhost:${PORT}/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
    echo -e "${GREEN}${BOLD}✅ KaiRest actualizado y funcionando.${NC}"
    echo -e "${GREEN}   Versión: ${VERSION}${NC}"
    echo -e "${GREEN}   URL: http://localhost:${PORT}${NC}"
    exit 0
  fi
  sleep 2
  printf "."
done

echo ""
echo -e "${RED}⚠️  La app no respondió en 120s. Revisa: $COMPOSE_CMD $COMPOSE_FILE logs web${NC}"
exit 1
