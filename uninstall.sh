#!/usr/bin/env bash
# CasaLeones POS — Detener y limpiar containers
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${RED}${BOLD}🦁 CasaLeones POS — Desinstalar${NC}"
echo ""

# Detect compose command
if docker compose version &>/dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo -e "${RED}❌ Docker Compose no encontrado.${NC}"
  exit 1
fi

echo -e "${YELLOW}⚠️  Esto detendrá CasaLeones y eliminará los containers.${NC}"
echo ""
read -p "¿Eliminar también la base de datos? (s/N): " DELETE_DB

$COMPOSE_CMD down

if [[ "${DELETE_DB,,}" == "s" || "${DELETE_DB,,}" == "si" || "${DELETE_DB,,}" == "sí" ]]; then
  echo "Eliminando volúmenes de datos..."
  $COMPOSE_CMD down -v
  echo -e "${GREEN}✅ Containers y base de datos eliminados.${NC}"
else
  echo -e "${GREEN}✅ Containers detenidos. La base de datos se conserva.${NC}"
fi

echo ""
echo "Para reinstalar: ./install.sh"
