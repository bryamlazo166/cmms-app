#!/usr/bin/env bash
# Actualizacion MANUAL del codigo del CMMS en el VPS desde GitHub (primario).
#
# Uso (en el VPS):        bash ~/cmms/app/deploy/vps/update_app.sh
# Uso (desde Windows):    scripts\vps_actualizar_app.ps1
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$DIR/../.." && pwd)"

echo "[1/3] git pull (main)..."
cd "$REPO_DIR"
git fetch origin main
git reset --hard origin/main

echo "[2/3] Reconstruyendo imagen de la app..."
cd "$DIR"
docker compose build app

echo "[3/3] Reiniciando contenedor..."
docker compose up -d app

echo ""
docker ps --filter name=cmms --format 'table {{.Names}}\t{{.Status}}'
echo "Actualizacion completada: $(date '+%Y-%m-%d %H:%M:%S')"
