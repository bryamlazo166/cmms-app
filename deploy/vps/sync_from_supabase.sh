#!/usr/bin/env bash
# Sincronizacion MANUAL Supabase -> PostgreSQL local del VPS.
#
# - Es un refresh completo del schema public (la BD pesa ~30 MB: rapido y barato).
# - Cada corrida deja ademas un backup fechado en ~/cmms/backups (conserva los 10
#   ultimos), asi que sincronizar tambien ES sacar backup.
# - Solo consume egress de Supabase cuando TU la ejecutas (nada automatico).
#
# Uso (en el VPS):        bash ~/cmms/app/deploy/vps/sync_from_supabase.sh
# Uso (desde Windows):    scripts\vps_sync_bd.ps1
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: no existe $ENV_FILE (contiene SUPABASE_DB_URL)"; exit 1
fi

SUPA_URL="$(grep -E '^SUPABASE_DB_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [[ -z "$SUPA_URL" ]]; then
    echo "ERROR: SUPABASE_DB_URL no definida en $ENV_FILE"; exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
DUMP="/backups/supabase_${TS}.dump"

echo "[1/6] Dump de Supabase (schema public, formato custom)..."
docker exec cmms-db pg_dump "$SUPA_URL" -n public -Fc --no-owner --no-privileges -f "$DUMP"
SIZE="$(docker exec cmms-db sh -c "du -h '$DUMP' | cut -f1")"
echo "      OK: $DUMP ($SIZE)"

# La app se detiene durante el refresh: si sigue viva, su db.create_all()
# recrea tablas vacias en cuanto ve el schema vacio y el restore choca.
echo "[2/6] Deteniendo cmms-app durante el refresh..."
docker stop cmms-app >/dev/null
trap 'docker start cmms-app >/dev/null; echo "cmms-app rearrancada."' EXIT

echo "[3/6] Recreando schema public local..."
docker exec -i cmms-db psql -U cmms -d cmms -v ON_ERROR_STOP=1 -q <<'SQL'
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA extensions;
DO $$ BEGIN CREATE ROLE powerbi_reader NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
SQL

echo "[4/6] Restaurando dump en el PostgreSQL local..."
# El dump trae su propio "CREATE SCHEMA public" (ya existe con las extensiones):
# se excluye del indice de restauracion y todo lo demas sigue siendo estricto.
docker exec cmms-db sh -c "pg_restore -l '$DUMP' | grep -v 'SCHEMA - public' > /tmp/restore.list"
docker exec cmms-db pg_restore -U cmms -d cmms --no-owner --no-privileges --exit-on-error -L /tmp/restore.list "$DUMP"

echo "[5/6] Verificacion..."
docker exec cmms-db psql -U cmms -d cmms -t -A -c "
SELECT 'tablas: ' || count(*) FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE';" \
    -c "SELECT 'avisos: ' || count(*) FROM maintenance_notices;" \
    -c "SELECT 'ordenes de trabajo: ' || count(*) FROM work_orders;" \
    -c "SELECT 'puntos de lubricacion: ' || count(*) FROM lubrication_points;"

echo "[6/6] Rotando backups (conservo los 10 mas recientes)..."
docker exec cmms-db sh -c 'ls -1t /backups/supabase_*.dump 2>/dev/null | tail -n +11 | xargs -r rm -f'
docker exec cmms-db sh -c 'ls -1t /backups/supabase_*.dump | head -3'

echo ""
echo "Sincronizacion completada: $(date '+%Y-%m-%d %H:%M:%S')"
