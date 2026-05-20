-- ============================================================================
-- PASO 1 — Verificacion previa antes de activar RLS
--
-- Confirma que la conexion que usa tu app Flask (DATABASE_URL) corre como
-- un rol con BYPASSRLS. Si la respuesta es bypassrls = true, puedes activar
-- RLS sin riesgo de romper la app.
--
-- IMPORTANTE: este SELECT debes ejecutarlo conectado *con la misma cadena
-- DATABASE_URL que usa tu app*, NO desde el SQL Editor del panel (que se
-- conecta como otro rol).
--
-- Opcion A — Desde tu equipo:
--   psql "$env:DATABASE_URL" -c "SELECT current_user, ..."
--
-- Opcion B — En el SQL Editor de Supabase (corre como `postgres` por defecto,
-- que tambien tiene BYPASSRLS, asi que tambien sirve como verificacion).
-- ============================================================================

SELECT
    current_user                                                          AS rol_actual,
    (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)      AS bypassrls,
    (SELECT rolsuper      FROM pg_roles WHERE rolname = current_user)     AS es_superuser;

-- Resultado esperado para que el plan sea seguro:
--   rol_actual debe ser 'postgres' (o un rol con bypassrls = true)
--   bypassrls  debe ser true
--
-- Si bypassrls = false, AVISAME antes de continuar — habria que ajustar
-- el usuario de DATABASE_URL o crear policies especificas.
