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
# Regla: si hay repo git, la instalación se hizo con install.sh (build local,
# docker-compose.yml) — usar el MISMO stack que install.sh para no cambiar de
# estrategia a mitad del ciclo de vida. docker-compose.prod.yml es solo para
# despliegues sin git (imagen pre-construida copiada al servidor).
if [ -d .git ] && [ -f docker-compose.yml ]; then
  COMPOSE_FILE=""
  BUILD_FLAG="--build"
  echo -e "${BLUE}ℹ ${NC} Instalación con git detectada — usando docker-compose.yml (build local)"
  echo -e "${BLUE}ℹ ${NC} Descargando última versión del código..."
  git pull --rebase 2>/dev/null || echo "⚠️  No se pudo hacer git pull."
elif [ -f docker-compose.prod.yml ]; then
  COMPOSE_FILE="-f docker-compose.prod.yml"
  BUILD_FLAG=""
  echo -e "${BLUE}ℹ ${NC} Usando docker-compose.prod.yml (imagen pre-construida)"
elif [ -f docker-compose.yml ]; then
  COMPOSE_FILE=""
  BUILD_FLAG="--build"
  echo -e "${BLUE}ℹ ${NC} Usando docker-compose.yml"
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
if [ -z "$BUILD_FLAG" ]; then
  echo -e "${BLUE}ℹ ${NC} Descargando última imagen..."
  $COMPOSE_CMD $COMPOSE_FILE pull 2>&1 | tail -3
fi

echo -e "${BLUE}ℹ ${NC} Aplicando actualización..."
$COMPOSE_CMD $COMPOSE_FILE up -d $BUILD_FLAG 2>&1 | tail -5

# ── Apply schema migrations ──
# create_all() del arranque solo crea tablas nuevas, nunca altera existentes.
# Alembic aplica los cambios de schema pendientes. Una base creada por create_all
# no tiene historial: se marca c009 (no head) y upgrade aplica el resto. Marcar head
# daba por aplicada la migración más nueva SIN crear sus columnas (create_all no
# altera tablas existentes) y la app tronaba. De c009 en adelante las migraciones son
# idempotentes: revisan con inspector antes de crear.
echo -e "${BLUE}ℹ ${NC} Aplicando migraciones de base de datos..."
sleep 5  # dar tiempo a que los contenedores estén exec-ready
HAS_ALEMBIC=$($COMPOSE_CMD $COMPOSE_FILE exec -T db psql -U casaleones -d casaleones -tAc \
  "SELECT to_regclass('alembic_version') IS NOT NULL" 2>/dev/null | tr -d '[:space:]' || echo "f")
if [ "$HAS_ALEMBIC" != "t" ]; then
  $COMPOSE_CMD $COMPOSE_FILE exec -T web flask db stamp c009 2>/dev/null \
    && echo -e "${GREEN}✓${NC} Historial Alembic iniciado en c009 (primera vez)" \
    || echo "⚠️  No se pudo hacer stamp (se reintentará en la próxima actualización)."
fi
$COMPOSE_CMD $COMPOSE_FILE exec -T web flask db upgrade 2>/dev/null \
  && echo -e "${GREEN}✓${NC} Migraciones aplicadas" \
  || echo "⚠️  No se pudieron aplicar migraciones. Revisa: $COMPOSE_CMD $COMPOSE_FILE logs web"

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
